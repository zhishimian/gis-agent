from functools import partial
import json
import os
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

from gis_agent.persistence.evidence import file_digest
from gis_agent.persistence.json import truncate_log
from gis_agent.runtime.inspect_fast import attach_spatial_vitals
from gis_agent.runtime.paths import import_root, package_resource
from gis_agent.runtime.runner import collect_outputs, extract_explicit_paths, run_process
from gis_agent.tools.base import Tool


def run_python_script(
    launcher: Path,
    log_dir: Path,
    script_path: str,
    arguments: list[str] | None = None,
    *,
    font_files: tuple[Path, ...] = (),
    timeout_sec: int = 180,
    watch_roots: tuple[Path, ...] = (),
    protected_paths: tuple[Path, ...] = (),
    cancel_event: Event | None = None,
) -> dict[str, Any]:
    script = Path(script_path).expanduser().resolve()
    if not script.is_file() or script.suffix.lower() != ".py":
        return {"ok": False, "status": "failed", "error": f"Python 脚本不存在或扩展名不是 .py：{script}"}
    if not launcher.is_file():
        return {"ok": False, "status": "failed", "error": f"Python 启动器不存在：{launcher}"}
    if arguments is not None and (not isinstance(arguments, list) or any(not isinstance(item, str) for item in arguments)):
        return {"ok": False, "status": "failed", "error": "arguments 必须是字符串列表。"}
    if not isinstance(timeout_sec, int) or not 5 <= timeout_sec <= 600:
        return {"ok": False, "status": "failed", "error": "timeout_sec 必须在 5 到 600 秒之间；大规模计算请按瓦片/阶段拆分。"}

    run_log_dir = (log_dir / uuid4().hex).resolve()
    run_log_dir.mkdir(parents=True, exist_ok=True)
    snapshot = run_log_dir / "script.py"
    snapshot.write_bytes(script.read_bytes())
    script_hash = file_digest(snapshot)
    stdout_path = run_log_dir / "stdout.txt"
    stderr_path = run_log_dir / "stderr.txt"
    result_path = run_log_dir / "result.json"
    request_path = run_log_dir / "request.json"
    request_path.write_text(
        json.dumps({"script": str(script), "arguments": arguments or []}, ensure_ascii=False),
        encoding="utf-8",
    )
    entry = package_resource("integrations", "qgis", "script_entry.py")
    execution_guide = package_resource("integrations", "qgis", "execution.md")
    effective_watch = watch_roots or (script.parent,)

    sub_env = dict(os.environ)
    # Strip host PROJ/GDAL vars for plain Python interpreters so bundled wheels use their matching proj.db.
    if launcher.suffix.lower() not in {".bat", ".cmd"}:
        for var in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA"):
            sub_env.pop(var, None)

    outcome = run_process(
        [str(launcher), "-B", str(entry)],
        cwd=script.parent,
        env=sub_env | {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "QT_QPA_PLATFORM": "offscreen",
            "MPLBACKEND": "Agg",
            "GIS_AGENT_PROJECT_ROOT": str(import_root()),
            "GIS_AGENT_SCRIPT_REQUEST": str(request_path),
            "GIS_AGENT_RESULT_PATH": str(result_path),
            **({"GIS_AGENT_FONT_FILES": ";".join(str(path) for path in font_files)} if font_files else {}),
        },
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_sec=timeout_sec,
        watch_roots=effective_watch,
        protected_paths=protected_paths,
        cancel_event=cancel_event,
    )

    changed = not script.is_file() or file_digest(script) != script_hash
    structured: dict[str, Any] = {}
    if result_path.is_file():
        try:
            structured = {"result": json.loads(result_path.read_text(encoding="utf-8"))}
        except json.JSONDecodeError as error:
            structured = {"error": f"结构化结果不是有效JSON：{error}"}
        structured.update(result_path=str(result_path), result_sha256=file_digest(result_path))

    explicit = extract_explicit_paths(structured.get("result"))
    outputs = collect_outputs(outcome["before_outputs"], outcome["after_outputs"], explicit)
    outputs = [
        item for item in outputs
        if Path(item["path"]) != script and not Path(item["path"]).is_relative_to(run_log_dir)
    ]
    if outcome["status"] == "succeeded" and outputs:
        attach_spatial_vitals(outputs, launcher)

    stderr_raw = stderr_path.read_text(encoding="utf-8", errors="replace")
    stdout_raw = stdout_path.read_text(encoding="utf-8", errors="replace")
    if outcome["returncode"] and "ModuleNotFoundError: No module named 'processing'" in stderr_raw:
        structured["hint"] = f"Processing初始化入口见：{execution_guide}"
    if outcome["cancelled"]:
        structured["error"] = "执行已被用户主动中止，子进程树已清理。"
    elif outcome["timed_out"]:
        structured["error"] = f"脚本执行超过 {timeout_sec} 秒超时限制，进程树已终止。"
    if outcome["tampered_inputs"]:
        structured["error"] = f"检测到受保护输入文件被修改：{outcome['tampered_inputs']}"

    ok = (
        outcome["status"] == "succeeded"
        and not changed
        and "error" not in structured
        and not (isinstance(structured.get("result"), dict) and structured["result"].get("ok") is False)
    )
    if outcome["cancelled"]:
        status = "cancelled"
    elif outcome["timed_out"]:
        status = "timed_out"
    elif ok:
        status = "succeeded"
    else:
        status = "failed"

    return {
        "ok": ok,
        "status": status,
        "timed_out": outcome["timed_out"],
        "cancelled": outcome["cancelled"],
        "elapsed_ms": outcome["elapsed_ms"],
        "returncode": outcome["returncode"],
        "outputs": outputs,
        "stdout": truncate_log(stdout_raw, 2500) if not ok or "result" not in structured else "",
        "stderr": truncate_log(stderr_raw, 3500),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "script_snapshot": str(snapshot),
        "script_sha256": script_hash,
        "script_changed": changed,
        "stdout_sha256": file_digest(stdout_path),
        "stderr_sha256": file_digest(stderr_path),
        **structured,
    }


def inspect_data(
    launcher: Path,
    log_dir: Path,
    source: str | None = None,
    sources: list[str] | None = None,
    *,
    cancel_event: Event | None = None,
) -> dict[str, Any]:
    if (source is None) == (sources is None) or (
        sources is not None and (not sources or any(not isinstance(item, str) for item in sources))
    ):
        return {"ok": False, "error": "请提供 source，或非空 sources 列表，二者选一。"}
    fast_script = package_resource("runtime", "inspect_fast.py")
    script = fast_script if fast_script.is_file() else package_resource("integrations", "qgis", "inspect_data.py")
    result = run_python_script(
        launcher,
        log_dir,
        str(script),
        [source] if source is not None else ["--batch", *sources],
        cancel_event=cancel_event,
    )
    if result["ok"]:
        result["data"] = (
            result.pop("result")
            if "result" in result
            else json.loads(Path(result["stdout_path"]).read_text(encoding="utf-8"))
        )
        del result["stdout"]
    return result


def run_data_check(
    launcher: Path,
    log_dir: Path,
    mode: str,
    *,
    cancel_event: Event | None = None,
    **parameters: Any,
) -> dict[str, Any]:
    script = package_resource("integrations", "qgis", "check_data.py")
    return run_python_script(
        launcher,
        log_dir,
        str(script),
        [json.dumps({"mode": mode, **parameters}, ensure_ascii=False)],
        cancel_event=cancel_event,
    )


def make_qgis_python_tools(
    launcher: Path,
    log_dir: Path,
    font_files: tuple[Path, ...] = (),
    *,
    watch_roots: tuple[Path, ...] = (),
    protected_paths: tuple[Path, ...] = (),
    cancel_event: Event | None = None,
) -> list[Tool]:
    execution_guide = package_resource("integrations", "qgis", "execution.md")
    return [
        Tool(
            name="inspect_data",
            description=(
                "快速读取 GIS 数据元信息与物理属性。矢量返回字段、样例、数量、几何类型、坐标轴单位、CRS、范围与几何抽检；"
                "栅格返回尺寸、像元大小、波段类型(dtype)、颜色解释(colorinterp)、单位、缩放偏移(scales/offsets)、NoData、CRS、范围与概览抽样区间。"
                "多图层容器先返回 layers，再用选定图层的 source 调用本工具。"
                "批量结果在data.datasets，逐项查看ok；顶层ok只表示批量测量完成。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "绝对数据路径或上一轮返回的图层 source。"},
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "批量读取指定数据。与source二选一。",
                    },
                },
                "oneOf": [{"required": ["source"]}, {"required": ["sources"]}],
                "additionalProperties": False,
            },
            function=partial(inspect_data, launcher, log_dir, cancel_event=cancel_event),
        ),
        Tool(
            name="run_python_script",
            description=(
                "在隔离进程执行已保存的 .py 脚本，支持超时回收与递归产出文件回执。"
                f"Processing/PyQGIS初始化及清理的正确入口见：{execution_guide}。"
                "纯GeoPandas/Shapely/Rasterio/Matplotlib脚本不需要QgsApplication。"
                "工作目录为脚本所在目录，受信任本地执行，请勿修改原始输入数据。"
                "可向环境变量 GIS_AGENT_RESULT_PATH 指定的文件写JSON，返回result与outputs列表；日志头尾截断，完整日志落盘。"
                "首次用 write_file 保存，修改优先用 edit_file。不要用os._exit(0)绕过清理。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "script_path": {"type": "string"},
                    "arguments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "JSON安全传递的字符串列表，还原为脚本sys.argv[1:]。",
                    },
                    "timeout_sec": {
                        "type": "integer",
                        "minimum": 5,
                        "maximum": 600,
                        "description": "最大运行秒数，默认180，范围5～600；耗时更长的大规模计算请先抽样测速并按瓦片/阶段拆分持久化。",
                    },
                },
                "required": ["script_path"],
                "additionalProperties": False,
            },
            function=partial(
                run_python_script,
                launcher,
                log_dir,
                font_files=font_files,
                watch_roots=watch_roots,
                protected_paths=protected_paths,
                cancel_event=cancel_event,
            ),
        ),
        Tool(
            "summarize_fields",
            "统计字段空值、非空唯一值、数值范围与总量，可查稳定键和空/无效几何。samples为开头最多5条，不保证非零；duplicate_rows为超出首次出现的行数。返回位于result；ok仅表示测量成功，业务要求需看实际数值。",
            {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "fields": {"type": "array", "items": {"type": "string"}},
                    "key": {"type": "string"},
                    "check_geometry": {"type": "boolean"},
                },
                "required": ["source", "fields"],
                "additionalProperties": False,
            },
            partial(run_data_check, launcher, log_dir, "fields", cancel_event=cancel_event),
        ),
        Tool(
            "check_spatial_relation",
            "按外键核对source几何 relation reference几何，默认intersects。两层须同一有效CRS，参照键须唯一。result返回missing_key、empty_geometry、violations和有限反例。只检查source现存对象，不发现已丢失的源ID，也不决定最优归属。",
            {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "reference": {"type": "string"},
                    "foreign_key": {"type": "string"},
                    "reference_key": {"type": "string"},
                    "relation": {"type": "string", "enum": ["intersects", "within", "contains", "touches"]},
                },
                "required": ["source", "reference", "foreign_key", "reference_key"],
                "additionalProperties": False,
            },
            partial(run_data_check, launcher, log_dir, "relations", cancel_event=cancel_event),
        ),
    ]
