from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.base import Tool


def make_session_tool(store: SessionStore) -> Tool:
    return Tool(
        name="read_session_messages",
        description=(
            "按从零开始的消息序号读取当前 Session 原记录，每次一条，长消息按 offset 分页。"
            "使用 next_offset 读完当前条，再使用 next_message 读取下一条；不会自动展开工具资产。"
            "复核压缩过的用户要求时，应回读原话和后续澄清。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "start": {"type": "integer", "minimum": 0},
                "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 8000},
            },
            "required": ["start"], "additionalProperties": False,
        },
        function=store.read_messages,
    )