import hashlib
import re
import json
from functools import partial
from pathlib import Path
from typing import Any

from qgis_backend.client import QGISClient
from tools.base import Tool
from tools.registry import ToolRegistry

STRING_TYPES={"string","expression","crs","extent","point","file","folder","source","vector","raster","mesh","pointcloud","annotation","maplayer","layout","layoutitem","coordinateoperation",}

def parameter_schema(
        parameter:dict[str,Any],
)->dict[str,Any]:
    type_info=parameter["type"]
    qgis_type=(
        type_info["id"]
        if isinstance(type_info,dict)
        else type_info
    )
    definition=parameter["raw_definition"]

    description=[parameter["description"],
                 f"QGIS参数类型:{qgis_type}"]
    if parameter.get("help"):
        description.append(parameter["help"])
    if parameter.get("default_value") is not None:
        description.append(
            "默认值："
            + json.dumps(
                parameter["default_value"],
                ensure_ascii=False,
            )
        )
    if isinstance(type_info, dict):
        description.extend(
            type_info.get("acceptable_values", [])
        )
    if parameter["is_destination"]:
        schema = {"type": "string"}
        description.append(
            "使用绝对文件或目录路径；"
            "不要使用 memory: 或 TEMPORARY_OUTPUT。"
        )
    elif qgis_type == "boolean":
        schema = {"type": "boolean"}
    elif qgis_type in {"number", "distance", "scale"}:
        schema = {
            "type": (
                "integer"
                if definition.get("data_type") == 0
                else "number"
            )
        }
    elif qgis_type == "enum":
        options = definition.get("options", [])
        static_strings = definition.get(
            "uses_static_strings",
            False,
        )
        item_schema = {
            "type": "string" if static_strings else "integer"
        }
        if options:
            item_schema["enum"] = (
                options
                if static_strings
                else list(range(len(options)))
            )
        if parameter.get("available_options"):
            description.append(
                "枚举选项："
                + json.dumps(
                    parameter["available_options"],
                    ensure_ascii=False,
                )
            )
        schema = (
            {"type": "array", "items": item_schema}
            if definition.get("allow_multiple")
            else item_schema
        )
    elif qgis_type == "multilayer":
        schema = {
            "type": "array",
            "items": {"type": "string"},
        }
    elif qgis_type == "field":
        schema = (
            {
                "type": "array",
                "items": {"type": "string"},
            }
            if definition.get("allow_multiple")
            else {"type": "string"}
        )

    elif qgis_type == "band":
        schema = {"type": "integer"}

    elif qgis_type in STRING_TYPES:
        schema = {"type": "string"}

    else:
        schema = {
            "anyOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {"type": "null"},
                {
                    "type": "array",
                    "items": {},
                },
                {
                    "type": "object",
                    "additionalProperties": True,
                },
            ]
        }

    return {
        **schema,
        "description": "\n".join(description),
    }

def tool_name(algorithm_id: str) -> str:
    name = "qgis_" + re.sub(
        r"[^a-zA-Z0-9_-]",
        "_",
        algorithm_id,
    )

    if len(name) <= 64:
        return name

    suffix = hashlib.sha256(
        algorithm_id.encode("utf-8")
    ).hexdigest()[:8]

    return f"{name[:55]}_{suffix}"

def execute_algorithm(
    client: QGISClient,
    algorithm_id: str,
    definitions: dict[str, Any],
    /,
    **arguments: Any,
) -> dict[str, Any]:
    for name, parameter in definitions.items():
        if not parameter["is_destination"]:
            continue

        if name not in arguments:
            if parameter["optional"]:
                continue

            return {
                "ok": False,
                "algorithm_id": algorithm_id,
                "error": f"必须指定输出参数 {name} 的绝对路径。",
            }

        value = arguments[name]

        if (
            not isinstance(value, str)
            or not Path(value).is_absolute()
        ):
            return {
                "ok": False,
                "algorithm_id": algorithm_id,
                "error": f"输出参数 {name} 必须是绝对路径。",
            }

        if Path(value).is_file():
            return {
                "ok": False,
                "algorithm_id": algorithm_id,
                "error": f"输出文件已经存在：{value}",
            }

    return client.execute(algorithm_id, **arguments)

def make_tool(
    algorithm_id: str,
    metadata: dict[str, Any],
    documentation: dict[str, Any],
    client: QGISClient,
) -> Tool:
    definitions = documentation["parameters"]

    return Tool(
        name=tool_name(algorithm_id),
        description="\n".join(
            str(value)
            for value in (
                algorithm_id,
                metadata["name"],
                metadata.get("group"),
                metadata.get("short_description"),
            )
            if value
        ),
        parameters={
            "type": "object",
            "properties": {
                name: parameter_schema(parameter)
                for name, parameter in definitions.items()
            },
            "required": [
                name
                for name, parameter in definitions.items()
                if not parameter["optional"]
                and (
                    parameter["is_destination"]
                    or parameter.get("default_value") is None
                )
            ],
            "additionalProperties": False,
        },
        function=partial(
            execute_algorithm,
            client,
            algorithm_id,
            definitions,
        ),
    )

def load_qgis_tool(
    client: QGISClient,
    catalog: dict[str, dict[str, Any]],
    registry: ToolRegistry,
    algorithm_id: str,
) -> Tool:
    name = tool_name(algorithm_id)

    if name in registry.tools:
        tool = registry.get(name)

        if tool.description.splitlines()[0] != algorithm_id:
            raise ValueError(
                f"QGIS 工具名称冲突：{algorithm_id} → {name}"
            )

        return tool

    tool = make_tool(
        algorithm_id,
        catalog[algorithm_id],
        client.query("help", algorithm_id),
        client,
    )
    registry.register(tool)

    return tool
