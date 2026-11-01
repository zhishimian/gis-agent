from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.tools.base import Tool


def make_history_tool(history: ExecutionHistory) -> Tool:
    return Tool(
        "execution_history",
        "按需查当前Session真实执行。可按工具、脚本/成果路径或错误检索，默认最近5项；"
        "已有信息充分时直接继续。detail读取所选执行的参数、代码摘录、错误及结果；"
        "script/stdout/stderr/request/traceback按cursor分页读受限且校验过的资源。"
        "多项匹配时详情取offset指定项，默认最新；未知状态不证明执行完成。",
        {"type": "object", "properties": {
            "execution_id": {"type": "string"}, "query": {"type": "string"},
            "tool": {"type": "string"}, "status": {"type": "string"},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            "section": {"type": "string", "enum": ["summary", "detail", "arguments", "result", "error", "links", "script", "stdout", "stderr", "request", "traceback"]},
            "cursor": {"type": "integer", "minimum": 0},
            "max_characters": {"type": "integer", "minimum": 512, "maximum": 8000},
        }, "additionalProperties": False}, history.query,
    )
