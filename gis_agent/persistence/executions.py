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

from gis_agent.persistence.evidence import file_digest, tool_result
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
    output_dir: Path | None = None

    @property
    def output_root(self) -> Path:
        return (self.output_dir or self.store.root.parent / "outputs" / self.store.session_id).resolve()

    def read_result(self, message: dict) -> Any:
        if "asset" in message:
            path = self.store.asset_path(message["asset"])
            if not path.is_relative_to(self.store.root / f"{self.store.session_id}.assets" / "tool_results"):
                raise ValueError("工具资产经过链接跳出了当前 Session。")
        return tool_result(self.store, message)

    def facts(self, value: Any, arguments: Any, metadata: dict | None = None, *, capture_request: bool = False) -> dict:
        facts: dict[str, Any] = {"dependency_completeness": "unknown", "inputs": [], "outputs": []}
        if not isinstance(value, dict):
            return facts
        arguments = arguments if isinstance(arguments, dict) else {}
        if metadata:
            facts["algorithm_id"] = metadata["algorithm_id"]
            facts["definition_sha256"] = metadata["definition_sha256"]
            facts["omitted_parameters"] = sorted(metadata["parameters"].keys() - arguments.keys())
            for name, definition in metadata["parameters"].items():
                if not definition["destination"] and name in arguments and definition["type"] in {
                    "source", "vector", "raster", "maplayer", "multilayer", "file",
                }:
                    facts["inputs"].append({"parameter": name, "source": arguments[name], "identity_strength": "reference_only"})
        outputs = value.get("outputs")
        if not isinstance(outputs, dict) and isinstance(value.get("result"), dict):
            outputs = value["result"].get("outputs", value["result"])
        if isinstance(outputs, dict):
            for name, source in outputs.items():
                if not isinstance(source, str) or not Path(source.split("|", 1)[0]).is_absolute():
                    continue
                item = {"parameter": name, "source": source, "identity_strength": "reported_reference"}
                path = Path(source.split("|", 1)[0]).resolve()
                if path.is_relative_to(self.output_root):
                    item["observed_at"] = datetime.now(timezone.utc).isoformat()
                    item["exists"] = path.is_file()
                    if item["exists"]:
                        stat = path.stat()
                        item.update(size=stat.st_size, mtime_ns=stat.st_mtime_ns, identity_strength="stat_only")
                facts["outputs"].append(item)
        if value.get("script_snapshot"):
            facts["script"] = {"path": arguments.get("script_path"), "snapshot": value["script_snapshot"],
                               "sha256": value.get("script_sha256"), "execution_mode": "original_path",
                               "script_changed": value.get("script_changed"), "actual_code_identity": "not_proven"}
            request = Path(value["script_snapshot"]).parent / "request.json"
            if request.resolve().is_relative_to(self.output_root / "python_logs") and request.is_file():
                facts["request"] = {"path": str(request), "sha256": file_digest(request) if capture_request else None,
                                    "identity_strength": "captured_at_completion" if capture_request else "unverified_reference"}
        return facts

    def read_resource(self, row: dict, section: str, cursor: int = 0, limit: int = 4000) -> dict:
        resources = {
            "script": ("script_snapshot", "script_sha256", "script.py"),
            "stdout": ("stdout_path", "stdout_sha256", "stdout.txt"),
            "stderr": ("stderr_path", "stderr_sha256", "stderr.txt"),
        }
        if section == "request":
            reference = row.get("facts", {}).get("request", {})
            location, expected, filename = reference.get("path"), reference.get("sha256"), "request.json"
        elif section == "traceback":
            location, expected = row["links"].get("traceback_path"), row["links"].get("traceback_sha256")
            filename = f"{row['execution_id']}.traceback.txt"
        else:
            path_key, hash_key, filename = resources[section]
            location, expected = row["links"].get(path_key), row["links"].get(hash_key)
        if not location:
            return {"ok": False, "error": "该执行没有对应资源引用。"}
        path = Path(location).resolve()
        allowed = self.record_dir if section == "traceback" else self.output_root / "python_logs"
        if not path.is_relative_to(allowed) or path.name != filename:
            return {"ok": False, "error": "资源超出当前 Session 的 Python 日志范围。"}
        try:
            data = path.read_bytes()
            if expected is None or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("资源缺少内容指纹或校验失败。")
            text = data.decode("utf-8")
        except (OSError, UnicodeError, ValueError) as error:
            return {"ok": False, "error": str(error)}
        end = min(cursor + limit, len(text))
        return {"ok": True, "path": str(path), "sha256": expected, "text": text[cursor:end],
                "total_characters": len(text), "next_cursor": end if end < len(text) else None}

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

    def complete(self, identifier: str, message: dict, message_index: int, elapsed_ms: float,
                 arguments: dict | None = None) -> None:
        path = self.record_path(identifier)
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["state"] != "started":
            if record.get("message_sha256") != digest(message):
                raise ValueError("已完成回执与本次结果冲突。")
            return
        value = self.read_result(message)
        record.update(state=result_status(value), finished_at=datetime.now(timezone.utc).isoformat(),
                      elapsed_ms=elapsed_ms, message_index=message_index, message_sha256=digest(message))
        record["facts"] = self.facts(value, arguments, record.get("metadata"), capture_request=True)
        if len(json_text(message)) <= 16000:
            record["completion_message"] = message
        write_json(path, record)

    def raised(self, identifier: str, error: Exception, elapsed_ms: float) -> None:
        path = self.record_path(identifier)
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["state"] != "started":
            raise ValueError("已完成回执不能改写成异常。")
        trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        trace_path = path.with_suffix(".traceback.txt").resolve()
        if not trace_path.is_relative_to(self.record_dir):
            raise ValueError("异常日志超出当前 Session 目录。")
        trace_path.write_text(trace, encoding="utf-8")
        record.update(state="raised", finished_at=datetime.now(timezone.utc).isoformat(),
                      elapsed_ms=elapsed_ms, error=f"{type(error).__name__}: {error}"[:3000],
                      traceback_path=str(trace_path), traceback_sha256=hashlib.sha256(trace.encode("utf-8")).hexdigest())
        write_json(path, record)

    def merge_record(self, row: dict, path: Path) -> None:
        try:
            if path.is_symlink():
                raise ValueError("执行回执不能通过文件链接读取。")
            record = json.loads(path.read_text(encoding="utf-8"))
            if (record["version"] != 1 or record["execution_id"] != row["execution_id"]
                    or record["call_sha256"] != row["sources"]["call_sha256"]):
                raise ValueError("回执的原调用来源不匹配。")
            if row["pairing"] == "paired" and record.get("message_sha256") is not None:
                if (record["message_sha256"] != row["sources"]["tool_message_sha256"]
                        or record["message_index"] != row["sources"]["tool_message_index"]):
                    raise ValueError("回执与 Session 工具结果不匹配。")
                if record["state"] != row["status"]:
                    raise ValueError("回执状态与工具结果冲突。")
            row.update({key: record[key] for key in ("started_at", "finished_at", "elapsed_ms")})
            row["recorded_state"] = record["state"]
            if "facts" in record:
                row["facts"] = record["facts"]
            if row["pairing"] != "paired":
                if record["state"] == "raised":
                    row.update(status="raised", error=record["error"])
                    row["links"].update({key: record[key] for key in ("traceback_path", "traceback_sha256")})
                elif record.get("completion_message"):
                    completion = record["completion_message"]
                    if (digest(completion) != record["message_sha256"]
                            or completion.get("tool_call_id") != row["sources"]["tool_call_id"]
                            or completion.get("tool_name") != row["tool"]):
                        raise ValueError("孤立完成消息的来源不匹配。")
                    value = self.read_result(completion)
                    row.update(result=value, links=result_links(value), pairing="orphan")
        except (OSError, ValueError, KeyError, TypeError) as error:
            row.update(status="unknown", integrity="conflict", error=str(error))

    def hydrate(self, row: dict, path: Path | None = None) -> None:
        if row.get('pairing') == 'replay_child':
            return
        if row["integrity"] != "ok":
            return
        try:
            path = path or self.record_path(row["execution_id"])
            if path.exists():
                self.merge_record(row, path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            row.update(status="unknown", integrity="conflict", error=str(error))

    def rows(self, *, read_receipts: bool = True) -> list[dict[str, Any]]:
        if not self.store.path.exists():
            return []
        messages = json.loads(self.store.path.read_text(encoding="utf-8"))
        if not isinstance(messages, list) or any(not isinstance(item, dict) for item in messages):
            raise ValueError("Session 顶层必须是消息对象列表。")
        if self.record_dir.resolve() != self.record_dir:
            raise ValueError("执行回执目录经过链接跳出了当前 Session。")
        records = {path.stem: path for path in self.record_dir.glob("e*.json")} if read_receipts else {}
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
                    "sources": {"assistant_index": index, "call_slot": slot, "tool_call_id": call.get("id"), "call_sha256": digest(call)},
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
                    row["sources"]["tool_message_sha256"] = digest(item)
                    row["pairing"] = "paired"
                    try:
                        if (item.get("tool_name", row["tool"]) != row["tool"]
                                or item.get("execution_id", row["execution_id"]) != row["execution_id"]):
                            raise ValueError("工具结果的执行来源不匹配。")
                        value = self.read_result(item)
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        row.update(integrity="corrupt", error=str(error))
                    else:
                        row.update(result=value, status=result_status(value), links=result_links(value))
                        if isinstance(value, dict):
                            row["error"] = str(value.get("error") or value.get("stderr") or "")[-3000:]
                        if "argument_error" in row:
                            row["status"] = "rejected"
                if row["execution_id"] in records:
                    self.hydrate(row, records[row["execution_id"]])
                elif not read_receipts and row["pairing"] == "unpaired":
                    self.hydrate(row)
                if "facts" not in row:
                    row["facts"] = self.facts(row["result"], row["arguments"])
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
        for path in self.record_dir.glob('r_*_s*.json'):
            try:
                if path.is_symlink():
                    raise ValueError('子回执不能通过链接读取。')
                record = json.loads(path.read_text(encoding='utf-8'))
                if record.get('origin') != 'replay_child' or record.get('execution_id') != path.stem:
                    raise ValueError('子回执来源冲突。')
                call = record['resolved_call']
                value = record.get('result')
                status = {'completed': 'succeeded', 'failed': 'failed'}.get(record['state'], 'unknown')
                integrity = 'ok'
                if status == 'succeeded':
                    from gis_agent.core.replay import validate_outputs
                    if not validate_outputs(record['output_versions']):
                        status, integrity = 'unknown', 'conflict'
                rows.append({'execution_id': path.stem, 'tool': call['tool'],
                             'arguments': call['arguments'], 'arguments_raw': json_text(call['arguments']),
                             'result': value, 'status': status, 'integrity': integrity, 'pairing': 'replay_child',
                             'sources': {'repair_id': record['repair_id'], 'source_execution': record['source_execution']},
                             'links': result_links(value), 'facts': self.facts(value, call['arguments']),
                             'started_at': record.get('started_at'), 'finished_at': record.get('finished_at'),
                             'elapsed_ms': record.get('elapsed_ms'), 'dependency_completeness': 'declared',
                             'error': str((value or {}).get('error') or (value or {}).get('stderr') or '')[-3000:]})
            except (OSError, ValueError, KeyError, TypeError) as error:
                rows.append({'execution_id': path.stem, 'tool': 'unknown', 'arguments': None,
                             'arguments_raw': '', 'result': None, 'status': 'unknown', 'integrity': 'corrupt',
                             'pairing': 'replay_child', 'sources': {}, 'links': {}, 'facts': {},
                             'started_at': None, 'finished_at': None, 'elapsed_ms': None,
                             'dependency_completeness': 'unknown', 'error': str(error)})
        return rows

    def query(
        self, execution_id: str | None = None, query: str | None = None,
        tool: str | None = None, status: str | None = None,
        offset: int = 0, limit: int = 5, section: str = "summary",
        cursor: int = 0, max_characters: int = 4000,
    ) -> dict[str, Any]:
        if offset < 0 or cursor < 0 or not 1 <= limit <= 20 or not 512 <= max_characters <= 8000:
            return {"ok": False, "error": "offset/cursor 必须非负，limit 为1～20，max_characters 为512～8000。"}
        resources = {"script", "stdout", "stderr", "request", "traceback"}
        if section not in {"summary", "arguments", "result", "error", "links", "detail", *resources}:
            return {"ok": False, "error": "不支持的历史读取 section。"}
        try:
            rows = self.rows(read_receipts=status is not None)
        except (OSError, ValueError, KeyError, TypeError) as error:
            return {"ok": False, "error": str(error)}
        selected = []
        for row in reversed(rows):
            if row["tool"] == "execution_history" and row["pairing"] == "unpaired":
                continue
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
            if status is None:
                self.hydrate(row)
            if section in resources:
                if row["integrity"] != "ok":
                    return {"ok": False, "error": "执行来源不完整，不能读取关联资源。", "integrity": row["integrity"]}
                return {**self.read_resource(row, section, cursor, max_characters), "execution_id": row["execution_id"]}
            if section == "detail":
                value = {key: row.get(key) for key in ("execution_id", "tool", "status", "arguments", "error")}
                if row["integrity"] == "ok":
                    if row["links"].get("script_snapshot"):
                        value["script"] = self.read_resource(row, "script", limit=2000)
                    if row["links"].get("stderr_path"):
                        value["stderr"] = self.read_resource(row, "stderr", limit=1500)
                value.update(result=row["result"], links=row["links"], facts=row["facts"], sources=row["sources"])
            else:
                value = row.get(section)
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
            if status is None:
                self.hydrate(row)
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
        return {"ok": True, "matches": len(selected), "matches_scope": "verified_records" if status is not None else "session_candidates", "items": items,
                "next_offset": end if end < len(selected) else None}
