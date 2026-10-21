import json
from pathlib import Path
from typing import Any
from uuid import uuid4


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=True)


def write_json(path: Path, value: Any) -> None:
    text = json_text(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def text_preview(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n……内容已缩略，请读取原始记录……\n"
    size = max(0, (limit - len(marker)) // 2)
    return text[:size] + marker + (text[-size:] if size else "")