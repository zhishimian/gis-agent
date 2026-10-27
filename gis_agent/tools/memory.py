from typing import Any

from gis_agent.core.memory import CATEGORIES, MemoryStore, MemoryTurn, make_scope, memory_sources, normalized
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.base import Tool


def make_memory_tools(
    store: MemoryStore, session: SessionStore, messages: list[dict[str, Any]], turn: MemoryTurn,
) -> list[Tool]:
    def remember(
        title: str, body: str, category: str, tags: list[str], source_indices: list[int],
        record_id: str | None = None, machine: bool = False,
        qgis_version: str | None = None, data_path: str | None = None,
    ) -> dict[str, Any]:
        try:
            sources = memory_sources(session, messages, source_indices, category)
            result = store.remember(
                title, body, category, tags, make_scope(store, machine, qgis_version, data_path), sources, record_id,
            )
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        turn.handled_sources.update(source_indices)
        turn.handled_bodies.add(normalized(body))
        return result

    def forget(record_id: str) -> dict[str, Any]:
        record = next((item for item in store.records if item.id == record_id), None)
        result = store.forget(record_id)
        if record is not None and result["ok"]:
            turn.handled_bodies.add(normalized(record.body))
            turn.handled_sources.update(
                source["message_index"] for source in record.sources if source["session_id"] == session.session_id
            )
        return result

    return [
        Tool(
            "search_memory", "检索项目记忆以便查看、更新或删除。返回来源、冲突和 in_scope；不适用记录只作核查资料。输入 ID 也可定位。",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
            store.lookup,
        ),
        Tool(
            "remember_memory", "按用户明确要求新增或按 record_id 更新一条记忆。source_indices 引用当前 Session 的真实用户或工具证据。",
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string"}, "body": {"type": "string"},
                    "category": {"type": "string", "enum": sorted(CATEGORIES)},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "source_indices": {"type": "array", "items": {"type": "integer", "minimum": 0}},
                    "record_id": {"type": "string"}, "machine": {"type": "boolean"},
                    "qgis_version": {"type": "string"}, "data_path": {"type": "string"},
                },
                "required": ["title", "body", "category", "tags", "source_indices"], "additionalProperties": False,
            }, remember,
        ),
        Tool(
            "forget_memory", "根据已定位的 ID 删除活动记忆；原始 Session 和用户文件保留。",
            {"type": "object", "properties": {"record_id": {"type": "string"}}, "required": ["record_id"], "additionalProperties": False},
            forget,
        ),
    ]