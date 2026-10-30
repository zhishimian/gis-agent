from functools import partial
import json
import os
from pathlib import Path
from typing import Any

from gis_agent.tools.base import Tool
from gis_agent.tools.qgis_python import run_python_script
from gis_agent.persistence.evidence import file_digest


def render_map(
    launcher: Path, log_dir: Path, font_files: tuple[Path, ...], design_path: str,
    template: str = "choropleth",
) -> dict[str, Any]:
    if template not in {"choropleth", "facilities"}:
        return {"ok": False, "error": "template 需要使用 choropleth 或 facilities；自定义布局可使用 run_python_script。"}
    design = Path(design_path).expanduser().resolve()
    if not design.is_file():
        return {"ok": False, "error": f"设计JSON不存在：{design}"}
    script = Path(__file__).resolve().parents[1] / "assets" / "cartography" / "examples" / f"{template}.py"
    try:
        settings = json.loads(design.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {"ok": False, "error": f"设计JSON格式错误：{error}"}
    if not isinstance(settings, dict) or any(not isinstance(settings.get(key), str) for key in ("brief", "output_dir", "crs")):
        return {"ok": False, "error": "设计JSON需要brief、output_dir和crs字符串字段，请读取Skill执行说明。"}
    if any(not Path(settings[key]).is_absolute() for key in ("brief", "output_dir")):
        return {"ok": False, "error": "brief和output_dir需要使用绝对路径。"}
    manifest_path = Path(settings["output_dir"]).resolve() / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        inputs = {row["path"] for row in manifest["inputs"]}
        expected_fonts = settings.get("font_files", [str(path) for path in font_files])
        if not expected_fonts:
            configured = os.environ.get("GIS_AGENT_FONT_FILES")
            directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            expected_fonts = configured.split(";") if configured else [str(directory / name) for name in ("msyh.ttc", "arial.ttf")]
        expected_fonts = [str(Path(path).expanduser().resolve()) for path in expected_fonts]
        recorded_fonts = [row["path"] for row in manifest["environment"]["fonts"]["files"]]
        paths = [(Path(row["path"]), row["sha256"]) for row in manifest["inputs"]]
        paths += [(manifest_path.parent / row["path"], row["sha256"]) for row in manifest["outputs"]]
        if {str(design), str(script)} <= inputs and (not expected_fonts or expected_fonts == recorded_fonts) and all(
            path.is_file() and file_digest(path) == expected for path, expected in paths
        ):
            return {"ok": True, "reused": True, "result": {
                "ok": True, "manifest": str(manifest_path), "manifest_sha256": file_digest(manifest_path),
                "files": manifest["files"], "maps": manifest["maps"], "layout": manifest["layout"],
                "preview": str(manifest_path.parent / manifest["files"]["preview"]),
                "artifacts": [str(manifest_path.parent / row["path"]) for row in manifest["outputs"]] + [str(manifest_path)],
            }}
    return run_python_script(launcher, log_dir, str(script), [str(design)], font_files=font_files)


def make_cartography_tools(launcher: Path, log_dir: Path, font_files: tuple[Path, ...]) -> list[Tool]:
    return [Tool(
        "render_map", "用已验证的QGIS例程渲染设计JSON。choropleth为分级设色，facilities为面和设施点。返回真实产物、预览、图层顺序和结构化结果。先读取gis-cartography Skill中的设计说明；自定义布局可执行PyQGIS脚本。",
        {"type": "object", "properties": {"design_path": {"type": "string"},
         "template": {"type": "string", "enum": ["choropleth", "facilities"]}},
         "required": ["design_path"], "additionalProperties": False},
        partial(render_map, launcher, log_dir, font_files),
    )]
