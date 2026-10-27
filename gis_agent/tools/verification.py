from pathlib import Path
from typing import Any

from gis_agent.agents.subtasks import SubtaskRunner
from gis_agent.tools.base import Tool
from gis_agent.tools.planning import finish_task


CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "requirement": {"type": "string"},
        "source_indices": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
        "method": {"type": "string"},
        "status": {"type": "string", "enum": ["PASS", "FAIL", "UNKNOWN"]},
        "finding": {"type": "string"},
        "evidence_indices": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["requirement", "source_indices", "method", "status", "finding", "evidence_indices"],
    "additionalProperties": False,
}


def make_verifier_finish(
    messages: list[dict[str, Any]], allowed_sources: set[int], output_dir: Path,
) -> Tool:
    def complete(
        status: str, summary: str, checks: list[dict[str, Any]], artifacts: list[str] | None = None,
    ) -> dict[str, Any]:
        result = finish_task(status, summary)
        if not result["ok"]:
            return result
        if status not in {"completed", "blocked", "needs_input"}:
            return {"ok": False, "error": "验证任务请使用 completed、blocked 或 needs_input。"}
        if not isinstance(checks, list) or (status == "completed" and not checks):
            return {"ok": False, "error": "完成复核时至少提供一项检查。"}
        for check in checks:
            if not isinstance(check, dict) or set(check) != set(CHECK_SCHEMA["properties"]):
                return {"ok": False, "error": "检查项字段不完整。"}
            if any(not isinstance(check[key], str) or not check[key].strip() for key in ("requirement", "method", "finding")):
                return {"ok": False, "error": "检查项的要求、方法和发现必须有正文。"}
            if not isinstance(check["status"], str) or check["status"] not in {"PASS", "FAIL", "UNKNOWN"}:
                return {"ok": False, "error": "检查状态必须是 PASS、FAIL 或 UNKNOWN。"}
            sources = check["source_indices"]
            if not isinstance(sources, list) or not sources or any(type(i) is not int or i not in allowed_sources for i in sources):
                return {"ok": False, "error": "检查项需要引用委派中提供的用户来源序号。"}
            evidence = check["evidence_indices"]
            if not isinstance(evidence, list):
                return {"ok": False, "error": "evidence_indices 必须是子会话工具消息序号列表。"}
            for index in evidence:
                if type(index) is not int or not 0 <= index < len(messages):
                    return {"ok": False, "error": "证据序号无效。"}
                item = messages[index]
                if item["role"] != "tool" or item.get("tool_name") in {"update_plan", "finish_task", "read_session_messages"}:
                    return {"ok": False, "error": "证据需要指向实际检查工具的返回消息。"}
            if check["status"] in {"PASS", "FAIL"} and not evidence:
                return {"ok": False, "error": "PASS 或 FAIL 需要实际工具证据，证据不足时使用 UNKNOWN。"}
        if artifacts is None:
            artifacts = []
        if not isinstance(artifacts, list) or any(not isinstance(path, str) for path in artifacts):
            return {"ok": False, "error": "artifacts 必须是文件路径列表。"}
        paths = [Path(path).expanduser().resolve() for path in artifacts]
        if any(not path.is_file() or not path.is_relative_to(output_dir.resolve()) for path in paths):
            return {"ok": False, "error": "检查产物必须是当前子任务输出目录中的实际文件。"}
        return {**result, "checks": checks, "artifacts": [str(path) for path in paths]}

    return Tool(
        name="finish_task",
        description="结束本次验证并返回逐项检查。completed 表示复核工作结束，检查状态由 checks 分别给出。必须单独调用。",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["completed", "blocked", "needs_input"]},
                "summary": {"type": "string"},
                "checks": {"type": "array", "items": CHECK_SCHEMA},
                "artifacts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["status", "summary", "checks"],
            "additionalProperties": False,
        },
        function=complete,
    )


def make_verification_tools(runner: SubtaskRunner) -> list[Tool]:
    return [
        Tool(
            name="verify_task",
            description=(
                "委派独立验证 Agent，制定检查方案或复核已有成果，返回检查项与记录位置。"
                "source_indices 提供相关用户原话，包含最新输入；artifacts 使用实际文件路径，"
                "Shapefile 同时提供 shp、shx、dbf、prj 等组成文件。输入变化时使用新的 task_id。"
            ),
            parameters={
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
            function=runner.run,
        ),
        Tool(
            name="read_verification",
            description="分段读取当前主会话所属验证子任务的原始消息，按检查结果中的证据序号回读。",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,40}$"},
                    "start": {"type": "integer", "minimum": 0},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8000},
                },
                "required": ["task_id", "start"],
                "additionalProperties": False,
            },
            function=runner.read,
        ),
    ]
