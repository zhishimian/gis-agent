import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any, BinaryIO

from gis_agent.config import AppConfig
from gis_agent.integrations.qgis.catalog import load_catalog, make_search_tool
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.persistence.json import json_text
from gis_agent.runtime.paths import default_project_dir
from gis_agent.runtime.probe import probe_launcher
from gis_agent.skills import skill_index
from gis_agent.tools.base import Tool
from gis_agent.tools.qgis_alg import make_run_qgis_tool
from gis_agent.tools.qgis_python import make_qgis_python_tools


PROTOCOL_VERSION = "2024-11-05"


def build_harness_tools(project: Path) -> dict[str, Tool]:
    """为 Claude Code / Codex / Cursor 等外部 Harness 组装确定性 GIS 内环工具集，零内部 Agent 循环依赖。"""
    config = AppConfig.from_env(project)
    log_dir = config.output_root / "_harness_logs"
    tools = {
        tool.name: tool
        for tool in make_qgis_python_tools(config.python_launcher, log_dir, config.font_files)
        if tool.name in {"inspect_data", "summarize_fields", "check_spatial_relation"}
    }
    tools["probe_gis_environment"] = Tool(
        name="probe_gis_environment",
        description="探测当前配置的 GIS Python 解释器版本、已安装空间库与 QGIS/GDAL 可用性。",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=lambda: {"ok": True, **probe_launcher(config.python_launcher)},
    )
    tools["list_gis_skills"] = Tool(
        name="list_gis_skills",
        description="列出内置专业 GIS Skills（空间分析、核查取证、专题制图）的名称、适用场景与本地 SKILL.md 路径。",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=lambda: {"ok": True, "skills": skill_index()},
    )
    if config.qgis is not None:
        client = QGISClient(config.qgis.process_launcher)
        catalog = load_catalog(client)
        cache: dict[str, dict[str, Any]] = {}
        tools["search_qgis_tools"] = make_search_tool(catalog, client, cache)
        tools["run_qgis_algorithm"] = make_run_qgis_tool(client, catalog, cache)
    return tools


class MCPServer:
    """纯标准库 JSON-RPC 2.0 STDIO MCP 服务端，兼容行分隔 JSON 与 Content-Length 帧。"""

    def __init__(self, tools: dict[str, Tool]) -> None:
        self.tools = tools

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        req_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params") or {}

        # JSON-RPC Notification（无 id）：按协议静默处理，不发送响应帧
        if "id" not in message:
            return None

        if method == "initialize":
            client_version = params.get("protocolVersion")
            version = client_version if isinstance(client_version, str) and client_version else PROTOCOL_VERSION
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "gis-agent-mcp", "version": "9.0.1"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            listed = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.parameters,
                }
                for tool in sorted(self.tools.values(), key=lambda item: item.name)
            ]
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": listed}}
        if method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments") or {}
            if name not in self.tools:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"未知 GIS 工具：{name}"},
                }
            if not isinstance(arguments, dict):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "arguments 必须是 JSON 对象。"},
                }
            try:
                outcome = self.tools[name].run(arguments)
            except Exception as error:
                outcome = {"ok": False, "error": f"{type(error).__name__}: {error}"}
            is_error = bool(isinstance(outcome, dict) and outcome.get("ok") is False)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json_text(outcome)}],
                    "isError": is_error,
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"不支持的 MCP 方法：{method}"},
        }

    def serve_stdio(self, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> None:
        inp = stdin if stdin is not None else sys.stdin.buffer
        out = stdout if stdout is not None else sys.stdout.buffer
        while True:
            line = inp.readline()
            if not line:
                break
            stripped = line.strip()
            if not stripped:
                continue
            use_header = False
            if stripped.lower().startswith(b"content-length:"):
                use_header = True
                length = int(stripped.split(b":", 1)[1].strip())
                while True:
                    hdr = inp.readline()
                    if not hdr or hdr in (b"\r\n", b"\n"):
                        break
                raw_body = inp.read(length)
            else:
                raw_body = stripped
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                response: dict[str, Any] | None = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"JSON 解析错误：{error}"},
                }
            else:
                response = self.handle_message(payload)
            if response is not None:
                encoded = json.dumps(response, ensure_ascii=False).encode("utf-8")
                if use_header:
                    out.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii") + encoded)
                else:
                    out.write(encoded + b"\n")
                out.flush()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="GIS-Agent STDIO MCP Server (Ring 1 Primitives + Skills)")
    parser.add_argument("--project", type=Path, default=default_project_dir())
    args = parser.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(message)s")
    server = MCPServer(build_harness_tools(args.project))
    server.serve_stdio()


if __name__ == "__main__":
    main()
