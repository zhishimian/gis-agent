import json
import time
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
        # Windows 杀毒或索引线程可能瞬时占用目标句柄，做有界退避重试
        for delay in (0.02, 0.05, 0.1, 0.2, 0.4, 0.0):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if delay == 0.0:
                    raise
                time.sleep(delay)
    finally:
        temporary.unlink(missing_ok=True)


def text_preview(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n……内容已缩略，请读取原始记录……\n"
    size = max(0, (limit - len(marker)) // 2)
    return text[:size] + marker + (text[-size:] if size else "")


def truncate_log(text: str, limit: int = 3500, head_lines: int = 25, tail_lines: int = 45) -> str:
    if len(text) <= limit:
        return text
    lines = text.splitlines(keepends=True)
    if len(lines) > head_lines + tail_lines:
        omitted = len(lines) - head_lines - tail_lines
        candidate = (
            "".join(lines[:head_lines])
            + f"\n……中间省略 {omitted} 行，完整输出见日志文件……\n"
            + "".join(lines[-tail_lines:])
        )
        if len(candidate) <= limit:
            return candidate
        text = candidate
    return text_preview(text, limit)
