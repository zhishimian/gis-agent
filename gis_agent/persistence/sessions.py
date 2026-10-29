import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from gis_agent.persistence.json import json_text, text_preview, write_json


CONTROL_TOOLS = {"update_plan", "finish_task"}


def message_units(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
    units = []
    index = 0
    while index < len(messages):
        start = index
        message = messages[index]
        if message["role"] == "tool":
            raise ValueError(f"消息 {index} 是没有对应调用的工具结果。")
        calls = message.get("tool_calls", [])
        pending = {call["id"] for call in calls}
        if len(pending) != len(calls):
            raise ValueError(f"消息 {index} 的调用 ID 重复。")
        index += 1
        while pending:
            if index == len(messages) or messages[index]["role"] != "tool":
                raise ValueError(f"消息 {start} 的工具批次未完成，请先检查已有产物。")
            call_id = messages[index]["tool_call_id"]
            if call_id not in pending:
                raise ValueError(f"消息 {index} 的工具结果无法匹配。")
            pending.remove(call_id)
            index += 1
        units.append((start, index))
    return units


def result_view(result: Any, limit: int, source: dict[str, Any]) -> str:
    text = json_text(result)
    if len(text) <= limit:
        return text
    view: dict[str, Any] = {"truncated": True, "source": source}
    if isinstance(result, dict):
        for key in (
            "ok", "returncode", "algorithm_id", "outputs", "path",
            "stdout_path", "stderr_path", "total_characters", "next_start",
            "next_offset", "next_message", "message_index", "session_id",
            "ready", "candidate_id", "review_scope", "status", "issues", "available_evidence",
        ):
            if key in result and len(json_text(result[key])) < limit // 4:
                view[key] = result[key]
    remaining = limit - len(json_text(view)) - 100
    if remaining < 80:
        raise ValueError("结果预览预算不足以容纳来源，请提高 tool_limit。")
    view["preview"] = text_preview(text, remaining // 2)
    return json_text(view)


def delivery_view(result: dict[str, Any]) -> dict[str, Any]:
    if "verification" not in result:
        return result
    verification = result["verification"]
    return {
        **{key: result[key] for key in (
            "ok", "candidate_id", "ready", "review_scope", "request_path", "request_sha256",
            "issues", "resolved_check_ids", "changed_files",
        ) if key in result},
        "verification": {
            **{key: verification[key] for key in ("task_id", "status", "stale", "summary", "map_notes") if key in verification},
            "checks": [
                {key: check[key] for key in ("check_id", "status", "finding", "coverage", "evidence_indices") if key in check}
                for check in verification.get("checks", [])
            ],
        },
    }


@dataclass
class SessionStore:
    root: Path
    session_id: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.session_id):
            raise ValueError("Session ID 只允许 1 到 80 个英文字母、数字、下划线或横线。")
        self.root = self.root.resolve()

    @property
    def path(self) -> Path:
        return self.root / f"{self.session_id}.json"

    @property
    def asset_dir(self) -> Path:
        return self.root / f"{self.session_id}.assets" / "tool_results"

    def asset_path(self, asset: dict[str, Any]) -> Path:
        if asset.get("version") != 1 or asset.get("format") != "json":
            raise ValueError("不支持的结果引用格式。")
        path = (self.root / asset["path"]).resolve()
        if not path.is_relative_to(self.asset_dir.resolve()):
            raise ValueError("工具结果引用超出了当前 Session 目录。")
        return path

    def read_record(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        messages = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(messages, list):
            raise ValueError("Session 顶层必须是消息列表。")
        for message in messages:
            if "asset" in message and not self.asset_path(message["asset"]).is_file():
                raise FileNotFoundError(f"工具结果资产缺失：{message['asset']}")
        return messages

    def load(self) -> list[dict[str, Any]]:
        messages = self.read_record()
        message_units(messages)
        return messages

    def save(self, messages: list[dict[str, Any]]) -> None:
        write_json(self.path, messages)

    @property
    def context_path(self) -> Path:
        return self.root / f"{self.session_id}.context.json"

    def record_model_call(self, entry: dict[str, Any]) -> None:
        path = self.root / f"{self.session_id}.calls.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json_text(entry) + "\n")

    def read_messages(self, start: int, offset: int = 0, limit: int = 4000) -> dict[str, Any]:
        if start < 0 or offset < 0 or not 1 <= limit <= 8000:
            return {"ok": False, "error": "start、offset 必须非负，limit 在 1 到 8000 之间。"}
        messages = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(messages, list):
            raise ValueError('Session must contain a message list.')
        if start >= len(messages):
            return {"ok": False, "error": "消息序号超出范围。", "message_count": len(messages)}
        text = json_text(messages[start])
        end = min(offset + limit, len(text))
        return {
            "ok": True, "session_id": self.session_id, "message_index": start,
            "text": text[offset:end], "total_characters": len(text),
            "next_offset": end if end < len(text) else None,
            "next_message": start + 1 if end == len(text) and start + 1 < len(messages) else None,
        }

    def tool_message(
        self, call_id: str, name: str, result: Any, limit: int,
    ) -> dict[str, Any]:
        text = json_text(result)
        message = {
            "role": "tool", "tool_call_id": call_id,
            "tool_name": name, "content": text,
        }
        if name == "read_image" and isinstance(result, dict) and result.get("ok"):
            message["images"] = [result["image"]]
        if name not in CONTROL_TOOLS and len(text) > limit:
            path = self.asset_dir / f"{uuid4().hex}.json"
            write_json(path, result)
            message["asset"] = {
                "version": 1, "format": "json",
                "path": path.relative_to(self.root).as_posix(), "characters": len(text),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
            message["content"] = result_view(result, limit, {"path": str(path)})
        return message

    def project(self, messages: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        projected = []
        names = {}
        for index, message in enumerate(messages):
            for call in message.get("tool_calls", []):
                names[call["id"]] = call["function"]["name"]
            item = {
                key: message[key]
                for key in ("role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content", "images")
                if key in message
            }
            if message["role"] == "tool":
                name = names.get(message["tool_call_id"], message.get("tool_name"))
                review = name in {"review_delivery", "read_delivery"}
                if review or (name not in CONTROL_TOOLS and len(item["content"]) > limit):
                    source = {"path": str(self.path), "message_index": index}
                    value = json.loads(item['content'])
                    if "asset" in message:
                        path = self.asset_path(message['asset'])
                        source = {"path": str(path)}
                        data = path.read_bytes()
                        expected = message["asset"].get("sha256")
                        if expected is not None and hashlib.sha256(data).hexdigest() != expected:
                            raise ValueError(f"工具结果资产校验失败：{path}")
                        value = json.loads(data)
                    if review:
                        value = {**delivery_view(value), "source": source}
                    item["content"] = result_view(value, limit, source)
            projected.append(item)
        return projected
