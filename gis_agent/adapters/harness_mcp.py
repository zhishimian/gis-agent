from pathlib import Path
from typing import Any

from gis_agent.config import AppConfig
from gis_agent.integrations.qgis.catalog import load_catalog, make_search_tool
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.runtime.probe import probe_launcher
from gis_agent.tools.base import Tool
from gis_agent.tools.qgis_alg import make_run_qgis_tool
from gis_agent.tools.qgis_python import make_qgis_python_tools


def build_harness_tools(project: Path) -> dict[str, Tool]:
    """为 Claude Code / Codex 等外部 Harness 组装确定性 GIS 工具集，无需启动内部 Agent 循环。"""
    config = AppConfig.from_env(project)
    log_dir = config.output_root / "_harness_logs"
    python_tools = {
        tool.name: tool
        for tool in make_qgis_python_tools(config.python_launcher, log_dir, config.font_files)
        if tool.name in {"inspect_data", "summarize_fields", "check_spatial_relation"}
    }
    python_tools["probe_gis_environment"] = Tool(
        name="probe_gis_environment",
        description="探测当前配置的 GIS Python 解释器版本、已安装空间库与 QGIS/GDAL 可用性。",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=lambda: {"ok": True, **probe_launcher(config.python_launcher)},
    )
    if config.qgis is not None:
        client = QGISClient(config.qgis.process_launcher)
        catalog = load_catalog(client)
        cache: dict[str, dict[str, Any]] = {}
        python_tools["search_qgis_tools"] = make_search_tool(catalog, client, cache)
        python_tools["run_qgis_algorithm"] = make_run_qgis_tool(client, catalog, cache)
    return python_tools
