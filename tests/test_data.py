import json
from pathlib import Path

from tools.qgis_python import inspect_data


def test_inspect_vector(tmp_path: Path) -> None:
    source = tmp_path / "point.geojson"
    source.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "测试点"},
                "geometry": {
                    "type": "Point",
                    "coordinates": [118.8, 32.0],
                },
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    result = inspect_data(
        Path("E:/exe/qgis/bin/python-qgis-ltr.bat"),
        tmp_path / "logs",
        str(source),
    )

    assert result["ok"], result
    assert result["data"]["feature_count"] == 1
    assert result["data"]["crs"] == "EPSG:4326"
    assert result["data"]["samples"][0]["name"] == "测试点"