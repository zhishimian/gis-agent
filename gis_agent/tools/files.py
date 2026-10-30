from pathlib import Path
import hashlib
from difflib import unified_diff
from typing import Any

from gis_agent.tools.base import Tool


def list_files(path: str, start: int = 0, limit: int = 100) -> dict[str, Any]:
    directory = Path(path).expanduser().resolve()
    if not directory.is_dir():
        return {"ok": False, "error": f"目录不存在：{directory}"}
    if start < 0 or not 1 <= limit <= 500:
        return {"ok": False, "error": "start 必须非负，limit 必须在 1 到 500 之间。"}
    entries = sorted(directory.iterdir())
    return {
        "ok": True, "path": str(directory), "total": len(entries),
        "entries": [
            {"name": item.name, "path": str(item), "is_directory": item.is_dir()}
            for item in entries[start:start + limit]
        ],
        "next_start": start + limit if start + limit < len(entries) else None,
    }


def read_file(
    path: str,
    start: int = 0,
    limit: int = 6000,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        return {"ok": False, "error": f"文件不存在：{target}"}
    if start < 0 or not 1 <= limit <= 20000:
        return {"ok": False, "error": "start 必须非负，limit 必须在 1 到 20000 之间。"}

    data = target.read_bytes()
    try:
        text = data.decode(encoding)
    except (UnicodeError, LookupError) as error:
        return {"ok": False, "error": f"文本解码失败，请核对encoding；二进制GIS数据使用inspect_data：{error}"}
    end = min(start + limit, len(text))
    return {
        "ok": True,
        "path": str(target),
        "total_characters": len(text),
        "sha256": hashlib.sha256(data).hexdigest(),
        "content": text[start:end],
        "next_start": end if end < len(text) else None,
    }


def write_file(
    path: str,
    content: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if target.exists() and (not overwrite or not target.is_file()):
        return {"ok": False, "error": f"目标已存在，未写入：{target}"}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target), "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def edit_file(path: str, old_text: str, new_text: str, expected_sha256: str | None = None) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        return {"ok": False, "error": f"文件不存在：{target}"}
    data = target.read_bytes()
    previous = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and previous != expected_sha256:
        return {"ok": False, "error": "文件版本已经变化，请重新读取待修改片段。", "sha256": previous}
    try:
        text = data.decode("utf-8")
    except UnicodeError as error:
        return {"ok": False, "error": f"edit_file只修改UTF-8文本，请先核对文件编码：{error}"}
    if "\r\n" in text:
        old_text = old_text.replace("\r\n", "\n").replace("\n", "\r\n")
        new_text = new_text.replace("\r\n", "\n").replace("\n", "\r\n")
    matches = text.count(old_text) if old_text else 0
    if matches != 1:
        return {"ok": False, "error": "old_text 必须是非空且恰好匹配一次的原文，请搜索或补充上下文。", "matches": matches}
    updated = text.replace(old_text, new_text, 1)
    target.write_bytes(updated.encode("utf-8"))
    diff = "\n".join(unified_diff(text.splitlines(), updated.splitlines(), n=2, lineterm=""))
    return {"ok": True, "path": str(target), "previous_sha256": previous,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "diff": diff[:3000],
            "diff_truncated": len(diff) > 3000}


def search_text(path: str, query: str, limit: int = 20) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        return {"ok": False, "error": f"文本文件不存在：{target}"}
    if not query or not 1 <= limit <= 100:
        return {"ok": False, "error": "query 不能为空，limit 必须在 1 到 100 之间。"}
    data = target.read_bytes()
    try:
        lines = data.decode("utf-8").splitlines(keepends=True)
    except UnicodeError as error:
        return {"ok": False, "error": f"search_text只读取UTF-8文本，请使用read_file指定encoding：{error}"}
    matches = [i for i, line in enumerate(lines) if query in line]
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    return {"ok": True, "path": str(target), "matches": len(matches),
            "sha256": hashlib.sha256(data).hexdigest(),
            "results": [{"line": i + 1, "start": starts[max(0, i - 1)], "text": lines[i].rstrip("\r\n")[:1000],
                         "context": "".join(lines[max(0, i - 1):i + 2])[:2000]} for i in matches[:limit]]}


file_tools = [
    Tool(
        name="list_files",
        description="列出目录的直接子项，不递归。",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "start": {"type": "integer", "minimum": 0},
                           "limit": {"type": "integer", "minimum": 1, "maximum": 500}},
            "required": ["path"],
            "additionalProperties": False,
        },
        function=list_files,
    ),
    Tool(
        "edit_file", "精确替换UTF-8文本的一处内容，适合修改脚本和设计参数。old_text 必须唯一；可用读取返回的 expected_sha256 检查版本。返回短差异。",
        {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"},
         "new_text": {"type": "string"}, "expected_sha256": {"type": "string"}},
         "required": ["path", "old_text", "new_text"], "additionalProperties": False}, edit_file,
    ),
    Tool(
        "search_text", "在指定UTF-8文本文件中查找字面量，返回行号、可供read_file继续读取的start、有限上下文和文件哈希。用于定位脚本错误和精确编辑。",
        {"type": "object", "properties": {"path": {"type": "string"}, "query": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["path", "query"], "additionalProperties": False}, search_text,
    ),
    Tool(
        name="read_file",
        description=(
            "分段读取文本文件，不用于二进制数据。start 是从零开始的字符位置；"
            "通过返回的 next_start 继续读取。默认 UTF-8，必要时指定 encoding。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20000},
                "encoding": {"type": "string"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        function=read_file,
    ),
    Tool(
        name="write_file",
        description=(
            "以 UTF-8 写入脚本、报告等文本，自动创建父目录。默认拒绝覆盖；"
            "修改本轮自己的脚本或报告时可显式传 overwrite=true。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "overwrite": {"type": "boolean"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        function=write_file,
    ),
]
