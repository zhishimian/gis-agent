from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from threading import Event
from time import perf_counter
from typing import Any, TypedDict

from gis_agent.core.auxiliary import AuxiliaryError
from gis_agent.core.context import ContextLimit, ContextManager
from gis_agent.core.events import EventCallback, emit_event
from gis_agent.core.loop import AgentLoopRunner
from gis_agent.core.memory import MemoryStore, MemoryTurn, extract_memories
from gis_agent.core.model import ModelReply
from gis_agent.core.planning import Plan
from gis_agent.persistence.evidence import tool_result
from gis_agent.persistence.executions import ExecutionHistory, execution_id, record_history
from gis_agent.persistence.json import json_text
from gis_agent.persistence.sessions import SessionStore, message_units
from gis_agent.prompts import render_prompt
from gis_agent.tools.base import Tool
from gis_agent.tools.registry import ToolRegistry


logger = logging.getLogger(__name__)
PASSIVE_TOOLS = {
    "update_plan", "finish_task", "read_session_messages", "execution_history",
    "search_memory", "remember_memory", "forget_memory",
    "list_files", "read_file", "search_text", "inspect_data", "summarize_fields",
    "check_spatial_relation", "read_image", "search_qgis_tools", "calculate_distance",
}


class RunState(TypedDict):
    version: int
    turn_start: int
    model_index: int
    responses_used: int
    execution_started: bool
    algorithms: list[str]
    callable_names: list[str]
    memory_errors: list[str]
    handled_sources: list[int]
    handled_bodies: list[str]
    background: str
    record_hash: str
    auxiliary_used: int
    outcome: dict[str, Any] | None


@dataclass
class Agent:
    registry: ToolRegistry
    base_tools: list[Tool]
    load_qgis_tool: Callable[[str], Tool] | None
    plan: Plan
    instructions: str
    chat: Callable[..., ModelReply]
    store: SessionStore
    context: ContextManager
    memory: MemoryStore | None = None
    memory_turn: MemoryTurn | None = None
    checkpointer: Any = None
    history: ExecutionHistory | None = None
    on_event: EventCallback | None = None
    cancel_event: Event | None = None
    workspace_context: dict[str, Any] | None = None
    runtime_capabilities: dict[str, Any] | None = None
    graph: AgentLoopRunner = field(init=False, repr=False)
    messages: list[dict[str, Any]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.memory is not None and self.memory_turn is None:
            raise ValueError("启用记忆时必须提供 MemoryTurn。")
        self.graph = AgentLoopRunner(self.model, self.tools, self.finish, self.checkpointer)

    def _is_cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def options(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": self.store.session_id}, "recursion_limit": 16}

    def record_hash(self) -> str:
        return hashlib.sha256(self.store.path.read_bytes()).hexdigest()

    def verify_record(self, state: RunState) -> None:
        if self.record_hash() != state["record_hash"]:
            raise ValueError(
                "Session 已领先于检查点或被外部修改，不能自动重放。"
                "请检查已有产物和执行标记；必要时新建会话并提供已有成果路径。"
            )

    def _reconcile_completed_batch(self, snapshot: Any) -> bool:
        """若工具批次已在 Session 全部标记 finished 并通过完整性检查，而 SQLite 尚未推进，安全向前对齐。"""
        if snapshot.next != ("tools",):
            return False
        try:
            records = self.store.read_record()
            message_units(records)
        except (OSError, ValueError):
            return False
        idx = snapshot.values.get("model_index")
        if not isinstance(idx, int) or idx >= len(records):
            return False
        assistant_msg = records[idx]
        calls = assistant_msg.get("tool_calls") or []
        executions = assistant_msg.get("executions") or {}
        if not calls or any(executions.get(c["id"]) != "finished" for c in calls):
            return False
        prefix = [*records[:idx], {k: v for k, v in assistant_msg.items() if k != "executions"}]
        if hashlib.sha256(json_text(prefix).encode("utf-8")).hexdigest() != snapshot.values.get("record_hash"):
            return False
        self.graph.update_state(
            self.options(),
            {"model_index": len(records), "record_hash": self.record_hash()},
            as_node="tools",
        )
        return True

    def recall(self, start: int) -> str:
        if self.memory is None:
            return ""
        query = self.messages[start]["content"] + " " + self.plan.goal
        return json.dumps(self.memory.recall(query), ensure_ascii=False)

    def run(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        previous = self.graph.get_state(self.options())
        if previous.next:
            raise ValueError("当前会话仍有待续跑的图，请先调用 resume。")
        message_units(messages)
        self.messages = messages
        self.context.auxiliary.reset()
        start = len(messages) - 1
        if start < 0 or messages[start]["role"] != "user" or messages[start].get("origin") not in {"user", "delegation"}:
            raise ValueError("新一轮必须从用户输入或委派输入开始。")
        if self.memory_turn is not None:
            self.memory_turn.reset(start)
        self.store.save(messages)
        emit_event(self.on_event, "turn_started", self.store.session_id, turn_start=start)
        state: RunState = {
            "version": 900,
            "turn_start": start,
            "model_index": len(messages),
            "responses_used": 0,
            "execution_started": False,
            "algorithms": list(previous.values.get("algorithms", [])) if messages[start].get("in_reply_to") else [],
            "callable_names": [],
            "memory_errors": [],
            "handled_sources": [],
            "handled_bodies": [],
            "background": self.recall(start),
            "record_hash": self.record_hash(),
            "auxiliary_used": 0,
            "outcome": None,
        }
        return self.drive(state)

    def resume(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        snapshot = self.graph.get_state(self.options())
        if not snapshot.next:
            raise ValueError("没有待续跑的检查点。")
        if snapshot.values.get("version") not in {790, 810, 900}:
            raise ValueError("检查点来自旧版执行流程，请保留原记录，新建会话并提供已有成果路径。")
        if self.record_hash() != snapshot.values["record_hash"]:
            if not self._reconcile_completed_batch(snapshot):
                self.verify_record(snapshot.values)
            snapshot = self.graph.get_state(self.options())
        messages[:] = self.store.read_record()
        self.messages = messages
        restored = Plan.from_messages(messages)
        self.plan.goal, self.plan.steps = restored.goal, restored.steps
        self.context.auxiliary.used = snapshot.values["auxiliary_used"]
        if self.memory_turn is not None:
            self.memory_turn.reset(snapshot.values["turn_start"])
            self.memory_turn.handled_sources.update(snapshot.values["handled_sources"])
            self.memory_turn.handled_bodies.update(snapshot.values["handled_bodies"])
        return self.drive(None)

    def drive(self, state: RunState | None) -> dict[str, Any]:
        while True:
            self.graph.invoke(state, self.options())
            snapshot = self.graph.get_state(self.options())
            if not snapshot.next:
                return snapshot.values["outcome"]
            self.verify_record(snapshot.values)
            state = None

    def available(self, state: RunState) -> list[Tool]:
        tools = {tool.name: tool for tool in self.base_tools}
        if self.load_qgis_tool is not None:
            for algorithm_id in state["algorithms"]:
                tool = self.load_qgis_tool(algorithm_id)
                tools[tool.name] = tool
        return list(tools.values())

    def model(self, state: RunState) -> dict[str, Any]:
        message_units(self.messages)
        if self._is_cancelled():
            return {
                "outcome": {
                    "ok": True,
                    "status": "cancelled",
                    "summary": "任务已由用户主动中止，已完成阶段的产物已保留。",
                },
                "record_hash": self.record_hash(),
            }
        business: dict[str, Any] = {
            "latest_user_message": max(
                i for i, item in enumerate(self.messages)
                if item["role"] == "user" and item.get("origin") != "program"
            ),
            "recent_tool_messages": {
                item["tool_call_id"]: i
                for i, item in enumerate(self.messages)
                if item["role"] == "tool" and i >= len(self.messages) - 20
            },
        }
        if self.workspace_context:
            business["workspace_context"] = self.workspace_context
        if self.runtime_capabilities:
            business["runtime_capabilities"] = self.runtime_capabilities
        if alert := _stagnation_alert(self.store, self.messages[state["turn_start"] :]):
            business["stagnation_alert"] = alert
        latest = self.messages[business["latest_user_message"]]
        if latest.get("in_reply_to"):
            business["answer_to_request"] = latest["in_reply_to"]
        try:
            request = self.context.prepare(
                self.instructions, self.messages, business, self.available(state), state["background"]
            )
        except (ContextLimit, AuxiliaryError) as error:
            return {"outcome": {"ok": False, "status": "blocked", "summary": str(error)}}
        if self._is_cancelled():
            return {
                "outcome": {
                    "ok": True,
                    "status": "cancelled",
                    "summary": "任务已由用户主动中止，已完成阶段的产物已保留。",
                },
                "record_hash": self.record_hash(),
            }
        reply = self.chat(request.messages, request.schemas)
        self.store.record_model_call({"purpose": "main", **reply.metadata()})
        emit_event(
            self.on_event, "model_replied", self.store.session_id,
            finish_reason=reply.finish_reason, estimated_tokens=request.estimated_tokens, usage=reply.usage,
        )
        logger.info("模型返回：%s；请求估算 token：%s", reply.metadata(), request.estimated_tokens)
        outcome = None
        if reply.finish_reason not in {"stop", "tool_calls"}:
            message = {
                "role": "assistant",
                "content": "模型响应未完整结束，未执行其中的工具调用。",
                "response": {**reply.metadata(), "raw_message": reply.message},
            }
            outcome = {"ok": False, "status": "blocked", "summary": f"模型结束状态为 {reply.finish_reason}，请检查输出预算。"}
        else:
            message = {**reply.message, "response": reply.metadata()}
            if not message.get("tool_calls"):
                message.pop("tool_calls", None)
        self.messages.append(message)
        self.store.save(self.messages)
        retained_algorithms = (
            [
                algorithm for algorithm in state["algorithms"]
                if self.load_qgis_tool(algorithm).name in request.callable_names
            ]
            if self.load_qgis_tool is not None
            else []
        )
        return {
            "responses_used": state["responses_used"] + 1,
            "algorithms": retained_algorithms,
            "callable_names": sorted(request.callable_names),
            "record_hash": self.record_hash(),
            "auxiliary_used": self.context.auxiliary.used,
            "outcome": outcome,
        }

    def tools(self, state: RunState) -> RunState:
        state = dict(state)
        message = self.messages[state["model_index"]]
        calls = message.get("tool_calls", [])
        self.available(state)
        if not calls:
            self.messages.append({"role": "user", "origin": "program", "content": render_prompt("continue.txt")})
            self.store.save(self.messages)
        for slot, call in enumerate(calls):
            name = call["function"]["name"]
            identifier = None
            elapsed_ms = 0.0
            if self._is_cancelled():
                result: Any = {"ok": False, "status": "cancelled", "cancelled": True, "error": "任务已中止，该调用未启动。"}
            else:
                try:
                    arguments = json.loads(call["function"]["arguments"])
                except json.JSONDecodeError as error:
                    result = {"ok": False, "error": f"工具参数不是有效 JSON：{error}"}
                else:
                    if not isinstance(arguments, dict):
                        result = {"ok": False, "error": "工具参数必须是 JSON 对象。"}
                    elif name not in state["callable_names"]:
                        result = {"ok": False, "error": f"本次没有提供工具 {name}，请核对可用工具列表。"}
                    elif name == "finish_task" and len(calls) != 1:
                        result = {"ok": False, "error": "finish_task 必须单独调用。"}
                    else:
                        message.setdefault("executions", {})[call["id"]] = "started"
                        self.store.save(self.messages)
                        emit_event(self.on_event, "tool_started", self.store.session_id, tool=name, call_id=call["id"])
                        if self.history is not None:
                            identifier = execution_id(state["model_index"], slot)
                            record_history(
                                self.history.begin, state["model_index"], slot, call,
                                self.registry.get(name).execution_metadata,
                            )
                        if name not in PASSIVE_TOOLS:
                            state["execution_started"] = True
                        started = perf_counter()
                        try:
                            result = self.registry.execute(name, arguments)
                        except Exception as error:
                            if identifier is not None:
                                record_history(self.history.raised, identifier, error, (perf_counter() - started) * 1000)
                            raise
                        elapsed_ms = (perf_counter() - started) * 1000
                        if name == "search_qgis_tools" and isinstance(result, list) and self.load_qgis_tool is not None:
                            algorithms = list(state["algorithms"])
                            for item in result:
                                tool = self.load_qgis_tool(item["algorithm_id"])
                                if item["algorithm_id"] in algorithms:
                                    algorithms.remove(item["algorithm_id"])
                                algorithms.append(item["algorithm_id"])
                                item["tool_name"] = tool.name
                            state["algorithms"] = algorithms
                        if name == "finish_task" and result["ok"]:
                            result = self.accept_finish(result, state)
                        message["executions"][call["id"]] = "finished"
                        tool_outputs = result.get("outputs", []) if isinstance(result, dict) and "outputs" in result else []
                        emit_event(
                            self.on_event, "tool_finished", self.store.session_id,
                            tool=name, call_id=call["id"], ok=result.get("ok") if isinstance(result, dict) else True,
                            elapsed_ms=elapsed_ms, outputs=tool_outputs,
                        )
            if name in {"remember_memory", "forget_memory"}:
                errors = set(state["memory_errors"])
                if isinstance(result, dict) and result.get("ok"):
                    errors.discard(name)
                    state["background"] = self.recall(state["turn_start"])
                else:
                    errors.add(name)
                state["memory_errors"] = sorted(errors)
            stored = self.store.tool_message(call["id"], name, result, self.context.config.tool_limit)
            if identifier is not None:
                stored["execution_id"] = identifier
                record_history(self.history.complete, identifier, stored, len(self.messages), elapsed_ms, arguments)
            self.messages.append(stored)
            self.store.save(self.messages)
            logger.info("工具 %s：%s", name, stored["content"][:1200])
        if self._is_cancelled() and state.get("outcome") is None:
            state["outcome"] = {
                "ok": True,
                "status": "cancelled",
                "summary": "任务已由用户主动中止，子进程树已清理，已完成阶段的产物已保留。",
            }
        state["model_index"] = len(self.messages)
        state["record_hash"] = self.record_hash()
        if self.memory_turn is not None:
            state["handled_sources"] = sorted(self.memory_turn.handled_sources)
            state["handled_bodies"] = sorted(self.memory_turn.handled_bodies)
        return state

    def accept_finish(self, result: dict[str, Any], state: RunState) -> dict[str, Any]:
        status = result["status"]
        if state["memory_errors"] and status in {"answer", "completed"}:
            return {"ok": False, "error": "记忆操作仍有失败项，请重试对应操作或报告 blocked。"}
        if status == "answer" and state["execution_started"]:
            return {"ok": False, "error": "本轮已执行操作，请报告任务状态。"}
        if status == "completed" and self.plan.unfinished():
            return {"ok": False, "error": "计划仍有未完成项，请继续处理或报告阻碍。", "unfinished": self.plan.unfinished()}
        if status == "cancelled" and not any(
            message.get("cancelled_request") for message in self.messages[state["turn_start"] :]
        ):
            return {"ok": False, "error": "cancelled需用户明确取消；无法完成请用blocked/partial或提出必要问题。"}
        if status in {"partial", "blocked", "needs_input"} and self.plan.unfinished():
            result = result | {"unfinished_plan": self.plan.unfinished()}
        if status == "completed":
            anomalies_by_path, verified_after, last_failed = _artifact_diagnostics(
                self.store, self.messages[state["turn_start"] :]
            )
            ack = set(result.get("acknowledged_anomalies") or [])
            pending_l2: list[dict[str, Any]] = []
            for art in result.get("artifacts") or []:
                norm = _norm_path(art)
                anoms = anomalies_by_path.get(norm, [])
                for anom in anoms:
                    if anom.get("level") == "fatal":
                        return {
                            "ok": False,
                            "error": f"交付产物存在致命读取异常（{anom.get('code')}），请修复后再 completed，或改用 partial/blocked。",
                            "path": art,
                            "anomaly": anom,
                        }
                if norm in last_failed:
                    return {
                        "ok": False,
                        "error": "该交付产物关联的最近一次执行仍为失败状态；请重新运行成功并核验后再 completed，或改用 partial/blocked。",
                        "path": art,
                    }
                if norm not in verified_after and "ALL" not in ack:
                    for anom in anoms:
                        if anom.get("level") == "warning" and anom.get("code") not in ack:
                            pending_l2.append({**anom, "path": art})
            if pending_l2:
                return {
                    "ok": False,
                    "error": (
                        "检测到交付产物存在空间告警信号，请先修复或核实；若确认为任务预期现象或原数据固有局限，"
                        "请在 summary 中说明并在 acknowledged_anomalies 中传入对应编码后重试 finish_task，或改用 partial/blocked。"
                    ),
                    "anomalies": pending_l2,
                }
        state["outcome"] = result
        return result

    def finish(self, state: RunState) -> dict[str, Any]:
        outcome = dict(state["outcome"])
        self.messages.append({"role": "assistant", "content": outcome["summary"]})
        self.store.save(self.messages)
        if self.memory is not None and outcome["status"] in {"answer", "completed"}:
            try:
                maintenance = extract_memories(self.memory, self.store, self.messages, self.memory_turn, self.context.auxiliary)
            except (OSError, ValueError, KeyError, TypeError) as error:
                maintenance = {"status": "failed", "error": str(error)}
            outcome["memory"] = maintenance
            self.store.record_model_call({"purpose": "memory_maintenance", **maintenance})
        emit_event(self.on_event, "turn_finished", self.store.session_id, status=outcome.get("status"))
        return {"outcome": outcome, "record_hash": self.record_hash(), "model_index": len(self.messages)}


_EXC_RE = re.compile(r"\b([A-Za-z]+Error|Exception)\b")


def _norm_path(raw: str) -> str:
    clean = raw.split("|layername=", 1)[0]
    try:
        return os.path.normcase(str(Path(clean).expanduser().resolve()))
    except OSError:
        return os.path.normcase(clean)


def _safe_tool_payload(store: SessionStore, item: dict[str, Any]) -> Any:
    try:
        return tool_result(store, item)
    except Exception:
        return None


def _turn_call_index(messages_slice: list[dict[str, Any]]) -> dict[str, tuple[str, dict[str, Any]]]:
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    for msg in messages_slice:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else {}
            except Exception:
                args = {}
            calls[str(tc.get("id") or "")] = (name, args if isinstance(args, dict) else {})
    return calls


def _failure_signature(tool_name: str, args: dict[str, Any], payload: dict[str, Any]) -> str:
    target = ""
    if tool_name == "run_python_script":
        raw = args.get("script_path") or ""
        target = Path(str(raw)).name if raw else ""
    elif tool_name == "run_qgis_algorithm":
        target = str(args.get("algorithm_id") or "")
    err_text = str(payload.get("stderr") or payload.get("error") or "")
    tail = "\n".join(err_text.splitlines()[-3:])
    exc_match = _EXC_RE.findall(tail)
    exc = exc_match[-1] if exc_match else next((line.strip()[:60] for line in err_text.splitlines() if line.strip()), "failed")
    return ":".join(part for part in (tool_name, target, exc) if part)


def _stagnation_alert(store: SessionStore, messages_slice: list[dict[str, Any]]) -> dict[str, Any] | None:
    calls = _turn_call_index(messages_slice)
    signatures: list[str] = []
    for msg in reversed(messages_slice):
        if msg.get("role") != "tool":
            continue
        call_id = str(msg.get("tool_call_id") or "")
        name, args = calls.get(call_id, (str(msg.get("tool_name") or ""), {}))
        if name in PASSIVE_TOOLS:
            continue
        payload = _safe_tool_payload(store, msg)
        if isinstance(payload, dict) and payload.get("ok") is True:
            break
        if isinstance(payload, dict) and payload.get("ok") is False:
            signatures.append(_failure_signature(name, args, payload))
    if not signatures:
        return None
    latest = signatures[0]
    repeated = sum(1 for sig in signatures if sig == latest)
    count = len(signatures)
    if count >= 5:
        return {
            "level": "escalate",
            "consecutive_failures": count,
            "repeated_signature": latest,
            "advice": "连续执行失败已达上限；请勿继续微调同类重试，立即切换全新底层方法或调用 finish_task(status='blocked'|'needs_input'|'partial') 诚实报告已知阻碍。",
        }
    if repeated >= 2 or count >= 3:
        return {
            "level": "warn",
            "consecutive_failures": count,
            "repeated_signature": latest,
            "advice": "同一错误连续出现；请停止盲目重跑，先用 inspect_data/summarize_fields 或极小样本探针核对输入与 Schema，或读取对应 Skill 参考文档切换路线。",
        }
    return None


def _artifact_diagnostics(
    store: SessionStore, messages_slice: list[dict[str, Any]]
) -> tuple[dict[str, list[dict[str, Any]]], set[str], set[str]]:
    calls = _turn_call_index(messages_slice)
    anomalies_by_path: dict[str, list[dict[str, Any]]] = {}
    verified_after: set[str] = set()
    last_failed: set[str] = set()

    for msg in messages_slice:
        if msg.get("role") != "tool":
            continue
        call_id = str(msg.get("tool_call_id") or "")
        name, args = calls.get(call_id, (str(msg.get("tool_name") or ""), {}))
        payload = _safe_tool_payload(store, msg)
        if not isinstance(payload, dict):
            continue

        if name == "run_python_script" or isinstance(payload.get("outputs"), list):
            outputs = payload.get("outputs") or []
            if payload.get("ok") is True:
                for item in outputs:
                    raw_p = item.get("path")
                    if isinstance(raw_p, str):
                        norm = _norm_path(raw_p)
                        last_failed.discard(norm)
                        anomalies_by_path[norm] = list(item.get("anomalies") or [])
                        verified_after.discard(norm)
            else:
                for item in outputs:
                    raw_p = item.get("path")
                    if isinstance(raw_p, str):
                        last_failed.add(_norm_path(raw_p))
        elif name == "run_qgis_algorithm":
            if payload.get("ok") is True:
                outputs_map = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}
                anom_map = payload.get("anomalies") if isinstance(payload.get("anomalies"), dict) else {}
                for key, raw_p in outputs_map.items():
                    if isinstance(raw_p, str):
                        norm = _norm_path(raw_p)
                        last_failed.discard(norm)
                        anomalies_by_path[norm] = list(anom_map.get(key) or [])
                        verified_after.discard(norm)
            elif isinstance(args.get("parameters"), dict):
                for val in args["parameters"].values():
                    if isinstance(val, str) and any(val.lower().endswith(ext) for ext in (".gpkg", ".tif", ".tiff", ".shp", ".geojson")):
                        last_failed.add(_norm_path(val))
        elif name in {"summarize_fields", "inspect_data", "check_spatial_relation"} and payload.get("ok") is True:
            for key in ("source", "reference"):
                if isinstance(args.get(key), str):
                    verified_after.add(_norm_path(args[key]))
            for src in args.get("sources") or ():
                if isinstance(src, str):
                    verified_after.add(_norm_path(src))

    return anomalies_by_path, verified_after, last_failed
