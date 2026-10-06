from functools import partial
from typing import Any
from qgis_backend.client import QGISClient
from tools.base import Tool

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
)->list[dict[str,str]]:
    words=set(query.lower().split())
    matches:list[tuple[int,str]]=[]

    for algorithm_id,metadata in catalog.items():
        name=metadata["name"].lower()
        title=f"{algorithm_id} {name}".lower()
        tags=metadata.get("tags") or []
        if isinstance(tags,list):
            tags=" ".join(tags)
        text=" ".join(str(value) for value in(metadata.get("group"),metadata.get("short_description"),tags,)if value).lower()
        score=sum(3*(word in title)+3*(word==name)+(word in text) for word in words)
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
        for _,algorithm_id in matches[:5]
    ]

def make_search_tool(
        catalog:dict[str,dict[str,Any]],
)->Tool:
    return Tool(
        name="search_qgis_tools",
        description=(
            "Search the QGIS algorithm catalog using short English "
            "keywords. Translate Chinese requests into English. "
            "Search separately for different workflow steps when "
            "necessary. Matching concrete tools become available "
            "in the next response."
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
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        function=partial(search_catalog, catalog),
    )
