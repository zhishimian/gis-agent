import json
from pathlib import Path

import pytest
from PIL import Image

from gis_agent.prompts import render_prompt
from gis_agent.skills import skill_index
from gis_agent.tools.qgis_python import run_python_script


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "gis_agent/skills/gis-cartography/scripts"


def execute(qgis_dir: Path, folder: Path, code: str, arguments: list[str] | None = None) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "probe.py"
    script.write_text(code, encoding="utf-8")
    return run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", folder / "logs", str(script), arguments)


def test_skill_discovery_only_discloses_metadata() -> None:
    skills = skill_index()
    prompt = render_prompt("system.j2", output_dir=ROOT / "outputs", skills=skills,
                           supports_images=True, supports_memory=False)
    assert {item["name"] for item in skills} == {"gis-cartography", "gis-verification", "gis-spatial-analysis"}
    assert all(item["description"] in prompt and Path(item["path"]).is_file() for item in skills)
    assert "scripts/vector_map.py" not in prompt


def test_windows_arguments_roundtrip_and_project_import(qgis_dir: Path, tmp_path: Path) -> None:
    arguments = ['中文 空格.gpkg|layername=点', 'a&b>c<d^e%PATH%!', '"双引号"', "", "两行\n内容"]
    result = execute(qgis_dir, tmp_path / "中文 & 目录", '''import json, os, sys
from pathlib import Path
import gis_agent
Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(json.dumps({"arguments": sys.argv[1:], "cwd": str(Path.cwd())}), encoding="utf-8")
''', arguments)
    assert result["ok"] and result["result"]["arguments"] == arguments, result
    assert Path(result["result"]["cwd"]) == tmp_path / "中文 & 目录"


@pytest.fixture
def plotting_data(qgis_dir: Path, tmp_path: Path) -> Path:
    result = execute(qgis_dir, tmp_path, '''import json, os, sys
from pathlib import Path
import rasterio
import geopandas as gpd
import numpy as np
import pandas
import pyogrio
import pyproj
import shapely
import matplotlib
from affine import Affine
from shapely.geometry import Point, box
from rasterio.transform import from_origin
from rasterio.warp import transform
from rasterio.vrt import WarpedVRT

root = Path.cwd()
data = root / "数据.gpkg"
points = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(500000, 3500000)], crs="EPSG:32650")
points.to_file(data, layer="点", driver="GPKG")
areas = gpd.GeoDataFrame({"id": [1, 2, 3, 4], "value": [0., 5., 10., None]},
    geometry=[box(499980 + i*10, 3499990, 499990 + i*10, 3500010) for i in range(4)], crs=points.crs)
areas.to_file(data, layer="面", driver="GPKG")
assert set(gpd.list_layers(data)["name"]) == {"点", "面"}
read = gpd.read_file(data, layer="点")
assert len(read) == 1 and read.iloc[0]["id"] == 1 and read.crs.to_epsg() == 32650
back = read.to_crs(4326).to_crs(32650)
assert back.geometry.iloc[0].distance(read.geometry.iloc[0]) < 1e-6
array = np.arange(60*1300, dtype="float32").reshape(60, 1300)
array[:2, :2] = -9999
with rasterio.open(root / "terrain.tif", "w", driver="GTiff", width=1300, height=60, count=1,
    dtype="float32", crs=read.crs, transform=from_origin(499350, 3500030, 1, 1), nodata=-9999) as dataset:
    dataset.write(array, 1)
with rasterio.open(root / "terrain.tif") as dataset:
    assert dataset.read(1, masked=True).mask.sum() == 4
    assert dataset.index(500000, 3500000) == (30, 650)
    with WarpedVRT(dataset, crs="EPSG:3857") as projected:
        assert projected.crs.to_epsg() == 3857 and projected.read(1, masked=True).count() > 0
with rasterio.open(root / "rotated.tif", "w", driver="GTiff", width=1300, height=60, count=1,
    dtype="float32", crs=read.crs, transform=from_origin(499350, 3500030, 1, 1) * Affine.rotation(4), nodata=-9999) as dataset:
    dataset.write(array, 1)
lon, lat = transform("EPSG:32650", "EPSG:4326", [500000], [3500000])
assert abs(lon[0] - 117) < 1e-8
Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(json.dumps({
    "python": sys.executable, "prefix": sys.prefix, "version": sys.version,
    "libraries": {module.__name__: {"version": module.__version__, "path": module.__file__}
        for module in (matplotlib, gpd, rasterio, np, pandas, shapely, pyproj, pyogrio)},
    "gdal": {"rasterio": rasterio.__gdal_version__, "pyogrio": pyogrio.__gdal_version_string__},
    "layers": gpd.list_layers(data)["name"].tolist(), "io_passed": True,
}, ensure_ascii=False, indent=2), encoding="utf-8")
''')
    assert result["ok"] and result["result"]["io_passed"], result
    (tmp_path / "environment.json").write_text(json.dumps(result["result"], ensure_ascii=False, indent=2), encoding="utf-8")
    return tmp_path


def test_real_vector_and_all_export_formats(qgis_dir: Path, plotting_data: Path) -> None:
    root = plotting_data
    result = execute(qgis_dir, root, '''import json, os, sys
from pathlib import Path
import geopandas as gpd
from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure
configure_plotting()
import matplotlib.pyplot as plt
data = Path("数据.gpkg").resolve()
area = gpd.read_file(data, layer="面")
points = gpd.read_file(data, layer="点").to_crs(area.crs)
fig, (ax, stats) = plt.subplots(1, 2, figsize=(8, 4), layout="constrained")
try:
    area.plot(ax=ax, color="#d3e9ee", zorder=1)
    points.plot(ax=ax, color="#b83f3f", markersize=40, zorder=4)
    ax.set_aspect("equal")
    ax.set_title("中文地图与原始点")
    ax.set_axis_off()
    stats.bar(["零值", "有效值"], [1, 3])
    export_figure(fig, "all_formats", formats=("png", "svg", "pdf"), inputs=(str(data),),
        map_panels=(MapPanel("main", ax, area.crs.to_string()),))
    assert "qgis.core" not in sys.modules and not any(name.startswith("PyQt") for name in sys.modules)
finally:
    plt.close(fig)
''')
    assert result["ok"] and "Glyph" not in result["stderr"], result
    data = result["result"]
    assert data["version"] == 2 and set(data["files"]) == {"png", "svg", "pdf"}
    assert data["warnings"] == []
    assert Path(data["files"]["pdf"]).read_bytes().startswith(b"%PDF")
    assert b"<svg" in Path(data["files"]["svg"]).read_bytes()
    with Image.open(data["preview"]) as image:
        assert max(image.size) <= 1800
    manifest = json.loads(Path(data["manifest"]).read_text(encoding="utf-8"))
    assert manifest["inputs"] and manifest["environment"]["fonts"]
    assert manifest["map_panels"][0]["crs"] == "EPSG:32650"
    assert {1, 4}.issubset({item["zorder"] for item in manifest["map_panels"][0]["artists"]})
    assert not list(root.rglob("*.qgz")) and not list(root.rglob("*.qpt")) and not list(root.rglob("*.qml"))


def test_executable_examples_with_nodata_and_reprojection(qgis_dir: Path, plotting_data: Path) -> None:
    root = plotting_data
    data = str(root / "数据.gpkg")
    settings = {
        "vector_map": {"area_path": data, "point_path": data, "area_layer": "面", "point_layer": "点", "title": "范围与原始点", "scale_length": 10},
        "choropleth": {"source": data, "layer": "面", "field": "value", "breaks": [0, 5, 10], "colors": ["#dbe9f3", "#3776a4"]},
        "raster_composite": {"raster_path": str(root / "terrain.tif"), "point_path": data, "point_layer": "点", "display_crs": "EPSG:32650"},
    }
    for name, config in settings.items():
        config["output_dir"] = str(root / name)
        request = root / f"{name}.json"
        request.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        result = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", root / "logs", str(SCRIPTS / f"{name}.py"), [str(request)])
        assert result["ok"] and Path(result["result"]["preview"]).is_file(), result
        assert "Glyph" not in result["stderr"], result
    encoding = json.loads((root / "choropleth/encoding.json").read_text(encoding="utf-8"))
    assert encoding["class_counts"] == [1, 2] and encoding["missing"] == 1 and encoding["valid"] == 3
    request.write_text(json.dumps(settings["raster_composite"] | {"raster_path": str(root / "rotated.tif"),
        "display_crs": "EPSG:3857", "output_dir": str(root / "rotated_map")}), encoding="utf-8")
    rotated = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", root / "logs", str(SCRIPTS / "raster_composite.py"), [str(request)])
    assert rotated["ok"] and rotated["result"]["map_panels"][0]["crs"] == "EPSG:3857", rotated
    bad = settings["choropleth"] | {"breaks": [0, 5, 9]}
    request.write_text(json.dumps(bad), encoding="utf-8")
    failed = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", root / "logs", str(SCRIPTS / "choropleth.py"), [str(request)])
    assert not failed["ok"] and "cover" in failed["stderr"]


def test_invalid_fonts_and_outputs_fail_observably(qgis_dir: Path, tmp_path: Path) -> None:
    result = execute(qgis_dir, tmp_path, '''from gis_agent.integrations.plotting.runtime import configure_plotting
configure_plotting(["missing.ttf"])
''')
    assert not result["ok"] and "配置字体不存在" in result["stderr"]
    result = execute(qgis_dir, tmp_path, '''from gis_agent.integrations.plotting.runtime import configure_plotting, export_figure
configure_plotting()
import matplotlib.pyplot as plt
fig = plt.figure()
try:
    export_figure(fig, "invalid", formats=("qgz",))
finally:
    plt.close(fig)
''')
    assert not result["ok"] and "仅支持" in result["stderr"]
