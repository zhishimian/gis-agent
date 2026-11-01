import json
from dataclasses import dataclass
from typing import Any

from gis_agent.persistence.evidence import tool_result
from gis_agent.persistence.json import json_text
from gis_agent.persistence.sessions import SessionStore


QUIET_TOOLS = {
    "execution_history", "read_session_messages", "read_file", "search_text",
    "list_files", "read_image", "search_qgis_tools", "update_plan", "finish_task",
}


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
                        value = tool_result(self.store, item)
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        row.update(integrity="corrupt", error=str(error))
                    else:
                        row.update(result=value, status=result_status(value), links=result_links(value))
                        if isinstance(value, dict):
                            row["error"] = str(value.get("error") or value.get("stderr") or "")[-3000:]
                        if "argument_error" in row:
                            row["status"] = "rejected"
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
