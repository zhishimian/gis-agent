from pathlib import Path
from typing import Any

from gis_agent.tools.base import Tool


def list_files(path: str) -> dict[str, Any]:
    return {
        "entries": [
            {"name": item.name, "is_directory": item.is_dir()}
            for item in sorted(Path(path).expanduser().resolve().iterdir())
        ],
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

    text = target.read_text(encoding=encoding)
    end = min(start + limit, len(text))
    return {
        "ok": True,
        "path": str(target),
        "total_characters": len(text),
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
    return {"ok": True, "path": str(target), "bytes": target.stat().st_size}


file_tools = [
    Tool(
        name="list_files",
        description="列出目录的直接子项，不递归。",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        function=list_files,
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