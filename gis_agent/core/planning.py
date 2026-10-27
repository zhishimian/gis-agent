import json
from dataclasses import dataclass, field
from typing import Any


STEP_STATUSES = ("pending", "in_progress", "completed")


@dataclass
class Plan:
    goal: str = ""
    steps: list[dict[str, str]] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {"goal": self.goal, "steps": [dict(step) for step in self.steps]}

    def unfinished(self) -> list[str]:
        return [step["content"] for step in self.steps if step["status"] != "completed"]

    def update(self, goal: str, steps: list[dict[str, str]]) -> dict[str, Any]:
        if not isinstance(goal, str) or not goal.strip():
            return {"ok": False, "error": "goal 必须是非空字符串。"}
        if not isinstance(steps, list) or not steps:
            return {"ok": False, "error": "steps 必须是非空列表。"}

        validated = []
        for step in steps:
            if not isinstance(step, dict):
                return {"ok": False, "error": "每个步骤必须是对象。"}
            content = step.get("content")
            status = step.get("status")
            if not isinstance(content, str) or not content.strip():
                return {"ok": False, "error": "步骤内容不能为空。"}
            if status not in STEP_STATUSES:
                return {"ok": False, "error": "步骤状态无效。"}
            validated.append({"content": content.strip(), "status": status})

        if sum(step["status"] == "in_progress" for step in validated) > 1:
            return {"ok": False, "error": "同一时间只能有一个进行中的步骤。"}

        self.goal = goal.strip()
        self.steps = validated
        return {"ok": True, "plan": self.snapshot()}

    @classmethod
    def from_messages(cls, messages: list[dict[str, Any]]) -> "Plan":
        plan = cls()
        update_calls = set()
        for message in messages:
            if message["role"] == "assistant":
                update_calls.update(
                    call["id"]
                    for call in message.get("tool_calls", [])
                    if call["function"]["name"] == "update_plan"
                )
            elif message["role"] == "tool" and message["tool_call_id"] in update_calls:
                result = json.loads(message["content"])
                if result.get("ok") is True:
                    restored = plan.update(**result["plan"])
                    if not restored["ok"]:
                        raise ValueError(f"会话中的计划无效：{restored['error']}")
        return plan