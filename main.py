from functools import partial
from pathlib import Path
from agent import run_agent
from qgis_backend.adapter import load_qgis_tool
from qgis_backend.catalog import  load_catalog,make_search_tool
from qgis_backend.client import QGISClient
from tools import  registry
from tools.builtin import builtin_tools

def main()->None:
    client=QGISClient()
    catalog=load_catalog(client)
    search_tool=make_search_tool(catalog)

    registry.register(search_tool)
    print(f"QGIS catalog: {len(catalog)} algorithms")
    run_agent(
        registry,
        [*builtin_tools,search_tool],
        partial(
            load_qgis_tool,client,catalog,registry,
        ),
        Path(__file__).resolve().parent/"outputs",
    )

if __name__=="__main__":
    main()