import hashlib
import json
from pathlib import Path
from typing import Any

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
