from functools import partial
from pathlib import Path

from agent import run_agent
from qgis_backend.adapter import load_qgis_tool
from qgis_backend.catalog import load_catalog, make_search_tool
from qgis_backend.client import QGISClient
from tools import registry
from tools.builtin import builtin_tools
from tools.files import file_tools
from tools.qgis_python import make_qgis_python_tools


def main() -> None:
    qgis_dir = Path("E:/exe/qgis")
    output_root = Path(__file__).resolve().parent / "outputs"
    client = QGISClient(launcher=qgis_dir / "bin" / "qgis_process-qgis-ltr.bat")
    catalog = load_catalog(client)
    extra_tools = [
        make_search_tool(catalog),
        *file_tools,
        *make_qgis_python_tools(
            qgis_dir / "bin" / "python-qgis-ltr.bat",
            output_root / "python_logs",
        ),
    ]
    for tool in extra_tools:
        registry.register(tool)

    print(f"QGIS catalog: {len(catalog)} algorithms")
    run_agent(
        registry,
        [*builtin_tools, *extra_tools],
        partial(load_qgis_tool, client, catalog, registry),
        output_root,
        max_steps=30,
    )


if __name__ == "__main__":
    main()