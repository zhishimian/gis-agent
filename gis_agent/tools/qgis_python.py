import json
import os
import subprocess
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4

from gis_agent.persistence.evidence import file_digest
from gis_agent.tools.base import Tool


def run_python_script(
    launcher: Path,
    log_dir: Path,
    script_path: str,
    arguments: list[str] | None = None,
    *, font_files: tuple[Path, ...] = (),
) -> dict[str, Any]:
    script = Path(script_path).expanduser().resolve()
    if not script.is_file() or script.suffix.lower() != ".py":
        return {"ok": False, "error": f"Python 脚本不存在或扩展名不是 .py：{script}"}
    if not launcher.is_file():
        return {"ok": False, "error": f"QGIS Python 启动器不存在：{launcher}"}
    if arguments is not None and (not isinstance(arguments, list) or any(not isinstance(item, str) for item in arguments)):
        return {"ok": False, "error": "arguments 必须是字符串列表。"}

    log_dir = (log_dir / uuid4().hex).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    snapshot = log_dir / "script.py"
    snapshot.write_bytes(script.read_bytes())
    script_hash = file_digest(snapshot)
    stdout_path = log_dir / "stdout.txt"
    stderr_path = log_dir / "stderr.txt"
    result_path = log_dir / "result.json"
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        result = subprocess.run(
            [str(launcher), "-B", str(script), *(arguments or [])],
            cwd=script.parent,
            env=os.environ | {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "QT_QPA_PLATFORM": "offscreen",
                "GIS_AGENT_RESULT_PATH": str(result_path),
                **({"GIS_AGENT_FONT_FILES": ";".join(str(path) for path in font_files)} if font_files else {}),
            },
            stdout=stdout,
            stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    changed = not script.is_file() or file_digest(script) != script_hash
    structured = {}
    if result_path.is_file():
        try:
            structured = {"result": json.loads(result_path.read_text(encoding="utf-8"))}
        except json.JSONDecodeError as error:
            structured = {"error": f"结构化结果不是有效JSON：{error}"}
        structured.update(result_path=str(result_path), result_sha256=file_digest(result_path))
    return {
        "ok": result.returncode == 0 and not changed and "error" not in structured
              and not (isinstance(structured.get("result"), dict) and structured["result"].get("ok") is False),
        "returncode": result.returncode,
        "stdout": stdout_path.read_text(encoding="utf-8", errors="replace")[-2000:] if result.returncode or "result" not in structured else "",
        "stderr": stderr_path.read_text(encoding="utf-8", errors="replace")[-3000:],
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "script_snapshot": str(snapshot), "script_sha256": script_hash, "script_changed": changed,
        "stdout_sha256": file_digest(stdout_path), "stderr_sha256": file_digest(stderr_path),
        **structured,
    }


def inspect_data(
    launcher: Path, log_dir: Path, source: str | None = None, sources: list[str] | None = None,
) -> dict[str, Any]:
    if (source is None) == (sources is None) or (sources is not None and (
        not sources or any(not isinstance(item, str) for item in sources)
    )):
        return {"ok": False, "error": "请提供 source，或非空 sources 列表，二者选一。"}
    script = Path(__file__).resolve().parents[1] / "integrations" / "qgis" / "inspect_data.py"
    result = run_python_script(launcher, log_dir, str(script), [source] if source is not None else ["--batch", *sources])
    if result["ok"]:
        result["data"] = result.pop("result") if "result" in result else json.loads(Path(result["stdout_path"]).read_text(encoding="utf-8"))
        del result["stdout"]
    return result


def run_data_check(launcher: Path, log_dir: Path, mode: str, **parameters: Any) -> dict[str, Any]:
    script = Path(__file__).resolve().parents[1] / "integrations" / "qgis" / "check_data.py"
    return run_python_script(launcher, log_dir, str(script), [json.dumps({"mode": mode, **parameters}, ensure_ascii=False)])


def make_qgis_python_tools(launcher: Path, log_dir: Path, font_files: tuple[Path, ...] = ()) -> list[Tool]:
    return [
        Tool(
            name="inspect_data",
            description=(
                "读取 GIS 数据元信息。矢量返回字段、三条属性样例、数量、几何类型、"
                "CRS 和范围；栅格返回尺寸、像元大小、波段、NoData、CRS 和范围。"
                "多图层容器先返回 layers，再用选定图层的 source 调用本工具。"
                "不进行完整几何校验或全量数值统计。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "绝对数据路径或上一轮返回的图层 source。"},
                    "sources": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                                "description": "批量读取指定数据，共用一次QGIS初始化。与source二选一。"},
                },
                "oneOf": [{"required": ["source"]}, {"required": ["sources"]}],
                "additionalProperties": False,
            },
            function=partial(inspect_data, launcher, log_dir),
        ),
        Tool(
            name="run_python_script",
            description=(
                "执行已保存的 .py 脚本，使用独立 QGIS Python 进程。"
                "需要 PyQGIS 或 Processing 时，由脚本显式初始化。"
                "工作目录为脚本所在目录，不共享上次执行的变量。"
                "等待脚本退出，返回退出码、日志尾部和完整日志路径。"
                "首次用 write_file 保存，修改优先用 edit_file。arguments 可传入脚本参数。"
                "可向环境变量 GIS_AGENT_RESULT_PATH 指定的文件写JSON，返回result；stdout只作日志，不要求末行格式。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "script_path": {"type": "string"},
                    "arguments": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["script_path"],
                "additionalProperties": False,
            },
            function=partial(run_python_script, launcher, log_dir, font_files=font_files),
        ),
        Tool(
            "summarize_fields", "测量矢量字段的空值、唯一值、数值范围与总量，并返回有限样本。可检查稳定键重复与几何有效性。只提供事实，不决定业务公式。",
            {"type": "object", "properties": {"source": {"type": "string"},
             "fields": {"type": "array", "items": {"type": "string"}}, "key": {"type": "string"},
             "check_geometry": {"type": "boolean"}}, "required": ["source", "fields"], "additionalProperties": False},
            partial(run_data_check, launcher, log_dir, "fields"),
        ),
        Tool(
            "check_spatial_relation", "按外键定位参照对象，统计缺失键、空几何和不满足指定空间关系的记录，返回有限反例。两层须有相同有效CRS，参照键须唯一；不会自动选择归属规则。",
            {"type": "object", "properties": {"source": {"type": "string"}, "reference": {"type": "string"},
             "foreign_key": {"type": "string"}, "reference_key": {"type": "string"},
             "relation": {"type": "string", "enum": ["intersects", "within", "contains", "touches"]}},
             "required": ["source", "reference", "foreign_key", "reference_key"], "additionalProperties": False},
            partial(run_data_check, launcher, log_dir, "relations"),
        ),
    ]
