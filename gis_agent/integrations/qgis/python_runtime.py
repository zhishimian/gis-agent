import json
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any


def run_processing(job: Callable[[], dict[str, Any]]) -> None:
    from qgis.core import QgsApplication, QgsProject

    app = QgsApplication([], False)
    try:
        app.initQgis()
        plugins = str(Path(QgsApplication.prefixPath()) / "python/plugins")
        if plugins not in sys.path:
            sys.path.insert(0, plugins)
        from processing.core.Processing import Processing

        Processing.initialize()
        text = json.dumps(job(), ensure_ascii=False, allow_nan=False)
    except BaseException as error:
        # 异常栈可能继续持有job中的图层，须先释放已退出的函数帧。
        traceback.clear_frames(error.__traceback__)
        raise
    finally:
        QgsProject.instance().clear()
        app.exitQgis()

    Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(text, encoding="utf-8")
