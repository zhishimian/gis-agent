from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
import hashlib
import os
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

from openai import DefaultHttpxClient, OpenAI

from gis_agent.adapters.stubs import WorkspaceContext
from gis_agent.agent import Agent
from gis_agent.config import AppConfig
from gis_agent.core.auxiliary import AuxiliaryCalls
from gis_agent.core.context import ContextManager
from gis_agent.core.events import EventCallback
from gis_agent.core.memory import MemoryStore, MemoryTurn
from gis_agent.core.model import ModelReply, TokenCounter
from gis_agent.core.planning import Plan
from gis_agent.integrations.llm import chat, make_token_counter
from gis_agent.integrations.qgis.catalog import load_catalog, make_search_tool
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.persistence.checkpoints import SqliteCheckpointer
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.interaction import latest_outcome
from gis_agent.persistence.json import json_text
from gis_agent.persistence.sessions import SessionStore
from gis_agent.prompts import render_prompt
from gis_agent.runtime.probe import runtime_capabilities
from gis_agent.skills import skill_index
from gis_agent.tools.base import Tool
from gis_agent.tools.builtin import builtin_tools
from gis_agent.tools.files import make_file_tools
from gis_agent.tools.history import make_history_tool
from gis_agent.tools.images import make_image_tool
from gis_agent.tools.memory import make_memory_tools
from gis_agent.tools.planning import make_planning_tools
from gis_agent.tools.qgis_alg import make_run_qgis_tool
from gis_agent.tools.qgis_python import make_qgis_python_tools
from gis_agent.tools.registry import ToolRegistry
from gis_agent.tools.session import make_session_tool


@dataclass
class Conversation:
    agent: Agent
    messages: list[dict[str, Any]]
    output_dir: Path
    cancel_event: Event = field(default_factory=Event)
    workspace_context: WorkspaceContext | None = None

    def request_stop(self) -> None:
        """供桌面端与 QGIS 插件主线程安全调用，协作式中止当前轮次并回收子进程树。"""
        self.cancel_event.set()

    def update_workspace_context(self, context: WorkspaceContext | None) -> None:
        self.workspace_context = context
        self.agent.workspace_context = context.to_dict() if context is not None else None

    @property
    def pending(self) -> bool:
        return bool(self.agent.graph.get_state(self.agent.options()).next)

    def send(self, text: str) -> dict[str, Any]:
        if self.pending:
            raise ValueError("请先续跑当前任务，再提交新输入。")
        if not text.strip():
            raise ValueError("回复不能为空。")
        if self.waiting:
            return self.reply(text)
        self._verify_boundary()
        self.cancel_event.clear()
        self.messages.append({"role": "user", "origin": "user", "content": text})
        return self.agent.run(self.messages)

    @property
    def waiting(self) -> dict | None:
        outcome = latest_outcome(self.agent.store, self.messages)
        return outcome if outcome and outcome["status"] == "needs_input" else None

    def _verify_boundary(self) -> None:
        if self.messages != self.agent.store.read_record():
            raise ValueError("Session已被其他客户端修改，请重新打开。")
        snapshot = self.agent.graph.get_state(self.agent.options())
        if snapshot.values:
            if (
                not snapshot.next
                and self.messages
                and self.messages[-1].get("cancelled_request")
                and self.agent.record_hash() != snapshot.values.get("record_hash")
            ):
                prefix = self.messages[:-1]
                previous = latest_outcome(self.agent.store, prefix)
                if (
                    hashlib.sha256(json_text(prefix).encode("utf-8")).hexdigest() == snapshot.values["record_hash"]
                    and previous
                    and previous["status"] == "needs_input"
                    and previous["request_id"] == self.messages[-1]["cancelled_request"]
                ):
                    self.agent.graph.update_state(
                        self.agent.options(),
                        {
                            "outcome": self.messages[-1]["cancellation"],
                            "record_hash": self.agent.record_hash(),
                            "model_index": len(self.messages),
                        },
                        as_node="finish",
                    )
                    snapshot = self.agent.graph.get_state(self.agent.options())
            self.agent.verify_record(snapshot.values)

    def reply(self, text: str, *, request_id: str | None = None, reply_id: str | None = None) -> dict:
        if self.pending:
            raise ValueError("请先续跑现有检查点。")
        waiting = self.waiting
        if not waiting or (request_id is not None and request_id != waiting["request_id"]):
            raise ValueError("问题已处理或request_id与当前等待不符。")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("回复不能为空；可退出保留问题，或取消任务。")
        reply_id = reply_id or uuid4().hex
        if any(m.get("reply_id") == reply_id for m in self.messages):
            raise ValueError("该reply_id已提交，不重复执行。")
        self._verify_boundary()
        self.cancel_event.clear()
        self.messages.append(
            {
                "role": "user",
                "origin": "user",
                "content": text.strip(),
                "in_reply_to": waiting["request_id"],
                "reply_id": reply_id,
            }
        )
        return self.agent.run(self.messages)

    @property
    def pending_answer(self) -> bool:
        return bool(not self.pending and self.messages and self.messages[-1].get("in_reply_to"))

    def continue_answer(self) -> dict:
        if not self.pending_answer:
            raise ValueError("没有尚未执行的补充信息。")
        snapshot = self.agent.graph.get_state(self.agent.options())
        prefix = self.messages[:-1]
        expected = hashlib.sha256(json_text(prefix).encode("utf-8")).hexdigest()
        if (
            snapshot.values.get("record_hash") != expected
            or snapshot.values.get("outcome", {}).get("status") != "needs_input"
            or latest_outcome(self.agent.store, prefix)["request_id"] != self.messages[-1]["in_reply_to"]
        ):
            raise ValueError("补充信息与原等待检查点不符，拒绝自动执行。")
        if self.messages != self.agent.store.read_record():
            raise ValueError("Session记录已变化。")
        self.cancel_event.clear()
        return self.agent.run(self.messages)

    def cancel(self) -> dict:
        if self.pending or not self.waiting:
            raise ValueError("只允许取消已安全等待的任务；运行中任务请调用 request_stop()。")
        self._verify_boundary()
        waiting = self.waiting
        result = {
            "ok": True,
            "status": "cancelled",
            "summary": "用户取消，已有成果保留。",
            "artifacts": waiting.get("artifacts", []),
            "unresolved": waiting.get("unresolved", []),
        }
        self.messages.append(
            {
                "role": "user",
                "origin": "user",
                "content": "取消当前等待任务。",
                "cancelled_request": waiting["request_id"],
                "cancellation": result,
            }
        )
        self.agent.store.save(self.messages)
        self.agent.graph.update_state(
            self.agent.options(),
            {"outcome": result, "record_hash": self.agent.record_hash(), "model_index": len(self.messages)},
            as_node="finish",
        )
        return result

    def resume(self) -> dict[str, Any]:
        self.cancel_event.clear()
        return self.agent.resume(self.messages)


@dataclass
class AgentFactory:
    config: AppConfig
    call: Callable[..., ModelReply]
    count_tokens: TokenCounter
    qgis: QGISClient | None = None
    catalog: dict[str, dict[str, Any]] | None = None

    def create(
        self,
        store: SessionStore,
        messages: list[dict[str, Any]],
        output_dir: Path,
        saver: Any,
        instructions: str,
        *,
        extra_tools: list[Tool] | None = None,
        memory: MemoryStore | None = None,
        turn: MemoryTurn | None = None,
        allowed_write_roots: tuple[Path, ...] = (),
        protected_paths: tuple[Path, ...] = (),
        on_event: EventCallback | None = None,
        cancel_event: Event | None = None,
        workspace_context: WorkspaceContext | None = None,
    ) -> Agent:
        plan = Plan.from_messages(messages)
        registry = ToolRegistry()
        history = ExecutionHistory(store, output_dir)
        planning = make_planning_tools(plan, output_dir=output_dir)
        help_cache: dict[str, dict[str, Any]] = {}
        python_launcher = self.config.python_launcher
        qgis_tools: list[Tool] = []
        if self.qgis is not None and self.catalog is not None:
            qgis_tools = [
                make_search_tool(self.catalog, self.qgis, help_cache),
                make_run_qgis_tool(
                    self.qgis,
                    self.catalog,
                    help_cache,
                    protected_paths=protected_paths,
                    cancel_event=cancel_event,
                ),
            ]
        tools = [
            *builtin_tools,
            *make_file_tools(allowed_roots=allowed_write_roots, protected_paths=protected_paths),
            *qgis_tools,
            *make_qgis_python_tools(
                python_launcher,
                output_dir / "python_logs",
                self.config.font_files,
                watch_roots=(output_dir,),
                protected_paths=protected_paths,
                cancel_event=cancel_event,
            ),
            *planning,
            make_session_tool(store),
            make_history_tool(history),
            *(extra_tools or []),
        ]
        if self.config.model.supports_images:
            tools.append(make_image_tool(store.root / f"{store.session_id}.assets" / "images"))
        if memory is not None:
            tools.extend(make_memory_tools(memory, store, messages, turn))
        for tool in tools:
            registry.register(tool)
        ws_dict = workspace_context.to_dict() if workspace_context is not None else None
        return Agent(
            registry=registry,
            base_tools=tools,
            load_qgis_tool=None,
            plan=plan,
            instructions=instructions,
            chat=self.call,
            store=store,
            context=ContextManager(
                store,
                self.config.context,
                AuxiliaryCalls(
                    self.call,
                    store.record_model_call,
                    self.count_tokens,
                    self.config.context.request_token_limit,
                ),
                {tool.name for tool in tools},
            ),
            memory=memory,
            memory_turn=turn,
            checkpointer=saver,
            history=history,
            on_event=on_event,
            cancel_event=cancel_event,
            workspace_context=ws_dict or None,
            runtime_capabilities=runtime_capabilities(
                python_launcher,
                has_qgis_process=(self.qgis is not None),
            ),
        )


@contextmanager
def open_conversation(
    config: AppConfig,
    session_id: str,
    *,
    api_key: str | None = None,
    on_event: EventCallback | None = None,
    extra_tools: list[Tool] | None = None,
    workspace_context: WorkspaceContext | None = None,
    allowed_write_roots: tuple[Path, ...] = (),
    protected_paths: tuple[Path, ...] = (),
    cancel_event: Event | None = None,
) -> Iterator[Conversation]:
    resolved_key = (api_key or os.environ.get(config.api_key_env, "")).strip()
    if not resolved_key:
        raise ValueError(f"未提供模型密钥，请显式传入 api_key 或设置环境变量 {config.api_key_env}。")
    active_cancel = cancel_event if cancel_event is not None else Event()
    store = SessionStore(config.session_root, session_id)
    config.session_root.mkdir(parents=True, exist_ok=True)
    output_dir = config.output_root / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    messages = store.read_record()
    qgis = QGISClient(config.qgis.process_launcher, cancel_event=active_cancel) if config.qgis is not None else None
    catalog = load_catalog(qgis) if qgis is not None else None
    with (
        OpenAI(
            api_key=resolved_key,
            base_url=config.model.base_url,
            max_retries=config.max_retries,
            http_client=DefaultHttpxClient(trust_env=config.trust_env),
        ) as client,
        SqliteCheckpointer.from_conn_string(str(config.session_root / "checkpoints.sqlite")) as saver,
    ):
        factory = AgentFactory(config, partial(chat, client, config.model), make_token_counter(config.model), qgis, catalog)
        memory = MemoryStore(config.memory) if config.memory is not None else None
        turn = MemoryTurn() if memory is not None else None
        agent = factory.create(
            store,
            messages,
            output_dir,
            saver,
            render_prompt(
                "system.j2",
                project=config.project,
                output_dir=output_dir,
                supports_images=config.model.supports_images,
                supports_memory=memory is not None,
                skills=skill_index(),
            ),
            extra_tools=extra_tools,
            memory=memory,
            turn=turn,
            allowed_write_roots=allowed_write_roots,
            protected_paths=protected_paths,
            on_event=on_event,
            cancel_event=active_cancel,
            workspace_context=workspace_context,
        )
        yield Conversation(
            agent,
            messages,
            output_dir,
            cancel_event=active_cancel,
            workspace_context=workspace_context,
        )
