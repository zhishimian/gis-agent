from functools import partial
import re
from typing import Any

from gis_agent.integrations.qgis.adapter import parameter_schema
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.tools.base import Tool


def load_catalog(client: QGISClient) -> dict[str, dict[str, Any]]:
    return {
        algorithm_id: metadata
        for provider in client.query("list")["providers"].values()
        for algorithm_id, metadata in provider["algorithms"].items()
    }


def search_catalog(
    catalog: dict[str, dict[str, Any]],
    query: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    if not query.strip() or not 1 <= limit <= 5:
        return []
    exact = next((key for key in catalog if key.lower() == query.strip().lower()), None)
    if exact is not None:
        catalog = {exact: catalog[exact]}
    words = set(re.findall(r"[a-z0-9]+", query.lower()))
    if not words:
        return []
    matches: list[tuple[int, str]] = []

    for algorithm_id, metadata in catalog.items():
        name = metadata["name"].lower()
        title = f"{algorithm_id} {name}".lower()
        tags = metadata.get("tags") or []
        if isinstance(tags, list):
            tags = " ".join(tags)
        text = " ".join(
            str(value)
            for value in (metadata.get("group"), metadata.get("short_description"), tags)
            if value
        ).lower()
        title_words = set(re.findall(r"[a-z0-9]+", title))
        text_words = set(re.findall(r"[a-z0-9]+", text))
        score = sum(6 * (word in title_words) + (word in text_words) for word in words)
        if query.strip().lower() == algorithm_id.lower():
            score += 1000
        score += 10 * (words <= title_words)
        if score:
            matches.append((score, algorithm_id))
    matches.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "algorithm_id": algorithm_id,
            "name": catalog[algorithm_id]["name"],
            "group": catalog[algorithm_id].get("group") or "",
            "description": catalog[algorithm_id].get("short_description") or "",
        }
        for _, algorithm_id in matches[:limit]
    ]


def describe_algorithm(documentation: dict[str, Any]) -> dict[str, Any]:
    definitions = documentation.get("parameters", {})
    details = documentation.get("algorithm_details", {})
    flags = details.get("documentation_flags") or []
    warnings = []
    if any("regenerates_primary_key" in flag for flag in flags):
        warnings.append("输出可能重建主键/FID；关联原数据前保留稳定业务ID并核对空间归属。")
    if details.get("deprecated"):
        warnings.append("此算法已弃用，请核对当前版本推荐算法。")
    required = [
        name
        for name, item in definitions.items()
        if not item["optional"] and (item["is_destination"] or item.get("default_value") is None)
    ]
    parameters = {name: parameter_schema(item) for name, item in definitions.items()}
    return {"required_parameters": required, "parameters": parameters, "warnings": warnings}


def search_with_docs(
    catalog: dict[str, dict[str, Any]],
    client: QGISClient | None,
    help_cache: dict[str, dict[str, Any]],
    query: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    rows = search_catalog(catalog, query, limit)
    if client is None:
        return rows
    enriched = []
    for row in rows:
        algorithm_id = row["algorithm_id"]
        if algorithm_id not in help_cache:
            help_cache[algorithm_id] = client.query("help", algorithm_id)
        enriched.append({**row, **describe_algorithm(help_cache[algorithm_id])})
    return enriched


def make_search_tool(
    catalog: dict[str, dict[str, Any]],
    client: QGISClient | None = None,
    help_cache: dict[str, dict[str, Any]] | None = None,
) -> Tool:
    cache = help_cache if help_cache is not None else {}
    return Tool(
        name="search_qgis_tools",
        description=(
            "用简短英文关键词发现QGIS算法；中文需求先转成英文术语。"
            "已知准确algorithm_id时按ID查询，只返回该算法；探索默认返回3项，最多5项。"
            "返回结果直接附带参数说明与必填项，查到后使用 run_qgis_algorithm 执行，不动态修改顶层Schema。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Short English keywords or exact algorithm_id, e.g. 'native:buffer', 'reproject layer'.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        function=partial(search_with_docs, catalog, client, cache),
    )
