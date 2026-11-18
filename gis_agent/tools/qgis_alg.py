from pathlib import Path
from threading import Event
from typing import Any

from gis_agent.integrations.qgis.adapter import execute_algorithm
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.tools.base import Tool


def run_qgis_algorithm(
    client: QGISClient,
    catalog: dict[str, dict[str, Any]],
    help_cache: dict[str, dict[str, Any]],
    protected_paths: tuple[Path, ...],
    algorithm_id: str,
    parameters: dict[str, Any],
    project_path: str | None = None,
    timeout_sec: int = 300,
    cancel_event: Event | None = None,
) -> dict[str, Any]:
    if not isinstance(algorithm_id, str) or not algorithm_id.strip():
        return {"ok": False, "status": "failed", "error": "必须提供非空的 algorithm_id。"}
    algorithm_id = algorithm_id.strip()
    if catalog and algorithm_id not in catalog:
        exact = next((key for key in catalog if key.lower() == algorithm_id.lower()), None)
        if exact is None:
            return {
                "ok": False,
                "status": "failed",
                "algorithm_id": algorithm_id,
                "error": f"未找到算法 {algorithm_id}，请先用 search_qgis_tools 查询准确 ID。",
            }
        algorithm_id = exact
    if not isinstance(parameters, dict):
        return {"ok": False, "status": "failed", "algorithm_id": algorithm_id, "error": "parameters 必须是 JSON 对象。"}
    if not isinstance(timeout_sec, int) or not 10 <= timeout_sec <= 600:
        return {"ok": False, "status": "failed", "algorithm_id": algorithm_id, "error": "timeout_sec 必须在 10 到 600 秒之间。"}

    if algorithm_id not in help_cache:
        help_cache[algorithm_id] = client.query("help", algorithm_id)
    definitions = help_cache[algorithm_id]["parameters"]

    if protected_paths:
        resolved_protected = [item.expanduser().resolve() for item in protected_paths]
        for name, definition in definitions.items():
            if definition["is_destination"] and isinstance(parameters.get(name), str):
                target = Path(parameters[name]).expanduser().resolve()
                if any(target == root or target.is_relative_to(root) for root in resolved_protected):
                    return {
                        "ok": False,
                        "status": "failed",
                        "algorithm_id": algorithm_id,
                        "error": f"禁止将输出写入受保护输入路径：{target}",
                    }

    call_args = dict(parameters)
    if project_path is not None:
        call_args["project_path"] = project_path
    effective_cancel = cancel_event or client.cancel_event
    if timeout_sec != client.timeout or effective_cancel is not client.cancel_event:
        timed_client = QGISClient(client.launcher, timeout=timeout_sec, cancel_event=effective_cancel)
        return execute_algorithm(timed_client, algorithm_id, definitions, **call_args)
    return execute_algorithm(client, algorithm_id, definitions, **call_args)


def make_run_qgis_tool(
    client: QGISClient,
    catalog: dict[str, dict[str, Any]],
    help_cache: dict[str, dict[str, Any]] | None = None,
    protected_paths: tuple[Path, ...] = (),
    cancel_event: Event | None = None,
) -> Tool:
    cache = help_cache if help_cache is not None else {}
    return Tool(
        name="run_qgis_algorithm",
        description=(
            "按准确 algorithm_id 执行单个标准 QGIS Processing 算法。"
            "parameters 传入算法参数字典（使用 Schema 原始大写参数名，必填输出使用不存在的新绝对路径）。"
            "未知参数名、缺失输出或覆盖已有文件会被直接拦截并返回允许参数列表。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "algorithm_id": {"type": "string", "description": "准确算法 ID，如 'native:buffer'。"},
                "parameters": {"type": "object", "additionalProperties": True, "description": "算法输入与输出参数字典。"},
                "project_path": {"type": "string", "description": "布局等算法所需的已有 QGIS 工程绝对路径。"},
                "timeout_sec": {"type": "integer", "minimum": 10, "maximum": 600, "description": "超时秒数，默认 300，上限 600。"},
            },
            "required": ["algorithm_id", "parameters"],
            "additionalProperties": False,
        },
        function=lambda algorithm_id, parameters, project_path=None, timeout_sec=300: run_qgis_algorithm(
            client,
            catalog,
            cache,
            protected_paths,
            algorithm_id,
            parameters,
            project_path=project_path,
            timeout_sec=timeout_sec,
            cancel_event=cancel_event,
        ),
    )
