import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def qgis_dir() -> Path:
    value = os.environ.get("GIS_AGENT_QGIS_DIR") or dotenv_values(ROOT / ".env").get("GIS_AGENT_QGIS_DIR")
    if not value:
        pytest.skip("请设置 GIS_AGENT_QGIS_DIR。")
    path = Path(value).expanduser().resolve()
    for launcher in ("qgis_process-qgis-ltr.bat", "python-qgis-ltr.bat"):
        if not (path / "bin" / launcher).is_file():
            pytest.skip("未找到 QGIS；可设置 GIS_AGENT_QGIS_DIR 为安装目录。")
    return path


