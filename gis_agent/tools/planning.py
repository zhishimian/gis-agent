from typing import Any
from pathlib import Path

from gis_agent.core.planning import Plan, STEP_STATUSES
from gis_agent.tools.base import Tool


FINISH_STATUSES = ("completed", "needs_input", "blocked", "answer")


def finish_task(
    status: str, summary: str, artifacts: list[str] | None = None,
    unresolved: list[str] | None = None,
) -> dict[str, Any]:
    if status not in FINISH_STATUSES:
        return {"ok": False, "error": "结束状态无效。"}
    if not isinstance(summary, str) or not summary.strip():
        return {"ok": False, "error": "必须提供交付说明或停止原因。"}
    if artifacts is not None and (not isinstance(artifacts, list) or any(not isinstance(path, str) for path in artifacts)):
        return {"ok": False, "error": "artifacts 需要填写实际文件或数据集目录的绝对路径。"}
    if unresolved is not None and (not isinstance(unresolved, list) or any(not isinstance(item, str) for item in unresolved)):
        return {"ok": False, "error": "unresolved 需要填写未完成或无法确认的事项列表。"}
    missing = [path for path in artifacts or [] if not Path(path).is_absolute() or not Path(path).exists()]
    if missing:
        return {"ok": False, "error": "成果路径不存在或未使用绝对路径。", "paths": missing}
    if status == "completed" and unresolved:
        return {"ok": False, "error": "还有未完成事项，请继续处理或使用 blocked/needs_input 如实结束。"}
    return {"ok": True, "status": status, "summary": summary.strip(),
            "artifacts": list(dict.fromkeys(artifacts or [])), "unresolved": unresolved or []}


def make_planning_tools(plan: Plan) -> list[Tool]:
    return [
        Tool(
            name="update_plan",
            description=(
                "设置或更新当前任务的完整计划。goal 记录用户目标，steps 整表替换。"
                "继续任务时保留已完成项，新任务应更换目标和清单。"
                "简单单项操作直接执行；多个独立目标或较长分析链再列计划，包含复核与交付。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {"type": "string", "enum": list(STEP_STATUSES)},
                            },
                            "required": ["content", "status"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["goal", "steps"],
                "additionalProperties": False,
            },
            function=plan.update,
        ),
        Tool(
            name="finish_task",
            description=(
                "报告本轮结束状态和面向用户的说明，必须单独调用。"
                "completed 表示所需工作已完成，artifacts 列出实际文件或数据集目录。"
                "unresolved 列出未完成项或未知事项，存在时使用 blocked 或 needs_input。"
                "needs_input 表示需要用户补充信息；blocked 表示执行受阻。"
                "answer 用于普通问答，可先读取资料；本轮已写入或计算成果时报告任务状态。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": list(FINISH_STATUSES)},
                    "summary": {"type": "string"},
                    "artifacts": {"type": "array", "items": {"type": "string"}},
                    "unresolved": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["status", "summary"],
                "additionalProperties": False,
            },
            function=finish_task,
        ),
    ]
