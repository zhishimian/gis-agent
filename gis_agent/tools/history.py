from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.tools.base import Tool


def make_history_tool(history: ExecutionHistory) -> Tool:
    return Tool(
        "execution_history",
        "查当前Session真实执行版本、当时参数、代码快照、结果和错误。当前文件多次修改、查上次成功版本或摘要后回查时尤其有用。"
        "用execution_id或脚本名query，status可筛succeeded/failed/unknown/returned，默认最近5项。detail读取参数、代码摘录、错误及结果；"
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
