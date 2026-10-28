import json
from pathlib import Path
from typing import Any

from gis_agent.agents.subtasks import SubtaskRunner
from gis_agent.persistence.evidence import file_digest, save_evidence, tool_evidence
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.base import Tool
from gis_agent.tools.planning import finish_task


def make_cartography_tools(
    runner: SubtaskRunner, resources: list[Path], font_files: tuple[Path, ...],
    supports_images: bool,
) -> list[Tool]:
    def run(task_id: str, goal: str, source_indices: list[int], artifacts: list[str]) -> dict[str, Any]:
        if not isinstance(artifacts, list) or any(not isinstance(path, str) for path in artifacts):
            return {"ok": False, "error": "artifacts 必须是实际文件路径列表。"}
        if not supports_images:
            return {"ok": False, "error": "制图角色需要启用图像输入，请先检查模型和 GIS_AGENT_VISION。"}
        if not font_files or any(not path.is_file() for path in font_files):
            return {"ok": False, "error": "请通过 GIS_AGENT_FONT_FILES 配置存在的本机字体文件。"}
        return runner.run(
            task_id, goal, source_indices,
            [*artifacts, *(str(path) for path in resources), *(str(path) for path in font_files)],
        )

    return [
        Tool(
            "cartograph_task",
            "委派制图 Agent。goal 指明 brief.json 路径；artifacts 登记简报、GIS数据和实际依赖，source_indices 引用用户原话并包含最新输入。资源与字体自动登记。已结束任务需使用新 task_id 修正。",
            {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,40}$"},
                    "goal": {"type": "string"},
                    "source_indices": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
                    "artifacts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["task_id", "goal", "source_indices", "artifacts"],
                "additionalProperties": False,
            },
            run,
        ),
        Tool(
            "read_cartography", "读取制图子任务已有结果，核对输入、记录和产物版本，不发起模型调用。",
            {"type": "object", "properties": {"task_id": {"type": "string"}},
             "required": ["task_id"], "additionalProperties": False},
            runner.read_result,
        ),
    ]


def make_cartography_rule_tool(path: Path) -> Tool:
    def read(rule_ids: list[str]) -> dict[str, Any]:
        rules = {item["id"]: item for item in json.loads(path.read_text(encoding="utf-8"))}
        if not isinstance(rule_ids, list) or not rule_ids or any(not isinstance(key, str) or key not in rules for key in rule_ids):
            return {"ok": False, "error": "rule_ids 需要填写规则目录中的 ID。"}
        return {"ok": True, "rules": [rules[key] for key in dict.fromkeys(rule_ids)]}

    return Tool(
        "read_cartography_rules", "按 ID 读取少量相关制图规则，返回条件、决策、参数、检查和限制。",
        {"type": "object", "properties": {"rule_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
         "required": ["rule_ids"], "additionalProperties": False},
        read,
    )


def make_cartography_finish(
    store: SessionStore, messages: list[dict[str, Any]], output_dir: Path,
    request: dict[str, Any], *, require_image: bool = True,
) -> Tool:
    root = output_dir.resolve()

    def complete(status: str, summary: str, artifacts: list[str] | None = None) -> dict[str, Any]:
        result = finish_task(status, summary)
        if not result["ok"]:
            return result
        if status not in {"completed", "blocked", "needs_input"}:
            return {"ok": False, "error": "制图任务请使用 completed、blocked 或 needs_input。"}
        if artifacts is None:
            artifacts = []
        if not isinstance(artifacts, list) or any(not isinstance(value, str) for value in artifacts):
            return {"ok": False, "error": "artifacts 必须是文件路径列表。"}
        paths = {Path(value).expanduser().resolve() for value in artifacts}
        if any(not path.is_file() or not path.is_relative_to(root) for path in paths):
            return {"ok": False, "error": "制图产物必须是本子任务目录中的现有文件。"}
        if status != "completed":
            return {**result, "artifacts": [str(path) for path in sorted(paths)]}
        manifest_path = root / "manifest.json"
        if manifest_path not in paths:
            return {"ok": False, "error": "请登记本子任务目录中的 manifest.json。"}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("version") != 1:
            return {"ok": False, "error": "制图 manifest 版本无效。"}
        files = manifest.get("files", {})
        outputs = manifest.get("outputs", [])
        if not isinstance(files, dict) or not isinstance(outputs, list) or not outputs:
            return {"ok": False, "error": "manifest 缺少 files 或 outputs。"}
        expected = {Path(row["path"]).resolve(): row["sha256"] for row in request["artifacts"]}
        for row in manifest.get("inputs", []):
            path = Path(row["path"]).resolve()
            if expected.get(path) != row["sha256"] or not path.is_file() or file_digest(path) != row["sha256"]:
                return {"ok": False, "error": f"输入未登记或版本变化：{path}"}
        versions = {}
        for row in outputs:
            relative = Path(row["path"])
            path = (root / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(root) or path not in paths:
                return {"ok": False, "error": "manifest.outputs 必须全部登记到本目录 artifacts。"}
            if file_digest(path) != row["sha256"]:
                return {"ok": False, "error": f"产物版本变化：{path}"}
            versions[path] = row["sha256"]
        for key in ("brief", "design", "script", "preview", "project", "layout"):
            if not isinstance(files.get(key), str) or (root / files[key]).resolve() not in versions:
                return {"ok": False, "error": f"manifest 缺少已登记产物：{key}"}
        for relative in [*files.get("styles", {}).values(), *(item["path"] for item in files.get("details", []))]:
            if (root / relative).resolve() not in versions:
                return {"ok": False, "error": "样式与局部图也必须登记到 manifest.outputs。"}
        brief = json.loads((root / files["brief"]).read_text(encoding="utf-8"))
        formats = brief.get("medium", {}).get("format", ["png", "qgz"])
        for kind in formats:
            key = "project" if kind == "qgz" else kind
            if key not in files or not isinstance(files[key], str) or (root / files[key]).resolve() not in versions:
                return {"ok": False, "error": f"尚未提供用户要求的格式：{kind}"}
        records = []
        preview_hash = versions[(root / files["preview"]).resolve()]
        script_hash = versions[(root / files["script"]).resolve()]
        view_index = -1
        render_index = -1
        for index, message in enumerate(messages):
            if message.get("role") != "tool" or message.get("tool_name") not in {"read_image", "run_python_script"}:
                continue
            proof = tool_evidence(store, messages, index)
            if not proof["ok"]:
                continue
            record = proof["record"]
            value = record["result"]
            if not isinstance(value, dict) or value.get("ok") is not True:
                continue
            if record["tool_name"] == "read_image":
                image = value.get("image", {})
                if image.get("crop") is None and image.get("source_sha256") == preview_hash:
                    view_index = index
                    records.append(record)
            elif value.get("script_sha256") == script_hash:
                lines = Path(value["stdout_path"]).read_text(encoding="utf-8").strip().splitlines()
                if lines and lines[-1].startswith("{"):
                    report = json.loads(lines[-1])
                    if isinstance(report, dict) and report.get("manifest") == str(manifest_path) and report.get("manifest_sha256") == file_digest(manifest_path):
                        render_index = index
                        records.append(record)
        if render_index < 0:
            return {"ok": False, "error": "缺少当前渲染脚本与 manifest 版本对应的成功执行记录，请重新执行并打印 export_layout 的返回值。"}
        if require_image and view_index < render_index:
            return {"ok": False, "error": "请用 read_image 整图读取当前 preview，重新导出后需要重新读取。"}
        evidence = [save_evidence(root, record) for record in records]
        evidence_files = {item["path"] for record in records for item in record["files"]}
        evidence_files.update(item["path"] for item in evidence)
        return {
            **result, "artifacts": [str(path) for path in sorted(paths)],
            "manifest": str(manifest_path), "evidence": evidence,
            "evidence_files": sorted(evidence_files), "image_reviewed": require_image,
        }

    return Tool(
        "finish_task",
        "结束制图任务，completed 需登记完整产物、当前渲染执行及整图读取。必须单独调用。",
        {"type": "object", "properties": {
            "status": {"type": "string", "enum": ["completed", "blocked", "needs_input"]},
            "summary": {"type": "string"},
            "artifacts": {"type": "array", "items": {"type": "string"}},
        }, "required": ["status", "summary", "artifacts"], "additionalProperties": False},
        complete,
    )

