from functools import partial
import re
from typing import Any
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.tools.base import Tool

def load_catalog(
        client:QGISClient,
)->dict[str,dict[str,Any]]:
    return{
        algorithm_id:metadata
        for provider in client.query("list")["providers"].values()
        for algorithm_id,metadata
        in provider["algorithms"].items()
    }

def search_catalog(
        catalog:dict[str,dict[str,Any]],
        query:str,
        limit:int=3,
)->list[dict[str,str]]:
    if not query.strip() or not 1 <= limit <= 5:
        return []
    exact = next((key for key in catalog if key.lower() == query.strip().lower()), None)
    if exact is not None:
        catalog = {exact: catalog[exact]}
    words=set(re.findall(r"[a-z0-9]+", query.lower()))
    if not words:
        return []
    matches:list[tuple[int,str]]=[]

    for algorithm_id,metadata in catalog.items():
        name=metadata["name"].lower()
        title=f"{algorithm_id} {name}".lower()
        tags=metadata.get("tags") or []
        if isinstance(tags,list):
            tags=" ".join(tags)
        text=" ".join(str(value) for value in(metadata.get("group"),metadata.get("short_description"),tags,)if value).lower()
        title_words = set(re.findall(r"[a-z0-9]+", title))
        text_words = set(re.findall(r"[a-z0-9]+", text))
        score = sum(6 * (word in title_words) + (word in text_words) for word in words)
        if query.strip().lower() == algorithm_id.lower():
            score += 1000
        score += 10 * (words <= title_words)
        if score:
            matches.append((score,algorithm_id))
    matches.sort(key=lambda item:(-item[0],item[1]))
    return [
        {"algorithm_id":algorithm_id,
        "name":catalog[algorithm_id]["name"],
        "group":catalog[algorithm_id].get("group") or "",
        "description":(
            catalog[algorithm_id].get("short_description")
            or ""
        ),
        }
        for _,algorithm_id in matches[:limit]
    ]

def make_search_tool(
        catalog:dict[str,dict[str,Any]],
)->Tool:
    return Tool(
        name="search_qgis_tools",
        description=(
            "用简短英文关键词发现QGIS算法；中文需求先转成英文术语。"
            "已知准确algorithm_id时按ID查询，只返回该算法；探索默认返回3项，最多5项。"
            "候选完整Schema在下一次响应提供，可直接调用其tool_name，无需另写初始化脚本。"
            "已有适用Schema时直接复用，候选不适用时再调整查询。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Short English keywords, such as "
                        "'vector buffer', 'reproject layer', "
                        "or 'polygon intersection'."
                        ),
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        function=partial(search_catalog, catalog),
    )
