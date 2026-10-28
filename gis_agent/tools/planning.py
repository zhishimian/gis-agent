from typing import Any

from gis_agent.core.planning import Plan, STEP_STATUSES
from gis_agent.tools.base import Tool


FINISH_STATUSES = ("completed", "needs_input", "blocked", "answer")


def finish_task(status: str, summary: str) -> dict[str, Any]:
    if status not in FINISH_STATUSES:
        return {"ok": False, "error": "结束状态无效。"}
    if not isinstance(summary, str) or not summary.strip():
        return {"ok": False, "error": "必须提供交付说明或停止原因。"}
    return {"ok": True, "status": status, "summary": summary.strip()}


def make_planning_tools(plan: Plan) -> list[Tool]:
    return [
        Tool(
            name="update_plan",
            description=(
                "设置或更新当前任务的完整计划。goal 记录用户目标，steps 整表替换。"
                "继续任务时保留已完成项，新任务应更换目标和清单。"
                "多步骤任务先列计划，最后包含按用户要求复核并整理交付。"
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
                "completed 请求交付，程序按当前配置检查复核结果与计划；根据返回说明继续处理。"
                "needs_input 表示需要用户补充信息；blocked 表示执行受阻。"
                "answer 用于本轮未执行操作的普通问答，不关闭已有计划。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": list(FINISH_STATUSES)},
                    "summary": {"type": "string"},
                },
                "required": ["status", "summary"],
                "additionalProperties": False,
            },
            function=finish_task,
        ),
    ]
