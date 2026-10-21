import os
from functools import partial
from pathlib import Path

from dotenv import load_dotenv
from openai import DefaultHttpxClient, OpenAI

from agent import run_agent
from context import ContextConfig
from llm import ModelConfig, chat, make_token_counter
from memory import MemoryConfig
from qgis_backend.adapter import load_qgis_tool
from qgis_backend.catalog import load_catalog, make_search_tool
from qgis_backend.client import QGISClient
from tools import registry
from tools.builtin import builtin_tools
from tools.files import file_tools
from tools.qgis_python import make_qgis_python_tools


def main() -> None:
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    model = ModelConfig()
    model_client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"], base_url=model.base_url, max_retries=3,
        http_client=DefaultHttpxClient(trust_env=False),
    )
    qgis_dir = Path("E:/exe/qgis")
    output_root = root / "outputs"
    qgis_client = QGISClient(launcher=qgis_dir / "bin" / "qgis_process-qgis-ltr.bat")
    catalog = load_catalog(qgis_client)
    extra_tools = [
        make_search_tool(catalog), *file_tools,
        *make_qgis_python_tools(qgis_dir / "bin" / "python-qgis-ltr.bat", output_root / "python_logs"),
    ]
    for tool in extra_tools:
        registry.register(tool)
    print(f"QGIS catalog: {len(catalog)} algorithms")
    run_agent(
        registry, [*builtin_tools, *extra_tools],
        partial(load_qgis_tool, qgis_client, catalog, registry), output_root,
        chat=partial(chat, model_client, model), session_root=root / "sessions",
        context_config=ContextConfig(request_token_limit=min(900_000, model.context_window - model.max_tokens - 16384)),
        count_tokens=make_token_counter(model), memory_config=MemoryConfig(project=root),
    )


if __name__ == "__main__":
    main()
