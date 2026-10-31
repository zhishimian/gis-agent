import json
from pathlib import Path

import pytest

from gis_agent.integrations.qgis.adapter import execute_algorithm, parameter_schema
from gis_agent.integrations.qgis.catalog import search_catalog
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.tools.planning import finish_task
from gis_agent.tools.qgis_python import run_python_script


def test_exact_algorithm_excludes_similarly_named_candidates() -> None:
    catalog = {key: {"name": name} for key, name in (
        ("native:buffer", "Buffer"), ("gdal:buffervectors", "Buffer vectors"),
        ("native:singlesidedbuffer", "Single sided buffer"),
    )}
    assert [item["algorithm_id"] for item in search_catalog(catalog, " NATIVE:BUFFER ")] == ["native:buffer"]
    assert len(search_catalog(catalog, "buffer")) == 3


def test_real_help_schema_and_parameter_case(qgis_dir: Path, tmp_path: Path) -> None:
    client = QGISClient(qgis_dir / "bin/qgis_process-qgis-ltr.bat")
    parameters = client.query("help", "native:buffer")["parameters"]
    for name in ("DISTANCE", "SEGMENTS", "DISSOLVE", "END_CAP_STYLE"):
        schema = parameter_schema(parameters[name])
        assert not any(text in schema["description"] for text in ("field:", "expression:"))
    assert parameter_schema(parameters["DISTANCE"])["type"] == "number"
    assert parameter_schema(parameters["DISSOLVE"])["type"] == "boolean"
    output = tmp_path / "should_not_exist.gpkg"
    result = execute_algorithm(client, "native:buffer", parameters, input="missing", OUTPUT=str(output))
    assert not result["ok"] and "INPUT" in result["allowed_parameters"]
    assert "input" in result["error"] and not output.exists()


def test_processing_lifecycle_and_failure(qgis_dir: Path, tmp_path: Path) -> None:
    source = tmp_path / "points.geojson"
    source.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": 17}, "geometry": {"type": "Point", "coordinates": [117, 32]}}
    ]}), encoding="utf-8")
    script = tmp_path / "analysis.py"
    script.write_text('''import sys
from qgis.core import QgsVectorLayer
from gis_agent.integrations.qgis.python_runtime import run_processing

def job():
    import processing
    layer = QgsVectorLayer(sys.argv[1], 'input', 'ogr')
    if sys.argv[2] == 'fail':
        raise ValueError('expected_field_failure')
    if sys.argv[2] == 'serialize':
        return {'layer': layer}
    result = processing.run('native:reprojectlayer', {
        'INPUT': layer, 'TARGET_CRS': 'EPSG:32650', 'OUTPUT': sys.argv[2],
    })
    output = QgsVectorLayer(result['OUTPUT'], 'output', 'ogr')
    return {'count': output.featureCount(), 'crs': output.crs().authid(),
            'id': next(output.getFeatures())['id']}

run_processing(job)
''', encoding="utf-8")
    launcher = qgis_dir / "bin/python-qgis-ltr.bat"
    for number in range(2):
        output = tmp_path / f"projected{number}.gpkg"
        result = run_python_script(launcher, tmp_path / "logs", str(script), [str(source), str(output)])
        assert result["ok"] and result["returncode"] == 0, result
        assert result["result"] == {"count": 1, "crs": "EPSG:32650", "id": 17}
        output.rename(tmp_path / f"released{number}.gpkg")
    for mode, error in (("fail", "expected_field_failure"), ("serialize", "not JSON serializable")):
        result = run_python_script(launcher, tmp_path / "logs", str(script), [str(source), mode])
        assert not result["ok"] and result["returncode"] == 1, result
        assert error in result["stderr"] and "result" not in result


def test_processing_import_error_has_actionable_hint(qgis_dir: Path, tmp_path: Path) -> None:
    script = tmp_path / "missing_import.py"
    script.write_text("import processing\n", encoding="utf-8")
    result = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", tmp_path / "logs", str(script))
    assert not result["ok"] and "ModuleNotFoundError" in result["stderr"]
    assert Path(result["hint"].split("：", 1)[1]).is_file()


def test_finish_exposes_unmet_requirements() -> None:
    result = finish_task("completed", "done", unresolved=["missing required output"])
    assert not result["ok"] and result["unresolved"] == ["missing required output"]
    assert finish_task("completed", "层名为result，已完成要求。")["ok"]
