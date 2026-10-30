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
            "Search the QGIS algorithm catalog using short English "
            "keywords. Translate Chinese requests into English. "
            "Use an exact algorithm ID when known. limit defaults to 3 (maximum 5). "
            "Selected candidates become callable on the next response; only tools whose schemas "
            "are actually provided can be called. Search by exact "
            "algorithm ID to rediscover a candidate."
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
