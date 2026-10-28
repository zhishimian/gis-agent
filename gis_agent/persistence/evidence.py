import hashlib
import json
from pathlib import Path
from typing import Any

from gis_agent.persistence.json import json_text
from gis_agent.persistence.sessions import SessionStore


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tool_result(store: SessionStore, message: dict[str, Any]) -> Any:
    if "asset" not in message:
        return json.loads(message["content"])
    path = store.asset_path(message["asset"])
    expected = message["asset"].get("sha256")
    if expected is not None and file_digest(path) != expected:
        raise ValueError(f"工具结果资产校验失败：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def tool_evidence(store: SessionStore, messages: list[dict[str, Any]], index: int) -> dict[str, Any]:
    if type(index) is not int or not 0 <= index < len(messages) or messages[index]["role"] != "tool":
        return {"ok": False, "error": "证据需要指向本子会话的工具消息。"}
    message = messages[index]
    call_id = message["tool_call_id"]
    for source in reversed(messages[:index]):
        if source["role"] != "assistant":
            continue
        call = next((item for item in source.get("tool_calls", []) if item["id"] == call_id), None)
        if call is not None:
            break
    else:
        return {"ok": False, "error": "证据缺少对应的工具调用。"}
    name = call["function"]["name"]
    if source.get("executions", {}).get(call_id) != "finished" or message.get("tool_name") != name:
        return {"ok": False, "error": "证据对应的工具调用尚未确认完成。"}
    result = tool_result(store, message)
    files = []
    if name in {"run_python_script", "inspect_data"}:
        if not isinstance(result, dict) or result.get("script_changed") is not False:
            return {"ok": False, "error": "脚本版本未确认稳定，请重新执行检查。"}
        for path_key, hash_key in (
            ("script_snapshot", "script_sha256"), ("stdout_path", "stdout_sha256"), ("stderr_path", "stderr_sha256"),
        ):
            if not result.get(path_key) or not result.get(hash_key):
                return {"ok": False, "error": "检查缺少脚本或日志版本，请重新执行。"}
            files.append({"path": result[path_key], "sha256": result[hash_key]})
    for image in message.get("images", []):
        files.append({"path": image["path"], "sha256": image["sha256"]})
    for item in files:
        path = Path(item["path"])
        if not path.is_file() or file_digest(path) != item["sha256"]:
            return {"ok": False, "error": f"证据文件已缺失或变化：{path}"}
    return {"ok": True, "record": {
        "message_index": index, "tool_call_id": call_id, "tool_name": name,
        "arguments": json.loads(call["function"]["arguments"]), "result": result, "files": files,
    }}


def save_evidence(output_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    data = json_text(record).encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    path = output_dir / "evidence" / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    elif file_digest(path) != digest:
        raise ValueError(f"已有证据快照发生变化：{path}")
    return {
        "message_index": record["message_index"], "tool_call_id": record["tool_call_id"],
        "tool_name": record["tool_name"], "path": str(path.resolve()), "sha256": digest,
    }
