from gis_agent.agents.delivery import DeliveryReview
from gis_agent.tools.base import Tool


def make_delivery_tools(review: DeliveryReview) -> list[Tool]:
    return [
        Tool(
            name="review_delivery",
            description=(
                "登记候选版本，委派独立验证 Agent 阅读要求并自行选择少量重难点复核。"
                "goal 简述实际方法与关键参数，无需另写重复报告。"
                "交付文件位于当前输出目录的 candidates/candidate_id/。"
                "修正时生成新候选，用 previous_id 关联上一版，repairs 逐项说明未解决检查的处理方式。"
                "inputs 提供原始数据、分析脚本和其他依赖。关闭数据写入后再提交。"
                "相同 ID 仅用于同一内容和参数的恢复。ready 表示本次复核状态，交付时还会重新核对。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,32}$"},
                    "goal": {"type": "string"},
                    "source_indices": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
                    "inputs": {"type": "array", "items": {"type": "string"}},
                    "deliverables": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "previous_id": {"type": ["string", "null"]},
                    "repairs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"check_id": {"type": "string"}, "action": {"type": "string"}},
                            "required": ["check_id", "action"], "additionalProperties": False,
                        },
                    },
                },
                "required": ["candidate_id", "goal", "source_indices", "inputs", "deliverables"],
                "additionalProperties": False,
            },
            function=review.review,
        ),
        Tool(
            name="read_delivery",
            description="读取候选登记、逐项问题和当前有效性。只读取已有记录与文件，不发起模型调用。",
            parameters={
                "type": "object", "properties": {"candidate_id": {"type": "string"}},
                "required": ["candidate_id"], "additionalProperties": False,
            },
            function=review.read,
        ),
    ]
