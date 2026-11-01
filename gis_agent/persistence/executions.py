import json
import hashlib
import logging
import re
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gis_agent.persistence.evidence import tool_result
from gis_agent.persistence.json import json_text, write_json
from gis_agent.persistence.sessions import SessionStore


QUIET_TOOLS = {
    "execution_history", "read_session_messages", "read_file", "search_text",
    "list_files", "read_image", "search_qgis_tools", "update_plan", "finish_task",
}
logger = logging.getLogger(__name__)


def digest(value: Any) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def record_history(operation: Callable, *arguments: Any) -> None:
    try:
        operation(*arguments)
    except Exception:
        # 回执是辅助记录，不能替代 Session 的执行保护。
        logger.warning("历史回执写入失败：%s", operation.__name__, exc_info=True)


def execution_id(index: int, slot: int) -> str:
    return f"e{index:06d}_{slot:02d}"


def result_status(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("ok") is False:
            return "failed"
        if value.get("ok") is True:
            return "succeeded"
    return "returned"


def result_links(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in (
        "algorithm_id", "outputs", "path", "script_snapshot", "script_sha256",
        "script_changed", "stdout_path", "stdout_sha256", "stderr_path",
        "stderr_sha256", "result_path", "result_sha256",
    ) if key in value}


@dataclass
class ExecutionHistory:
    store: SessionStore

    @property
    def record_dir(self) -> Path:
        return self.store.root / f"{self.store.session_id}.assets" / "executions"

    def record_path(self, identifier: str) -> Path:
        if not re.fullmatch(r"e\d{6,}_\d{2,}", identifier):
            raise ValueError("执行 ID 无效。")
        path = (self.record_dir / f"{identifier}.json").resolve()
        if not path.is_relative_to(self.record_dir):
            raise ValueError("执行回执超出当前 Session 目录。")
        return path

    def begin(self, index: int, slot: int, call: dict, metadata: dict | None = None) -> None:
        identifier = execution_id(index, slot)
        path = self.record_path(identifier)
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8"))["call_sha256"] != digest(call):
                raise ValueError("执行 ID 的原调用已变化。")
            return
        write_json(path, {
            "version": 1, "execution_id": identifier, "origin": "agent_tool",
            "call_sha256": digest(call), "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None, "elapsed_ms": None, "state": "started",
            "metadata": metadata,
        })

    def complete(self, identifier: str, message: dict, message_index: int, elapsed_ms: float) -> None:
        path = self.record_path(identifier)
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["state"] != "started":
            if record.get("message_sha256") != digest(message):
                raise ValueError("已完成回执与本次结果冲突。")
            return
        value = tool_result(self.store, message)
        record.update(state=result_status(value), finished_at=datetime.now(timezone.utc).isoformat(),
                      elapsed_ms=elapsed_ms, message_index=message_index, message_sha256=digest(message))
        if len(json_text(message)) <= 16000:
            record["completion_message"] = message
        write_json(path, record)

    def raised(self, identifier: str, error: Exception, elapsed_ms: float) -> None:
        path = self.record_path(identifier)
        record = json.loads(path.read_text(encoding="utf-8"))
        trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        trace_path = path.with_suffix(".traceback.txt")
        trace_path.write_text(trace, encoding="utf-8")
        record.update(state="raised", finished_at=datetime.now(timezone.utc).isoformat(),
                      elapsed_ms=elapsed_ms, error=f"{type(error).__name__}: {error}"[:3000],
                      traceback_path=str(trace_path), traceback_sha256=hashlib.sha256(trace.encode("utf-8")).hexdigest())
        write_json(path, record)

    def merge_record(self, row: dict, call: dict, message: dict | None) -> None:
        path = self.record_path(row["execution_id"])
        if not path.exists():
            return
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if (record["version"] != 1 or record["execution_id"] != row["execution_id"]
                    or record["call_sha256"] != digest(call)):
                raise ValueError("回执的原调用来源不匹配。")
            if message is not None and record.get("message_sha256") is not None:
                if (record["message_sha256"] != digest(message)
                        or record["message_index"] != row["sources"]["tool_message_index"]):
                    raise ValueError("回执与 Session 工具结果不匹配。")
            row.update({key: record[key] for key in ("started_at", "finished_at", "elapsed_ms")})
            row["recorded_state"] = record["state"]
            if message is None:
                if record["state"] == "raised":
                    row.update(status="raised", error=record["error"])
                    row["links"].update({key: record[key] for key in ("traceback_path", "traceback_sha256")})
                elif record.get("completion_message"):
                    completion = record["completion_message"]
                    if (digest(completion) != record["message_sha256"]
                            or completion.get("tool_call_id") != call.get("id")
                            or completion.get("tool_name") != row["tool"]):
                        raise ValueError("孤立完成消息的来源不匹配。")
                    value = tool_result(self.store, completion)
                    row.update(result=value, links=result_links(value), pairing="orphan")
        except (OSError, ValueError, KeyError, TypeError) as error:
            row.update(status="unknown", integrity="conflict", error=str(error))

    def rows(self) -> list[dict[str, Any]]:
        if not self.store.path.exists():
            return []
        messages = json.loads(self.store.path.read_text(encoding="utf-8"))
        if not isinstance(messages, list) or any(not isinstance(item, dict) for item in messages):
            raise ValueError("Session 顶层必须是消息对象列表。")
        rows = []
        for index, message in enumerate(messages):
            if message.get("role") != "assistant":
                continue
            calls = message.get("tool_calls", [])
            results: dict[str, list[tuple[int, dict]]] = {}
            end = index + 1
            while end < len(messages) and messages[end].get("role") == "tool":
                item = messages[end]
                results.setdefault(item.get("tool_call_id"), []).append((end, item))
                end += 1
            ids = [call.get("id") for call in calls]
            for slot, call in enumerate(calls):
                function = call.get("function", {})
                raw = function.get("arguments", "")
                row = {
                    "execution_id": execution_id(index, slot), "tool": function.get("name"),
                    "arguments_raw": raw, "arguments": None, "result": None,
                    "status": "unknown", "integrity": "ok", "pairing": "unpaired",
                    "started_at": None, "finished_at": None, "elapsed_ms": None,
                    "sources": {"assistant_index": index, "call_slot": slot, "tool_call_id": call.get("id")},
                    "links": {}, "dependency_completeness": "unknown",
                }
                try:
                    row["arguments"] = json.loads(raw)
                except (json.JSONDecodeError, TypeError) as error:
                    row["argument_error"] = str(error)
                matched = results.get(call.get("id"), [])
                if ids.count(call.get("id")) != 1 or len(matched) > 1:
                    row.update(integrity="conflict", error="同一批次的调用或结果 ID 重复。")
                elif matched:
                    tool_index, item = matched[0]
                    row["sources"]["tool_message_index"] = tool_index
                    row["pairing"] = "paired"
                    try:
                        if (item.get("tool_name", row["tool"]) != row["tool"]
                                or item.get("execution_id", row["execution_id"]) != row["execution_id"]):
                            raise ValueError("工具结果的执行来源不匹配。")
                        value = tool_result(self.store, item)
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        row.update(integrity="corrupt", error=str(error))
                    else:
                        row.update(result=value, status=result_status(value), links=result_links(value))
                        if isinstance(value, dict):
                            row["error"] = str(value.get("error") or value.get("stderr") or "")[-3000:]
                        if "argument_error" in row:
                            row["status"] = "rejected"
                if row["integrity"] == "ok":
                    try:
                        self.merge_record(row, call, matched[0][1] if matched else None)
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        row.update(status="unknown", integrity="conflict", error=str(error))
                rows.append(row)
        previous = {}
        for row in rows:
            arguments = row["arguments"]
            if row["tool"] == "run_python_script" and isinstance(arguments, dict):
                script = arguments.get("script_path")
                if script:
                    row["script"] = script
                    row["previous_same_script"] = previous.get(script)
                    previous[script] = row["execution_id"]
        return rows

    def query(
        self, execution_id: str | None = None, query: str | None = None,
        tool: str | None = None, status: str | None = None,
        offset: int = 0, limit: int = 5, section: str = "summary",
        cursor: int = 0, max_characters: int = 4000,
    ) -> dict[str, Any]:
        if offset < 0 or cursor < 0 or not 1 <= limit <= 20 or not 512 <= max_characters <= 8000:
            return {"ok": False, "error": "offset/cursor 必须非负，limit 为1～20，max_characters 为512～8000。"}
        if section not in {"summary", "arguments", "result", "error", "links", "detail"}:
            return {"ok": False, "error": "不支持的历史读取 section。"}
        try:
            rows = self.rows()
        except (OSError, ValueError, KeyError, TypeError) as error:
            return {"ok": False, "error": str(error)}
        selected = []
        for row in reversed(rows):
            if execution_id is not None and row["execution_id"] != execution_id:
                continue
            if tool is not None and row["tool"] != tool:
                continue
            if status is not None and row["status"] != status:
                continue
            if execution_id is None and tool is None and row["tool"] in QUIET_TOOLS:
                continue
            if query:
                arguments = row["arguments"] if isinstance(row["arguments"], dict) else {}
                text = json_text([row["execution_id"], row["tool"], row.get("script"),
                                  {key: value for key, value in arguments.items() if key not in {"content", "old_text", "new_text"}},
                                  row["links"], row.get("error", "")]).casefold()
                if not all(word in text for word in query.casefold().split()):
                    continue
            selected.append(row)
        if section != "summary":
            if offset >= len(selected):
                return {"ok": False, "error": "未找到对应执行。", "matches": len(selected)}
            row = selected[offset]
            value = row if section == "detail" else row.get(section)
            if section == "arguments" and value is None:
                value = row["arguments_raw"]
            text = json_text(value)
            end = min(cursor + max_characters, len(text))
            return {"ok": True, "execution_id": row["execution_id"], "status": row["status"],
                    "integrity": row["integrity"], "matches": len(selected), "section": section,
                    "text": text[cursor:end], "total_characters": len(text),
                    "next_cursor": end if end < len(text) else None}
        items = []
        for row in selected[offset:offset + limit]:
            item = {key: row[key] for key in (
                "execution_id", "tool", "status", "integrity", "pairing", "sources",
                "started_at", "finished_at", "elapsed_ms", "dependency_completeness",
            )}
            if row.get("script"):
                item["script"] = row["script"]
                item["previous_same_script"] = row["previous_same_script"]
            if row.get("error"):
                item["error"] = row["error"][-400:]
            if items and len(json_text([*items, item])) > max_characters:
                break
            items.append(item)
        end = offset + len(items)
        return {"ok": True, "matches": len(selected), "items": items,
                "next_offset": end if end < len(selected) else None}
