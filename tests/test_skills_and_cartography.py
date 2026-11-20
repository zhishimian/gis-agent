"""七大领域 Skill 格式链接校验、双环境参考脚本与静默制图测试。"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import struct
import sys
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from PIL import Image
import pytest
import yaml

from gis_agent.prompts import render_prompt
from gis_agent.skills import skill_index
from gis_agent.tools.qgis_python import run_python_script

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "gis_agent/skills"
SCRIPTS = ROOT / "gis_agent/skills/gis-cartography/scripts"


def execute(qgis_dir: Path, folder: Path, code: str, arguments: list[str] | None = None) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "check.py"
    script.write_text(code, encoding="utf-8")
    return run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", folder / "logs", str(script), arguments)


def script_call(qgis_dir: Path, folder: Path, skill: str, script: str, settings: dict) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    config = folder / "settings.json"
    config.write_text(json.dumps(settings), encoding="utf-8")
    return run_python_script(
        qgis_dir / "bin/python-qgis-ltr.bat",
        folder / "logs",
        str(SKILLS / skill / "scripts" / script),
        [str(config)],
    )


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


def test_skill_discovery_only_discloses_metadata() -> None:
    skills = skill_index()
    prompt = render_prompt("system.j2", output_dir=ROOT / "outputs", skills=skills,
                           supports_images=True, supports_memory=False)
    assert {item["name"] for item in skills} == {
        "gis-cartography",
        "gis-verification",
        "gis-data-io-and-staging",
        "gis-vector-and-network",
        "gis-raster-and-imagery",
        "gis-terrain-and-hydrology",
        "gis-spatial-statistics",
    }
    assert all(item["description"] in prompt and Path(item["path"]).is_file() for item in skills)
    assert "scripts/vector_map.py" not in prompt


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


@pytest.fixture
def data(qgis_dir: Path, tmp_path: Path) -> Path:
    result = execute(qgis_dir, tmp_path, '''import json, os
from pathlib import Path
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, LineString, Point, box, mapping

folder=Path.cwd()
multi=MultiPolygon([box(20,0,22,2), Polygon([(30,0),(33,0),(33,3),(30,3),(30,0)], holes=[[(31,1),(32,1),(32,2),(31,2),(31,1)]])])
objects=[Polygon([(0,0),(10,0),(10,10),(0,10),(0,0)], holes=[[(2,2),(4,2),(4,4),(2,4),(2,2)]]), multi,
         GeometryCollection([multi,Point(1,1),LineString([(0,0),(3,4)])]),GeometryCollection(),None]
features=[{'type':'Feature','properties':{'key':k},'geometry':mapping(g) if g is not None else None}
          for k,g in zip(['polygon','multi','collection','empty','null'],objects)]
for name,crs in [('geometry','EPSG:3857'),('geographic','EPSG:4326')]:
    (folder/(name+'.geojson')).write_text(json.dumps({'type':'FeatureCollection','crs':{'type':'name','properties':{'name':crs}},'features':features}),encoding='utf-8')
gpd.GeoDataFrame({'key':['anchor']},geometry=[Point(0,0)],crs='EPSG:3857').to_file(folder/'reference.gpkg',layer='points')
gpd.GeoDataFrame({'key':[None]},geometry=[Point(1,1)],crs='EPSG:3857').to_file(folder/'reference.gpkg',layer='null_key')
path=folder/'versions.gpkg'
gpd.GeoDataFrame({'key':['001','002','003',None]},geometry=[Point(i,0) for i in range(4)],crs='EPSG:3857').to_file(path,layer='before')
gpd.GeoDataFrame({'new_key':['001','001','004',None]},geometry=[Point(i,1) for i in range(4)],crs='EPSG:3857').to_file(path,layer='after')
path=folder/'join.gpkg'
left=gpd.GeoDataFrame({'object_key':['a','b','c','d'],'amount':[6.,8.,0.,None],'base':[2.,0.,4.,1.]},
 geometry=[box(0,0,2,2),box(9,0,11,2),box(30,0,32,2),MultiPolygon([box(14,0,15,1),box(16,0,17,1)])],crs='EPSG:3857')
right=gpd.GeoDataFrame({'zone_key':['R1','R2']},geometry=[box(-5,-5,10,10),box(10,-5,20,10)],crs=left.crs)
left.to_file(path,layer='source');right.to_file(path,layer='reference')
left.to_crs(4326).to_file(path,layer='source_geographic')
right.to_crs(4326).to_file(path,layer='geographic')
Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'prepared':True}),encoding='utf-8')
''')
    assert result["ok"], result
    return tmp_path


def test_skill_format_links_language_and_disclosure() -> None:
    skills = skill_index()
    assert {s["name"] for s in skills} == {
        "gis-cartography",
        "gis-verification",
        "gis-data-io-and-staging",
        "gis-vector-and-network",
        "gis-raster-and-imagery",
        "gis-terrain-and-hydrology",
        "gis-spatial-statistics",
    }
    for item in skills:
        folder = SKILLS / item["name"]
        text = (folder / "SKILL.md").read_text(encoding="utf-8")
        metadata = yaml.safe_load(text.split("---", 2)[1])
        assert metadata["name"] == folder.name and len(metadata["description"]) <= 1024
        assert isinstance(metadata.get("compatibility"), str) and 0 < len(metadata["compatibility"]) <= 500
        assert set(metadata) <= {"name", "description", "compatibility", "metadata", "license", "allowed-tools"}
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", metadata["name"]) and len(metadata["name"]) <= 64
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in metadata.get("metadata", {}).items())
        assert item["description"] == metadata["description"] and set(item) == {"name", "description", "path"}
        for path in folder.rglob("*"):
            if path.suffix not in {".py", ".md"}:
                continue
            content = path.read_text(encoding="utf-8")
            assert not re.search(r"[\u4e00-\u9fff]", content), path
            if path.suffix == ".md":
                for target in re.findall(r"\]\(([^)]+)\)", content):
                    if "://" not in target:
                        filename, _, fragment = target.partition("#")
                        linked = path.parent / filename
                        assert linked.exists(), (path, target)
                        if fragment:
                            headings = re.findall(r"^#{1,6} (.+)$", linked.read_text(encoding="utf-8"), re.MULTILINE)
                            assert fragment in {re.sub(r"[^\w -]", "", h.lower()).replace(" ", "-") for h in headings}, (path, target)
    prompt = render_prompt("system.j2", output_dir=ROOT / "outputs", skills=skills, supports_images=True, supports_memory=False)
    assert all(item["description"] in prompt for item in skills)
    assert "identity_audit.py" not in prompt and "reproject_clip.py" not in prompt


def test_multipart_collection_and_reference_facts(qgis_dir: Path, data: Path) -> None:
    settings = {"source": str(data / "geometry.geojson"), "key": "key", "limit": 5,
                "reference": {"source": str(data / "reference.gpkg"), "layer": "points"}}
    run = script_call(qgis_dir, data / "facts", "gis-verification", "geometry_facts.py", settings)
    assert run["ok"], run
    facts = {f["id"]: f for f in run["result"]["facts"]}
    assert facts["polygon"]["area"] == 96 and facts["polygon"]["holes"] == 1
    assert facts["multi"]["polygon_parts"] == 2 and facts["multi"]["holes"] == 1
    assert facts["multi"]["area"] == 12 and facts["multi"]["length"] == 24
    assert facts["multi"]["distance"] == 20
    assert facts["polygon"]["polygon_boundary_distance"] == 0
    assert facts["multi"]["vertex_distance"]["max"] == pytest.approx((33**2 + 3**2)**.5)
    assert facts["collection"]["polygon_parts"] == 2 and facts["collection"]["leaf_parts"] == 4
    assert facts["collection"]["area"] == 12 and facts["collection"]["length"] == 29
    assert facts["empty"]["empty"] and facts["null"]["null"]
    settings.update(source=str(data / "geographic.geojson"), reference=None, ids=["polygon"])
    geographic = script_call(qgis_dir, data / "geo_facts", "gis-verification", "geometry_facts.py", settings)
    assert geographic["ok"] and "area" not in geographic["result"]["facts"][0]
    settings["reference"] = {"source": str(data / "reference.gpkg"), "layer": "points"}
    failed = script_call(qgis_dir, data / "geo_distance", "gis-verification", "geometry_facts.py", settings)
    assert not failed["ok"] and "projected CRS" in failed["stderr"]
    settings.update(measure_crs="EPSG:3857", reference=None)
    transformed = script_call(qgis_dir, data / "transformed", "gis-verification", "geometry_facts.py", settings)
    assert transformed["ok"] and transformed["result"]["facts"][0]["area"] > 0
    nullable = script_call(qgis_dir, data / "null_key", "gis-verification", "geometry_facts.py", {
        "source": str(data / "reference.gpkg"), "layer": "null_key", "key": "key",
    })
    assert nullable["ok"] and nullable["result"]["facts"][0]["id"] is None


def test_identity_coverage_is_not_a_one_to_one_verdict(qgis_dir: Path, data: Path) -> None:
    result = script_call(qgis_dir, data / "identity", "gis-verification", "identity_audit.py", {
        "source": str(data / "versions.gpkg"), "result": str(data / "versions.gpkg"),
        "source_layer": "before", "result_layer": "after", "key": "key", "result_key": "new_key",
    })
    assert result["ok"], result
    facts = result["result"]
    assert facts["source_null_rows"] == facts["result_null_rows"] == 1
    assert facts["result_duplicate_rows"] == 1 and facts["source_duplicate_rows"] == 0
    assert facts["result_duplicate_examples"] == ["001"]
    assert facts["lost_ids"] == {"count": 2, "examples": ["002", "003"]}
    assert facts["added_ids"] == {"count": 1, "examples": ["004"]}
    assert facts["shared_multiplicities"] == {"1:2": 1} and "passed" not in facts
    missing = script_call(qgis_dir, data / "identity_missing", "gis-verification", "identity_audit.py", {
        "source": str(data / "versions.gpkg"), "result": str(data / "versions.gpkg"),
        "source_layer": "before", "result_layer": "after", "key": "unknown_key",
    })
    assert not missing["ok"] and "unknown_key" in missing["stderr"]


def test_join_preserves_objects_multiplicity_zero_and_missing(qgis_dir: Path, data: Path) -> None:
    settings = {"source": str(data / "join.gpkg"), "source_layer": "source", "source_key": "object_key",
                "reference": str(data / "join.gpkg"), "reference_layer": "reference", "reference_key": "zone_key",
                "output_dir": str(data / "joined"), "query_geometry": "representative_point", "predicate": "covered_by",
                "numerator": "amount", "denominator": "base", "ratio_field": "chosen_ratio"}
    result = script_call(qgis_dir, data / "join_run", "gis-vector-and-network", "spatial_join.py", settings)
    assert result["ok"], result
    facts = result["result"]
    assert facts["source_count"] == facts["result_count"] == 4
    assert facts["multiple_matches"] == facts["unmatched"] == 1
    assert facts["match_pairs"] == 4 and facts["undefined_ratios"] == 2
    check = execute(qgis_dir, data / "join_check", f'''import json, os
from pathlib import Path
import geopandas as gpd
import pandas as pd
source=gpd.read_file({str(data / 'join.gpkg')!r},layer='source').set_index('object_key')
result=gpd.read_file({str(data / 'joined/features.gpkg')!r},layer='features').set_index('object_key')
assert set(source.index)==set(result.index)
assert all(source.loc[k].geometry.equals(result.loc[k].geometry) for k in source.index)
assert result.match_count.to_dict()=={{'a':1,'b':2,'c':0,'d':1}}
assert result.loc['a','chosen_ratio']==3 and result.loc['c','chosen_ratio']==0
assert pd.isna(result.loc['b','chosen_ratio']) and pd.isna(result.loc['d','chosen_ratio'])
ledger=pd.read_csv({str(data / 'joined/matches.csv')!r})
assert len(ledger)==4 and set(ledger.loc[ledger.source_id=='b','reference_id'])=={{'R1','R2'}}
Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({{'independent':True}}),encoding='utf-8')
''')
    assert check["ok"], check
    settings.update(reference_layer="geographic", output_dir=str(data / "mismatch"))
    failed = script_call(qgis_dir, data / "mismatch_run", "gis-vector-and-network", "spatial_join.py", settings)
    assert not failed["ok"] and "CRS mismatch" in failed["stderr"]
    settings.update(analysis_crs="EPSG:3857", output_dir=str(data / "explicit_crs"),
                    query_geometry="geometry", predicate="intersects")
    transformed = script_call(qgis_dir, data / "explicit_run", "gis-vector-and-network", "spatial_join.py", settings)
    assert transformed["ok"] and transformed["result"]["match_pairs"] == 4


def test_processing_chain_real_area_and_output_protection(qgis_dir: Path, data: Path) -> None:
    output = data / "clip.gpkg"
    settings = {"source": f"{data / 'join.gpkg'}|layername=source_geographic", "mask": f"{data / 'join.gpkg'}|layername=reference",
                "target_crs": "EPSG:3857", "output": str(output)}
    result = script_call(qgis_dir, data / "chain", "gis-vector-and-network", "reproject_clip.py", settings)
    assert result["ok"] and result["returncode"] == 0, result
    checked = execute(qgis_dir, data / "chain_check", f'''import json,os
from pathlib import Path
import geopandas as gpd
result=gpd.read_file({str(output)!r})
assert result.crs.to_epsg()==3857 and result.is_valid.all()
assert set(result.object_key)=={{'a','b','d'}}
assert abs(result.area.sum()-10)<1e-8
Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({{'area':float(result.area.sum())}}),encoding='utf-8')
''')
    assert checked["ok"], checked
    refused = script_call(qgis_dir, data / "chain_again", "gis-vector-and-network", "reproject_clip.py", settings)
    assert not refused["ok"] and "FileExistsError" in refused["stderr"]


def test_join_keeps_large_numeric_ids_exact(qgis_dir: Path, tmp_path: Path) -> None:
    checked = execute(qgis_dir, tmp_path, f'''import json,os,runpy
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point,box
analyze=runpy.run_path({str(SKILLS / 'gis-vector-and-network/scripts/spatial_join.py')!r})['analyze']
path=Path.cwd()/'ids.gpkg'
first,second,target=2**53+1,2**53+3,2**53+5
gpd.GeoDataFrame({{'id':[first,second]}},geometry=[Point(0,0),Point(20,0)],crs='EPSG:3857').to_file(path,layer='source')
gpd.GeoDataFrame({{'id':[target]}},geometry=[box(-1,-1,1,1)],crs='EPSG:3857').to_file(path,layer='target')
value=analyze(str(path),str(path),'id','id',str(Path.cwd()/'output'),source_layer='source',reference_layer='target')
ledger=pd.read_csv(value['outputs']['matches'],dtype='string')
assert ledger.source_id.tolist()==[str(first)] and ledger.reference_id.tolist()==[str(target)]
actual=gpd.read_file(value['outputs']['features'],layer='features')
assert actual.id.tolist()==[first,second] and actual.match_count.tolist()==[1,0]
gpd.GeoDataFrame({{'id':[first]}},geometry=[None],crs='EPSG:3857').to_file(path,layer='missing_geometry')
try:
    analyze(str(path),str(path),'id','id',str(Path.cwd()/'invalid'),source_layer='missing_geometry',reference_layer='target')
except ValueError as error:
    assert 'explicit matching policy' in str(error)
else:
    raise AssertionError('Unknown geometry was silently treated as unmatched')
Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({{'exact':True}}),encoding='utf-8')
''')
    assert checked["ok"], checked


def test_parallel_edges_expose_a_feasible_but_nonoptimal_route(qgis_dir: Path, tmp_path: Path) -> None:
    run = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", tmp_path / "logs",
                            str(SKILLS / "gis-vector-and-network/scripts/parallel_edges.py"))
    assert run["ok"] and run["returncode"] == 0, run
    facts = run["result"]
    expected = min(9, 2 + 3, 7 + 3)
    assert facts["minimum_cost"] == facts["multigraph_cost"] == expected == 5
    assert facts["overwritten_cost"] == 9 > expected
    assert facts["retained_road"] == "short" and facts["parallel_alternatives"] == 2


def test_float32_rounding_against_independent_decimal_arithmetic(qgis_dir: Path, tmp_path: Path) -> None:
    run = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", tmp_path / "logs",
                            str(SKILLS / "gis-verification/scripts/precision_example.py"))
    assert run["ok"] and run["returncode"] == 0, run
    facts = run["result"]
    assert facts["stored_float32"] == struct.unpack("<f", struct.pack("<f", 12.345))[0]
    expected = (Decimal.from_float(facts["stored_float32"]) - Decimal(str(facts["base"]))).quantize(
        Decimal(".01"), rounding=ROUND_HALF_EVEN)
    assert facts["height_from_raw"] == float(expected) == 10.24
    assert facts["height_after_early_rounding"] == 10.23
    assert facts["distance"] > facts["threshold"]
    assert facts["raw_within"] is False and facts["rounded_within"] is True


def test_saved_schema_business_keys_and_merge_suffixes(qgis_dir: Path, tmp_path: Path) -> None:
    run = execute(qgis_dir, tmp_path, '''import json, os
from pathlib import Path
import geopandas as gpd
from shapely.geometry import Point

path=Path.cwd()/'versions.gpkg'
source=gpd.GeoDataFrame({'object_key':['001','002'],'zone_key':[10,20],'name':['Home A','Home B']},
    geometry=[Point(0,0),Point(1,0)],crs='EPSG:3857',index=[50,70])
source.to_file(path,layer='objects',index=False)
left=gpd.read_file(path,layer='objects')
assert gpd.list_layers(path)['name'].tolist()==['objects']
assert left.index.tolist()==[0,1] and left.object_key.tolist()==['001','002']
zones=gpd.GeoDataFrame({'zone_key':[20,10],'name':['Zone B','Zone A']},
    geometry=[Point(1,0),Point(0,0)],crs=left.crs)
unsafe=left.merge(zones.drop(columns='geometry'),on='zone_key')
assert 'name' not in unsafe and {'name_x','name_y'}.issubset(unsafe.columns)
reference=zones[['zone_key','name']].rename(columns={'name':'zone_name'})
joined=left.merge(reference,on='zone_key',how='left',validate='many_to_one')
assert joined.set_index('object_key').zone_name.to_dict()=={'001':'Zone A','002':'Zone B'}
assert joined.name.tolist()==['Home A','Home B']
Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'keys':joined.object_key.tolist(),'columns':joined.columns.tolist()}),encoding='utf-8')
''')
    assert run["ok"] and run["result"]["keys"] == ["001", "002"], run


def test_scale_textarea_font_api_and_real_render(qgis_dir: Path, tmp_path: Path) -> None:
    run = execute(qgis_dir, tmp_path, '''import json, os
from pathlib import Path
from gis_agent.integrations.plotting.runtime import configure_plotting
configure_plotting()
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.text import Text
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar

fig, ax=plt.subplots()
try:
    ax.set(xlim=(0,10),ylim=(0,10),aspect='equal')
    bar=AnchoredSizeBar(ax.transData,2,'2 units','lower left',fontproperties=FontProperties(size=9))
    ax.add_artist(bar)
    label=next(child for child in bar.txt_label.get_children() if isinstance(child,Text))
    assert label.get_fontsize()==9
    assert not hasattr(bar.txt_label,'set_fontsize')
    assert not hasattr(bar.txt_label,'set_text_props')
    label.set_fontsize(8.5)
    fig.canvas.draw()
    assert label.get_fontsize()==8.5
    output=Path.cwd()/'scale.png'
    fig.savefig(output)
    Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'png':str(output),'font_size':label.get_fontsize(),'matplotlib':matplotlib.__version__}),encoding='utf-8')
finally:
    plt.close(fig)
''')
    assert run["ok"] and run["result"]["font_size"] == 8.5, run
    with Image.open(run["result"]["png"]) as image:
        assert image.width > 0 and image.height > 0


def test_holdout_selection_counterexample(qgis_dir: Path, tmp_path: Path) -> None:
    result = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", tmp_path / "logs",
        str(ROOT / "gis_agent/skills/gis-verification/scripts/validation_split.py"))
    assert result["ok"], result
    facts = result["result"]
    groups = [set(facts[name]) for name in ("train_ids", "validation_ids", "test_ids")]
    assert all(not left & right for i, left in enumerate(groups) for right in groups[i + 1:])
    assert facts["selected_on_validation"] == "low" and facts["selected_on_test"] == "high"
    assert facts["final_test_rmse"] == math.sqrt((16 + 25) / 2)
    assert facts["test_selected_rmse"] == math.sqrt((0 + 1) / 2)
    assert facts["test_selected_rmse"] < facts["final_test_rmse"]


def test_terrain_masks_nested_outlets_and_cache(qgis_dir: Path, tmp_path: Path) -> None:
    result = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", tmp_path / "logs",
        str(ROOT / "gis_agent/skills/gis-terrain-and-hydrology/scripts/terrain_counterexamples.py"))
    assert result["ok"], result
    facts = result["result"]
    assert facts["upper_catchment"] == [0, 1, 2]
    assert facts["lower_catchment"] == [0, 1, 2, 3, 4] and facts["lower_partition"] == [3, 4]
    assert facts["unsafe_stencil_mean"] == (10 + 12 + 14 - 9999) / 4
    assert facts["masked_stencil_mean"] is None and facts["valid_stencil_mean"] == 13
    assert facts["valid_zero"] == 0
    assert facts["all_pairs"] == 100_000_000_000 and facts["bounded_pairs"] == 8_000_000
    assert facts["cache_key"] == facts["same_key"]
    assert all(facts[name] != facts["cache_key"] for name in ("changed_input", "changed_grid", "changed_code"))


def test_network_n1_to_n6(qgis_dir, tmp_path):
    run = run_python_script(qgis_dir / 'bin/python-qgis-ltr.bat', tmp_path / 'logs',
                           str(SKILLS / 'gis-vector-and-network/scripts/network_cases.py'))
    assert run['ok'], run
    assert set(run['result']) == {f'N{i}' for i in range(1, 7)}
    assert run['result']['N3']['nearest'][0]['cost'] == 10


def test_real_io_roundtrip(qgis_dir, tmp_path):
    script = SKILLS / 'gis-data-io-and-staging/scripts/io_roundtrip.py'
    config = tmp_path / 'settings.json'
    config.write_text(json.dumps({'output_dir': str(tmp_path / 'io')}), encoding='utf-8')
    result = run_python_script(qgis_dir / 'bin/python-qgis-ltr.bat', tmp_path / 'logs', str(script), [str(config)])
    assert result['ok'], result
    assert set(result['result']['outputs']) == {'GPKG', 'OpenFileGDB', 'raster'}
    again = run_python_script(qgis_dir / 'bin/python-qgis-ltr.bat', tmp_path / 'logs', str(script), [str(config)])
    assert not again['ok']  # no silent overwrite of diagnostic artifacts


def test_jenks_against_exhaustive_small_oracle_and_real_maps(qgis_dir, tmp_path):
    script_dir = SKILLS / 'gis-cartography/scripts'
    code = f'''import sys, json, os, itertools
from pathlib import Path
sys.path.insert(0,{str(script_dir)!r})
import numpy as np
import geopandas as gpd
from shapely.geometry import box
from classify_values import classify_values, legend_labels
from choropleth import draw
from vector_map import draw as vector

def sse(groups):
    return sum(float(((v-v.mean())**2).sum()) for v in groups if len(v))
rng=np.random.default_rng(17)
for n in range(2,9):
    for k in range(1,min(n,4)+1):
        values=np.sort(rng.integers(0,40,n)).astype(float)
        actual=classify_values(values,k=k)
        effective=actual['effective_k']
        got=sse([values[np.array(actual['labels'])==i] for i in range(effective)])
        expected=min(sse(np.split(values,cuts)) for cuts in itertools.combinations(range(1,n),effective-1))
        assert abs(got-expected)<1e-8,(values,k,actual,got,expected)
assert classify_values([0,1,100],k=2)['labels']==[0,0,1]
assert classify_values([0,100,101],k=2)['labels']==[0,1,1]
assert classify_values([2,2,None,float('inf')],k=5)['counts']==[2]
assert classify_values([None],k=2)['effective_k']==0
assert classify_values([0,1,2],k=9)['effective_k']==3
for unsafe in ([2**53+1,2**53+2], [2**53+1,None]):
    try: classify_values(unsafe,k=2)
    except ValueError: pass
    else: raise AssertionError('Integer precision loss was silent')
try: classify_values(range(50),max_fit_values=10)
except ValueError: pass
else: raise AssertionError('Exact budget not enforced')
sample=classify_values(range(50),sample_size=10,max_fit_values=10,k=3)
assert sample['approximate'] and sum(sample['counts'])==50
folder=Path.cwd()
data=gpd.GeoDataFrame({{'value':[0.,1.,100.,None]}},geometry=[box(i,0,i+.9,1) for i in range(4)],crs=32650,index=[70,20,5,90])
source=folder/'areas.gpkg';data.to_file(source,layer='areas',index=False)
result=draw(str(source),'value',str(folder/'map'),layer='areas',method='fisher_jenks',k=2)
encoding=json.loads((folder/'map/encoding.json').read_text())
assert encoding['class_counts']==[2,1]
assert encoding['classification']['labels']==[0,0,1]
assert all(result['metrics'][k]>=0 for k in ['input_fingerprint_ms','draw_ms','save_ms','preview_ms'])
try: vector(str(source),str(source),str(folder/'bad'),area_layer='areas',point_layer='areas')
except ValueError as e: assert 'points' in str(e)
else: raise AssertionError('Polygon pretending to be point accepted')
Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({{'oracle_cases':25,'map':result,'class_counts':encoding['class_counts']}}))
'''
    run = execute(qgis_dir, tmp_path, code)
    assert run['ok'], run


def test_allocation_facts_and_unknowns(qgis_dir, tmp_path):
    code = f'''import sys, json, os
from pathlib import Path
sys.path.insert(0,{str(SKILLS / 'gis-verification/scripts')!r})
import pandas as pd
from allocation_balance import allocation_balance
expected=pd.Series({{'a':10.,'b':20.,'c':0.,'d':5.}})
data=pd.DataFrame({{'zone':['a','a','b','unknown'],'value':[4.,3.,None,9.]}})
facts=allocation_balance(expected,data,zone_key='zone',value='value',unit='people')
by={{row['zone']:row for row in facts['zones']}}
assert by['a']['residual']==3 and by['d']['residual']==5
assert by['b']['residual'] is None and facts['residual_total'] is None
assert facts['unknown_zone_rows']==1 and set(facts['zones_without_allocations'])=={{'c','d'}}
assert 'PASS' not in facts
Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps(facts,allow_nan=False))
'''
    run = execute(qgis_dir, tmp_path, code)
    assert run['ok'], run


def test_new_asset_cli_settings_and_result_channels(qgis_dir, tmp_path):
    expected = tmp_path/'expected.csv'
    allocated = tmp_path/'allocated.csv'
    expected.write_text('zone,value\n0001,10\n0002,5\n')
    allocated.write_text('zone,value\n0001,7\n')
    cases = [
        ('gis-verification', 'allocation_balance.py',
         {'expected':str(expected),'allocations':str(allocated),'zone_key':'zone','value':'value',
          'unit':'people','output':str(tmp_path/'balances.json')}),
        ('gis-vector-and-network', 'network_location.py',
         {'costs':[[1,9],[20,2]],'weights':[1,1],'p':1}),
        ('gis-cartography', 'classify_values.py', {'values':[0,1,100,None],'k':2}),
    ]
    results = []
    for index,(skill,script,settings) in enumerate(cases):
        job = tmp_path/f'job{index}.json'
        job.write_text(json.dumps(settings),encoding='utf-8')
        run = run_python_script(qgis_dir/'bin/python-qgis-ltr.bat',tmp_path/'logs',
                                str(SKILLS/skill/'scripts'/script),[str(job)])
        assert run['ok'],run
        results.append(run['result'])
    assert results[0]['residual_total']==8 and results[0]['zones_without_allocations']==['0002']
    assert results[1]['sites']==[1]
    assert results[2]['labels']==[0,0,1,-1] and results[2]['counts']==[2,1]

def test_skills_applicability_fixture_names_are_valid() -> None:
    """skills_applicability.json 中所有预期 Skill 均存在于 7 技能目录中且覆盖全部拆分技能。"""
    fixture_path = ROOT / "tests/fixtures/skills_applicability.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    valid_names = {s["name"] for s in skill_index()}
    seen: set[str] = set()
    for case in cases:
        for name in case["expected"]:
            assert name in valid_names, case
            seen.add(name)
    assert seen == valid_names


def test_new_v902_skill_scripts_offline(tmp_path: Path) -> None:
    """V9.0.2 新增栅格对齐、水文汇流与双环境空间统计示例脚本在当前解释器下离线通过。"""
    import importlib.util

    if any(importlib.util.find_spec(mod) is None for mod in ("numpy", "scipy", "rasterio", "shapely")):
        pytest.skip("当前解释器缺少基础地理依赖。")

    scripts = [
        ("gis-raster-and-imagery", "raster_align_index.py"),
        ("gis-terrain-and-hydrology", "hydrology_routing.py"),
        ("gis-spatial-statistics", "spatial_stats_examples.py"),
        ("gis-verification", "metamorphic_checks.py"),
    ]
    results = {}
    for skill, name in scripts:
        run = run_python_script(Path(sys.executable), tmp_path / "logs", str(SKILLS / skill / "scripts" / name))
        assert run["ok"] and run["returncode"] == 0, (name, run)
        results[name] = run["result"]

    assert results["raster_align_index.py"]["valid_pixels"] == 32
    assert results["raster_align_index.py"]["savi_mean_scaled_reflectance"] < results["raster_align_index.py"]["savi_mean_unscaled_dn"]
    assert results["hydrology_routing.py"]["upper_accumulation_cells"] == 6
    assert results["hydrology_routing.py"]["lower_accumulation_cells"] == 12
    assert results["hydrology_routing.py"]["flood"]["connected_volume_m3"] == 850.0
    stats = results["spatial_stats_examples.py"]
    assert abs(stats["moran_i_tier_a"] - stats["moran_i_tier_b"]) < 1e-5
    meta = results["metamorphic_checks.py"]
    assert meta["conservation_ok"]["within_tolerance"] and not meta["conservation_leak"]["within_tolerance"]
    assert meta["permutation_good_invariant"] and not meta["permutation_pos_bug_invariant"]
    assert meta["boundary"]["boundary_only_keys"] == ["edge"]
    assert meta["ndvi_scale_invariant"] and not meta["savi_scale_invariant"]


def test_v905_palette_bank_and_anti_slop_guard(monkeypatch) -> None:
    """V9.0.5 科学色带库、禁用默认伪彩红线与双变量分箱测试（含缺失 cmcrameri 的 Tier A 降级）。"""
    import importlib.util
    if importlib.util.find_spec("matplotlib") is None or importlib.util.find_spec("numpy") is None:
        pytest.skip("当前解释器缺少 matplotlib/numpy。")

    import numpy as np
    from gis_agent.integrations.plotting.primitives import (
        BANNED_CMAPS,
        GEO_COLORS,
        bivariate_classify,
        build_bivariate_palette,
        get_bivariate_palette,
        get_palette,
        get_scientific_cmap,
        list_palettes,
    )

    catalog = list_palettes()
    assert len(catalog["sequential"]) >= 17
    assert len(catalog["diverging"]) >= 11
    assert len(catalog["qualitative"]) >= 10
    assert len(catalog["bivariate"]) >= 5
    assert {"land_muted", "ocean_soft", "nodata_gray", "zero_neutral"}.issubset(GEO_COLORS)

    for bad in ("jet", "rainbow", "hsv", "JET", "nipy_spectral", "prism", "rainbow_r"):
        assert bad.lower() in BANNED_CMAPS or bad.lower().removesuffix("_r") in BANNED_CMAPS
        with pytest.raises(ValueError, match="禁用"):
            get_scientific_cmap("sequential", bad)
        with pytest.raises(ValueError, match="禁用"):
            get_palette(bad)

    for kind, name in (("sequential", "carto_teal"), ("sequential", "hypsometric"), ("diverging", "tol_sunset"), ("qualitative", "okabe_ito")):
        cmap = get_scientific_cmap(kind, name, n=5, nodata_color="#d9d9d9")
        assert cmap.N == 5
        assert tuple(round(float(v), 3) for v in cmap.get_bad()[:3]) == (0.851, 0.851, 0.851)

    grid5 = build_bivariate_palette("#f2f2f2", "#1e78b4", "#e66101", "#2b1c47", n=5)
    assert len(grid5) == 5 and all(len(r) == 5 for r in grid5)
    assert grid5[0][0] == "#f2f2f2" and grid5[4][4] == "#2b1c47"
    assert len(get_bivariate_palette("stevens_pinkblue")) == 3

    biv3 = bivariate_classify([1.0, 5.0, 9.0, np.nan], [10.0, 20.0, 30.0, 40.0], bins=3, method="equal")
    assert biv3["x_bin"].tolist() == [0, 1, 2, -1]
    assert biv3["y_bin"].tolist() == [0, 1, 2, -1]
    assert biv3["pair_index"].tolist() == [0, 4, 8, -1]

    bivq = bivariate_classify([1.0, 2.0, 3.0, np.nan, 4.0], [10.0, 20.0, 30.0, 40.0, 50.0], bins=3, method="quantile")
    assert bivq["x_bin"].tolist() == [0, 0, 1, -1, 2] and bivq["y_bin"][3] == -1 and bivq["pair_index"][3] == -1

    # 模拟无 cmcrameri 的桌面 QGIS Python（Tier A）
    monkeypatch.setitem(sys.modules, "cmcrameri", None)
    monkeypatch.setitem(sys.modules, "cmcrameri.cm", None)
    for name in ("batlow", "lajolla", "vik", "roma"):
        kind = "diverging" if name in {"vik", "roma"} else "sequential"
        fallback_cmap = get_scientific_cmap(kind, name, reverse=True)
        assert fallback_cmap(0.5) is not None


@pytest.mark.parametrize("simulate_tier_a", [False, True])
def test_v905_cartographic_primitives_and_layout_diagnostics(tmp_path: Path, monkeypatch, simulate_tier_a: bool) -> None:
    """六大制图原语在 Tier B 与模拟 Tier A 下均可渲染，并检测外围白边比例。"""
    import importlib.util
    if any(importlib.util.find_spec(m) is None for m in ("geopandas", "matplotlib", "shapely")):
        pytest.skip("当前解释器缺少基础制图依赖。")

    if simulate_tier_a:
        for pkg in ("cartopy", "cartopy.crs", "cmcrameri", "cmcrameri.cm", "matplotlib_scalebar", "matplotlib_scalebar.scalebar", "adjustText"):
            monkeypatch.setitem(sys.modules, pkg, None)

    import geopandas as gpd
    from shapely.geometry import box

    from gis_agent.integrations.plotting.primitives import (
        add_bivariate_legend,
        add_clean_legend,
        add_graticule_frame,
        add_leader_callouts,
        add_locator_inset,
        add_scalebar_and_north,
        apply_publication_theme,
        attach_marginal_profiles,
        get_scientific_cmap,
    )
    from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure

    cfg = configure_plotting(font_style="sans", svg_editable_text=True)
    import matplotlib
    import matplotlib.pyplot as plt

    assert cfg["font_style"] == "sans" and cfg["svg_editable_text"] is True
    assert matplotlib.rcParams["svg.fonttype"] == "none"

    fonts_before = list(matplotlib.rcParams["font.family"])
    theme = apply_publication_theme("editorial_warm", font_scale=1.0, fig_width=12.0)
    assert list(matplotlib.rcParams["font.family"]) == fonts_before
    assert theme["style"] == "editorial_warm"
    for tier in ("T1", "T2", "T3", "T4"):
        assert theme["fonts"][tier] >= 12 and theme["fonts"][tier] % 2 == 0

    if not simulate_tier_a:
        serif_cfg = configure_plotting(font_style="serif", svg_editable_text=True)
        assert serif_cfg["font_style"] == "serif"
        assert any("Times New Roman" in fam or "SimSun" in fam for fam in serif_cfg["families"]) or not serif_cfg["fonts"]
        configure_plotting(font_style="sans", svg_editable_text=True)
        apply_publication_theme("editorial_warm", font_scale=1.0)

    gdf = gpd.GeoDataFrame(
        {"val": [1.0, 2.0, 3.0, 4.0]},
        geometry=[
            box(500_000, 3_500_000, 505_000, 3_505_000),
            box(505_000, 3_500_000, 510_000, 3_505_000),
            box(500_000, 3_505_000, 505_000, 3_510_000),
            box(505_000, 3_505_000, 510_000, 3_510_000),
        ],
        crs="EPSG:32650",
    )
    fig = plt.figure(figsize=(7.5, 6.2))
    try:
        panels = attach_marginal_profiles(fig, top=True, right=True, ratio=0.20, pad=0.035)
        ax = panels["main"]
        gdf.plot(ax=ax, column="val", cmap=get_scientific_cmap("sequential", "batlow"), edgecolor="#ffffff", linewidth=0.5)
        ax.set_xlim(498_000, 512_000)
        ax.set_ylim(3_498_000, 3_512_000)
        ax.set_aspect("equal")
        add_graticule_frame(ax, crs=gdf.crs, style="ticks_only", dms=True)
        sb_info = add_scalebar_and_north(ax, crs_units="metre", loc="lower right", north_loc="upper right")
        assert sb_info["scale_length_m"] is not None
        inset = add_locator_inset(ax, [0.04, 0.72, 0.22, 0.22], shape="circle")
        gdf.plot(ax=inset, facecolor="#cf597e", edgecolor="#333333")
        add_bivariate_legend(ax, [0.05, 0.06, 0.18, 0.18], "stevens_pinkblue", x_label="X", y_label="Y")
        add_clean_legend(ax, [("区域示例 Region", "#2a5674", 60.0)], show_pct=True, zero_label="零值", nodata_label="缺测", loc="upper left")
        add_leader_callouts(ax, [{"label": "热点站点 Peak", "xy": (502_500, 3_502_500)}], use_adjust_text=not simulate_tier_a)
        panels["top"].bar([502_500, 507_500], [2, 4], width=3000)
        panels["right"].barh([3_502_500, 3_507_500], [3, 1], height=3000)

        out_dir = tmp_path / ("tier_a" if simulate_tier_a else "tier_b")
        res = export_figure(fig, out_dir, formats=("png",), map_panels=(MapPanel("main", ax, "EPSG:32650"),))
        assert res["ok"] and Path(res["preview"]).is_file()
        assert "layout_diagnostics" in res
        ratios = res["layout_diagnostics"]["margin_whitespace_ratio"]
        assert set(ratios) == {"top", "bottom", "left", "right"}
        assert isinstance(res["layout_diagnostics"]["excessive_margin_warning"], bool)
        if cfg["fonts"]:
            assert not any("Glyph" in w for w in res["warnings"])
    finally:
        plt.close(fig)

    if not simulate_tier_a:
        # 故意构造超大外围白边与碎片过小字号图，验证 layout_diagnostics 与 typography 准确告警
        fig_pad = plt.figure(figsize=(16, 10))
        try:
            ax_tiny = fig_pad.add_axes([0.36, 0.36, 0.28, 0.28])
            gdf.plot(ax=ax_tiny)
            for idx_t, pt_sz in enumerate((6.1, 6.5, 7.0, 7.3, 8.1, 9.2)):
                ax_tiny.text(0.1, 0.1 + 0.1 * idx_t, f"small_{idx_t}", fontsize=pt_sz, transform=ax_tiny.transAxes)
            ax_tiny.set_axis_off()
            pad_res = export_figure(fig_pad, tmp_path / "padded", formats=("png", "svg"))
            diag = pad_res["layout_diagnostics"]
            assert diag["excessive_margin_warning"] is True
            assert set(diag["excessive_edges"]) == {"top", "bottom", "left", "right"}
            assert all(val > 0.25 for val in diag["margin_whitespace_ratio"].values())
            typo = diag["typography"]
            assert typo["small_text_warning"] is True
            assert typo["fragmented_font_tiers_warning"] is True
            assert typo["non_even_font_warning"] is True
            svg_content = Path(pad_res["files"]["svg"]).read_text(encoding="utf-8")
            assert "<text" in svg_content
        finally:
            plt.close(fig_pad)

        # 验证 Cartopy GeoAxes 兼容路径（Robinson + circle inset + marginals）
        import cartopy.crs as ccrs
        fig_geo = plt.figure(figsize=(8, 4.5))
        try:
            proj = ccrs.Robinson()
            geo_panels = attach_marginal_profiles(fig_geo, top=True, right=False, ratio=0.18, main_projection=proj)
            ax_geo = geo_panels["main"]
            ax_geo.set_global()
            gpd.GeoDataFrame(geometry=[box(-10, 10, 40, 50)], crs="EPSG:4326").plot(
                ax=ax_geo, transform=ccrs.PlateCarree(), color="#2a5674",
            )
            add_graticule_frame(ax_geo, style="clean_borderless")
            add_scalebar_and_north(ax_geo, crs_units="degree", north=False)
            c_in = add_locator_inset(ax_geo, [0.03, 0.12, 0.22, 0.22], shape="circle", projection=ccrs.Orthographic(10, 30))
            assert hasattr(c_in, "projection")
            geo_res = export_figure(fig_geo, tmp_path / "cartopy_geo", formats=("png",), map_panels=(MapPanel("global", ax_geo, proj.proj4_init),))
            assert geo_res["ok"]
        finally:
            plt.close(fig_geo)


def test_v905_publication_composite_script_offline(tmp_path: Path) -> None:
    """V9.0.5 离线合成出版级复合图参考脚本可通过 run_python_script 运行并产出完整产物。"""
    import importlib.util
    if any(importlib.util.find_spec(m) is None for m in ("geopandas", "matplotlib", "shapely", "pyproj")):
        pytest.skip("当前解释器缺少基础地理依赖。")

    out_dir = tmp_path / "composite_out"
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"output_dir": str(out_dir), "style": "light_geo", "formats": ["png", "svg"]}), encoding="utf-8")
    run = run_python_script(
        Path(sys.executable),
        tmp_path / "logs",
        str(SCRIPTS / "publication_composite.py"),
        [str(cfg)],
    )
    assert run["ok"] and run["returncode"] == 0, run
    res = run["result"]
    assert res["ok"] and Path(res["files"]["png"]).is_file() and Path(res["files"]["svg"]).is_file()
    assert res["layout_diagnostics"]["excessive_margin_warning"] is False
    typo = res["layout_diagnostics"]["typography"]
    assert typo["small_text_warning"] is False
    assert typo["non_even_font_warning"] is False
    assert typo["fragmented_font_tiers_warning"] is False
    hyg = res["layout_diagnostics"]["hygiene"]
    assert hyg["subtitle_detected_warning"] is False
    assert hyg["callout_box_warning"] is False
    assert hyg["duplicate_axis_ticks_warning"] is False
    assert hyg["clipped_text_warning"] is False
    assert hyg["frame_overflow_warning"] is False
    svg_txt = Path(res["files"]["svg"]).read_text(encoding="utf-8")
    assert "<text" in svg_txt and "catchments_bivariate" in svg_txt
    manifest = json.loads(Path(res["manifest"]).read_text(encoding="utf-8"))
    assert "layout_diagnostics" in manifest and res["warnings"] == []


def test_v9052_colorbar_connectors_quiet_corner_and_hygiene(tmp_path: Path) -> None:
    """V9.0.5.2 新增低饱和色带、连续色带、缩放连线、空白角落选址与 4 项自动化制图卫生告警测试。"""
    import importlib.util
    if any(importlib.util.find_spec(m) is None for m in ("geopandas", "matplotlib", "shapely")):
        pytest.skip("当前解释器缺少基础制图依赖。")

    import geopandas as gpd
    from matplotlib.colors import PowerNorm
    import numpy as np
    from shapely.geometry import Point, box

    from gis_agent.integrations.plotting import (
        GEO_COLORS,
        MapPanel,
        add_continuous_colorbar,
        add_graticule_frame,
        add_leader_callouts,
        add_locator_inset,
        add_scalebar_and_north,
        apply_publication_theme,
        configure_plotting,
        export_figure,
        find_quiet_corner,
        get_scientific_cmap,
        list_palettes,
        rank_quiet_corners,
    )

    pals = list_palettes()
    for name in ("nordic_snow", "slate_teal", "muted_ochre", "sage_forest"):
        assert name in pals["sequential"]
        cmap = get_scientific_cmap("sequential", name)
        assert cmap(0.5) is not None
    for tok in ("marker_low", "marker_mid", "marker_high", "marker_extreme"):
        assert tok in GEO_COLORS

    configure_plotting(font_style="sans", svg_editable_text=True)
    import matplotlib.pyplot as plt
    apply_publication_theme("light_geo", fig_width=8.5)

    # 1. 验证 clean 图：连续色带 + 圆形区位缩放连线 + 空白选址，4 项 hygiene 均为 False
    fig = plt.figure(figsize=(8.5, 6.2))
    try:
        ax = fig.add_axes([0.10, 0.20, 0.84, 0.72])
        grid = np.linspace(0.0, 120.0, 40 * 40).reshape(40, 40)
        norm = PowerNorm(gamma=0.45, vmin=0.0, vmax=120.0)
        im = ax.imshow(grid, extent=(0, 100, 0, 100), origin="upper", cmap=get_scientific_cmap("sequential", "nordic_snow"), norm=norm)

        # 构造左下空闲、右上拥挤的数据分布，测试 rank_quiet_corners / find_quiet_corner
        mask = np.zeros((100, 100), dtype=bool)
        mask[0:60, 40:100] = True  # upper-right occupied (row 0 = top)
        best_r = find_quiet_corner(ax, raster_mask=mask, raster_extent=(0, 100, 0, 100))
        assert best_r in {"lower left", "lower right"}

        pts = gpd.GeoDataFrame(geometry=[Point(x, y) for x in np.linspace(55, 95, 25) for y in np.linspace(55, 95, 10)], crs="EPSG:4326")
        ranked_v = rank_quiet_corners(ax, pts, exclude=("lower right",))
        assert ranked_v[0][0] in {"lower left", "upper left"} and all(c != "lower right" for c, _ in ranked_v)

        add_graticule_frame(ax, crs="EPSG:4326", style="ticks_only", dms=True)
        add_scalebar_and_north(ax, crs_units="degree", loc="lower right", north_loc="upper right", use_matplotlib_scalebar=False)
        inset = add_locator_inset(ax, [0.04, 0.66, 0.24, 0.28], shape="circle")
        inset.set_xlim(-85, -35)
        inset.set_ylim(-55, 12)

        cb = add_continuous_colorbar(
            fig, im, bounds=[0.10, 0.05, 0.78, 0.11], orientation="horizontal",
            label="Accumulation (in)", zero_label="0", nodata_label="NoData",
        )
        assert len(cb["ticks"]) >= 3
        add_continuous_colorbar(
            fig, im, bounds=[0.88, 0.22, 0.10, 0.65], orientation="vertical", label="Rate",
        )
        add_leader_callouts(ax, [{"label": "Station A", "xy": (70, 70), "xytext": (45, 78)}], use_adjust_text=False)

        clean_res = export_figure(fig, tmp_path / "clean_v9052", formats=("png", "svg"), map_panels=(MapPanel("main", ax, "EPSG:4326"),))
        hyg = clean_res["layout_diagnostics"]["hygiene"]
        assert hyg["subtitle_detected_warning"] is False
        assert hyg["callout_box_warning"] is False
        assert hyg["duplicate_axis_ticks_warning"] is False
        assert hyg["clipped_text_warning"] is False
        assert hyg["frame_overflow_warning"] is False
        svg_txt = Path(clean_res["files"]["svg"]).read_text(encoding="utf-8")
        assert "locator_inset" in svg_txt and "colorbar" in svg_txt
    finally:
        plt.close(fig)

    # 2. 验证 Cartopy GeoAxes 与矩形/圆形定位小图路径
    import cartopy.crs as ccrs
    fig_g = plt.figure(figsize=(8.0, 5.2))
    try:
        ax_m = fig_g.add_axes([0.10, 0.12, 0.58, 0.80], projection=ccrs.Mercator())
        ax_m.set_extent([-67, -59, -14, -7], crs=ccrs.PlateCarree())
        gpd.GeoDataFrame(geometry=[box(-65, -13, -61, -9)], crs="EPSG:4326").plot(ax=ax_m, transform=ccrs.PlateCarree())
        c_in = add_locator_inset(
            ax_m, [0.03, 0.66, 0.24, 0.26], shape="circle",
            projection=ccrs.EqualEarth(central_longitude=-60),
        )
        c_in.set_extent([-85, -34, -56, 13], crs=ccrs.PlateCarree())
        ext_in = add_locator_inset(fig_g, [0.74, 0.56, 0.20, 0.30], shape="rect")
        gpd.GeoDataFrame(geometry=[box(-85, -55, -35, 12)], crs="EPSG:4326").plot(ax=ext_in)
        g_res = export_figure(fig_g, tmp_path / "cartopy_conn", formats=("png", "svg"), map_panels=(MapPanel("main", ax_m, "EPSG:3857"),))
        assert g_res["ok"] and "locator_inset" in Path(g_res["files"]["svg"]).read_text(encoding="utf-8")
    finally:
        plt.close(fig_g)

    # 3. 验证 4 项反面卫生告警均可准确命中
    fig_bad = plt.figure(figsize=(8.0, 6.0))
    try:
        ax_b = fig_bad.add_axes([0.14, 0.14, 0.78, 0.70])
        gpd.GeoDataFrame(geometry=[box(3_600_000, 8_500_000, 4_300_000, 9_100_000)], crs="EPSG:5880").plot(ax=ax_b)
        ax_b.set_xlim(3_600_000, 4_300_000)
        ax_b.set_ylim(8_500_000, 9_100_000)
        # 堆叠副标题
        fig_bad.text(0.08, 0.94, "Main Snowfall Title", fontsize=16, fontweight="bold")
        fig_bad.text(0.08, 0.89, "A smaller lighter subtitle repeating the title", fontsize=12, color="#666666")
        # 实心白底贴片标注
        ax_b.annotate(
            "Winter Park, CO", xy=(4_000_000, 8_800_000), xytext=(4_100_000, 8_900_000),
            bbox=dict(boxstyle="round", facecolor="#ffffff", edgecolor="#666666", alpha=0.95),
            arrowprops=dict(arrowstyle="-"),
        )
        # 手写 DMS 标签覆盖默认 1e6 米制刻度
        ax_b.text(-0.02, 8_800_000, "10°S", transform=ax_b.get_yaxis_transform(), ha="right")
        # 出界被裁切文字
        fig_bad.text(1.03, 0.50, "Clipped Overflow Label", fontsize=12)

        bad_res = export_figure(fig_bad, tmp_path / "bad_v9052", formats=("png",), map_panels=(MapPanel("main", ax_b, "EPSG:5880"),))
        bad_hyg = bad_res["layout_diagnostics"]["hygiene"]
        assert bad_hyg["subtitle_detected_warning"] is True
        assert bad_hyg["callout_box_warning"] is True
        assert bad_hyg["duplicate_axis_ticks_warning"] is True
        assert bad_hyg["clipped_text_warning"] is True
    finally:
        plt.close(fig_bad)


def test_v9053_fonts_compass_perceptual_norm_and_frame_overflow(tmp_path: Path) -> None:
    """V9.0.5.3 宋体/楷体/仿宋默认字体、罗盘星指北针/高端比例尺、偏态感知拉伸、连线高层级与边框溢界自检测试。"""
    import importlib.util
    if any(importlib.util.find_spec(m) is None for m in ("geopandas", "matplotlib", "shapely")):
        pytest.skip("当前解释器缺少基础制图依赖。")

    import geopandas as gpd
    from matplotlib.colors import Normalize, PowerNorm
    import numpy as np
    from shapely.geometry import box

    from gis_agent.integrations.plotting import (
        MapPanel,
        add_graticule_frame,
        add_locator_inset,
        add_scalebar_and_north,
        apply_publication_theme,
        build_perceptual_norm,
        configure_plotting,
        export_figure,
        get_scientific_cmap,
    )

    # 1. 随仓捆绑开源字体文件检查，且 serif/kaiti 栈绝不混入 Microsoft YaHei
    fonts_dir = ROOT / "gis_agent/integrations/plotting/fonts"
    for fname in ("SourceSerif4-Regular.ttf", "SourceSerif4-Bold.ttf", "SourceSerif4-It.ttf", "LXGWWenKaiLite-Regular.ttf", "LXGWWenKaiLite-Medium.ttf"):
        assert (fonts_dir / fname).is_file(), fname

    default_cfg = configure_plotting()
    assert default_cfg["font_style"] == "serif"
    assert "Source Serif 4" in default_cfg["families"] and "LXGW WenKai Lite" in default_cfg["families"]
    assert "Microsoft YaHei" not in default_cfg["families"]

    import matplotlib.pyplot as plt
    for style_name in ("serif", "kaiti", "fangsong", "sans"):
        cfg = configure_plotting(font_style=style_name, svg_editable_text=True)
        assert cfg["font_style"] == style_name
        if style_name in {"serif", "kaiti", "fangsong"}:
            assert "Microsoft YaHei" not in cfg["families"]
            assert "LXGW WenKai Lite" in cfg["families"]
        apply_publication_theme("light_geo", fig_width=8.5)
        fig_t = plt.figure(figsize=(8.5, 5.5))
        try:
            ax_t = fig_t.add_axes([0.12, 0.14, 0.78, 0.76])
            gpd.GeoDataFrame(geometry=[box(0, 0, 100, 80)], crs="EPSG:32650").plot(ax=ax_t, color="#dceae8")
            ax_t.set_xlim(0, 100)
            ax_t.set_ylim(0, 80)
            ax_t.set_title("OpenGIS-Agent 2024–2025 冬季累积降雪量 ≥60 66°W 55,164 km²", fontsize=16, fontweight="bold")
            res_t = export_figure(fig_t, tmp_path / f"font_{style_name}", formats=("png",), map_panels=(MapPanel("main", ax_t, "EPSG:32650"),))
            assert not any("Glyph" in w for w in res_t["warnings"]), (style_name, res_t["warnings"])
        finally:
            plt.close(fig_t)

    # 2. 偏态连续场自适应 PowerNorm 与对称/均匀场退化 Normalize
    skewed = np.array([0.0, 0.0, 1.0, 2.0, 5.0, 12.0, 30.0, 80.0, 600.0])
    p_norm = build_perceptual_norm(skewed)
    assert isinstance(p_norm, PowerNorm) and 0.28 <= float(p_norm.gamma) <= 0.85
    even_vals = np.array([10.0, 50.0, 90.0])
    u_norm = build_perceptual_norm(even_vals, positive_only=False)
    assert type(u_norm) is Normalize

    # 3. 高工艺罗盘星/细针/斜角指北针 + 阶梯/刻度比例尺 + 独立圆形/矩形定位小图全组合，零 frame_overflow_warning
    configure_plotting(font_style="kaiti", svg_editable_text=True)
    apply_publication_theme("light_geo", fig_width=8.6)
    for idx_s, (s_st, n_st, s_loc, n_loc) in enumerate((
        ("cartographic", "compass_star", "lower right", "upper left"),
        ("ticked", "sleek_needle", "lower center", "upper right"),
        ("cartographic", "chevron", "lower left", "upper left"),
    )):
        fig_c = plt.figure(figsize=(8.6, 5.6))
        try:
            ax_c = fig_c.add_axes([0.10, 0.14, 0.56, 0.78])
            arr = np.linspace(0.0, 600.0, 20 * 20).reshape(20, 20)
            ax_c.imshow(arr, extent=(0, 1_500_000, 0, 1_000_000), cmap=get_scientific_cmap("sequential", "nordic_snow"), norm=p_norm)
            ax_c.set_xlim(0, 1_500_000)
            ax_c.set_ylim(0, 1_000_000)
            ax_c.set_aspect("equal")
            add_graticule_frame(ax_c, crs="EPSG:32650", style="ticks_only", dms=True)
            info = add_scalebar_and_north(
                ax_c, crs_units="metre", loc=s_loc, north_loc=n_loc,
                scale_style=s_st, north_style=n_st,
            )
            assert info["scale_style"] == s_st and info["north_style"] == n_st
            assert len(info["north_artists"]) >= 3

            ax_in = add_locator_inset(fig_c, [0.72, 0.56, 0.22, 0.30], shape="circle", zorder=10)
            gpd.GeoDataFrame(geometry=[box(-80, -50, -35, 10)], crs="EPSG:4326").plot(ax=ax_in)
            ax_in.set_xlim(-82, -33)
            ax_in.set_ylim(-52, 12)

            res_c = export_figure(fig_c, tmp_path / f"craft_{idx_s}", formats=("png", "svg"), map_panels=(MapPanel("main", ax_c, "EPSG:32650"),))
            assert res_c["layout_diagnostics"]["hygiene"]["frame_overflow_warning"] is False, res_c["layout_diagnostics"]["hygiene"]
            assert res_c["layout_diagnostics"]["hygiene"]["clipped_text_warning"] is False
        finally:
            plt.close(fig_c)

    # 4. 地图内文字撞穿主图黑边框时，frame_overflow_warning 精准触发
    fig_ov = plt.figure(figsize=(8.0, 5.5))
    try:
        ax_o = fig_ov.add_axes([0.10, 0.14, 0.80, 0.72])
        gpd.GeoDataFrame(geometry=[box(0, 0, 100, 80)], crs="EPSG:32650").plot(ax=ax_o)
        ax_o.set_xlim(0, 100)
        ax_o.set_ylim(0, 80)
        ax_o.text(0.05, 0.992, "N", transform=ax_o.transAxes, ha="center", va="bottom", fontsize=12, fontweight="bold")
        ov_res = export_figure(fig_ov, tmp_path / "overflow_case", formats=("png",), map_panels=(MapPanel("main", ax_o, "EPSG:32650"),))
        assert ov_res["layout_diagnostics"]["hygiene"]["frame_overflow_warning"] is True
        assert "N" in ov_res["layout_diagnostics"]["hygiene"]["frame_overflow_texts"]
    finally:
        plt.close(fig_ov)


def test_v9055_integer_graticules_zero_anchored_legend_and_font_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """V9.0.5.5 投影整数经纬求解、零值融合连续色带、居中线框图例与 font_style 优先级测试。"""
    import importlib.util
    if any(importlib.util.find_spec(m) is None for m in ("geopandas", "matplotlib", "pyproj", "shapely")):
        pytest.skip("当前解释器缺少基础制图依赖。")

    from matplotlib import colors as mcolors
    import numpy as np

    from gis_agent.config import configured_fonts
    from gis_agent.integrations.plotting import (
        GEO_COLORS,
        MapPanel,
        add_clean_legend,
        add_continuous_colorbar,
        add_graticule_frame,
        apply_publication_theme,
        configure_plotting,
        export_figure,
        get_scientific_cmap,
    )

    # 1. configured_fonts 默认不强塞 msyh.ttc；显式 font_style 优先于 GIS_AGENT_FONT_FILES
    fonts_dir = ROOT / "gis_agent/integrations/plotting/fonts"
    wk_font = (fonts_dir / "LXGWWenKaiLite-Regular.ttf").resolve()
    monkeypatch.delenv("GIS_AGENT_FONT_FILES", raising=False)
    assert configured_fonts(ROOT) == ()

    monkeypatch.setenv("GIS_AGENT_FONT_FILES", str(wk_font))
    env_cfg = configure_plotting()
    assert env_cfg["fonts"] == [str(wk_font)]

    explicit_cfg = configure_plotting(font_style="serif", svg_editable_text=True)
    assert "Source Serif 4" in explicit_cfg["families"]
    assert "Microsoft YaHei" not in explicit_cfg["families"]

    import matplotlib.pyplot as plt
    apply_publication_theme("light_geo", fig_width=9.0)

    # 2. EPSG:5070 CONUS 默认整数经纬刻度（无分秒）
    fig_us, ax_us = plt.subplots(figsize=(9.0, 5.5))
    try:
        ax_us.set_xlim(-2_450_000.0, 2_400_000.0)
        ax_us.set_ylim(-450_000.0, 3_520_000.0)
        ax_us.set_aspect("equal")
        add_graticule_frame(ax_us, crs="EPSG:5070", style="ticks_only", dms=True)
        fig_us.canvas.draw()
        x_labs = [t.get_text() for t in ax_us.get_xticklabels() if t.get_text()]
        y_labs = [t.get_text() for t in ax_us.get_yticklabels() if t.get_text()]
        assert len(x_labs) >= 3 and len(y_labs) >= 4
        assert all("°" in lab and "'" not in lab and '"' not in lab for lab in x_labs + y_labs), (x_labs, y_labs)
    finally:
        plt.close(fig_us)

    # 3. EPSG:5880 Rondônia 指定 2° 整数经纬 + zero_anchored 连续色带 + 居中线框 Legend
    cmap_za = get_scientific_cmap("sequential", "nordic_snow", zero_anchored=True)
    assert mcolors.to_hex(cmap_za(0.0)).lower() == GEO_COLORS["zero_neutral"].lower()
    assert mcolors.to_hex(cmap_za(1.0)).lower() == "#0c2338"

    fig_br = plt.figure(figsize=(9.0, 6.2))
    try:
        ax_br = fig_br.add_axes([0.08, 0.14, 0.62, 0.78])
        grid = np.linspace(0.0, 800.0, 30 * 30).reshape(30, 30)
        im = ax_br.imshow(
            grid,
            extent=(3_500_000.0, 4_470_000.0, 8_350_000.0, 9_230_000.0),
            origin="upper",
            cmap=cmap_za,
        )
        ax_br.set_xlim(3_500_000.0, 4_470_000.0)
        ax_br.set_ylim(8_350_000.0, 9_230_000.0)
        ax_br.set_aspect("equal")
        add_graticule_frame(ax_br, crs="EPSG:5880", style="ticks_only", dms=True, step_deg=(2, 2))
        add_continuous_colorbar(
            fig_br, im, bounds=[0.74, 0.58, 0.22, 0.16], orientation="horizontal",
            label="Value (in)", ticks=[0, 200, 500, 800], zero_label=None,
        )
        ax_leg = fig_br.add_axes([0.74, 0.14, 0.22, 0.34])
        ax_leg.set_axis_off()
        leg = add_clean_legend(
            ax_leg,
            [
                {"label": "Protected forest", "color": "#6f9b6b", "kind": "patch"},
                {"label": "Deforested area", "color": "#cf8a3d", "kind": "patch"},
                {"label": "Roads", "color": "#33383d", "kind": "line"},
            ],
            title="Legend", loc="center", frameon=True, frame_alpha=1.0, title_align="center",
        )
        assert leg is not None
        assert leg.get_title().get_fontweight() in {"bold", 700}
        assert leg._legend_box.align == "center"
        assert mcolors.to_hex(leg.get_frame().get_facecolor()).lower() == "#faf9f7"
        assert mcolors.to_hex(leg.get_frame().get_edgecolor()).lower() == "#b8b4ac"

        fig_br.canvas.draw()
        bx_labs = {t.get_text() for t in ax_br.get_xticklabels() if t.get_text()}
        by_labs = {t.get_text() for t in ax_br.get_yticklabels() if t.get_text()}
        assert {"66°W", "64°W", "62°W", "60°W"}.issubset(bx_labs), bx_labs
        assert {"14°S", "12°S", "10°S", "8°S"}.issubset(by_labs), by_labs

        res = export_figure(
            fig_br, tmp_path / "v9055_out", formats=("png", "svg"),
            map_panels=(MapPanel("rondonia", ax_br, "EPSG:5880"),),
        )
        hyg = res["layout_diagnostics"]["hygiene"]
        assert hyg["duplicate_axis_ticks_warning"] is False
        assert hyg["clipped_text_warning"] is False
        assert hyg["frame_overflow_warning"] is False
        assert res["warnings"] == []
    finally:
        plt.close(fig_br)


def test_v906_api_doc_compact_and_flow_primitives(tmp_path: Path) -> None:
    """V9.0.6 精简 <5KB API 文档及多点-线-流（无向/有向弧线 + 嵌套组合图例）原语测试。"""
    import importlib.util
    if any(importlib.util.find_spec(m) is None for m in ("geopandas", "matplotlib", "pyproj", "shapely")):
        pytest.skip("当前解释器缺少基础制图依赖。")

    api_doc = ROOT / "gis_agent/skills/gis-cartography/references/api.md"
    raw_bytes = api_doc.read_bytes()
    assert len(raw_bytes) < 5120, f"api.md 应小于 5KB，实际 {len(raw_bytes)} B"
    head_text = api_doc.read_text(encoding="utf-8")[:3000]
    for sym in ("configure_plotting", "export_figure", "add_scalebar_and_north", "add_flow_arcs", "add_size_legend"):
        assert sym in head_text, sym

    import geopandas as gpd
    import matplotlib.pyplot as plt
    from shapely.geometry import LineString, Point, box

    from gis_agent.integrations.plotting import (
        GEO_COLORS,
        MapPanel,
        add_flow_arcs,
        add_graticule_frame,
        add_scalebar_and_north,
        add_size_legend,
        apply_publication_theme,
        configure_plotting,
        export_figure,
    )

    configure_plotting(font_style="serif", svg_editable_text=True)
    apply_publication_theme("light_geo", fig_width=8.6)

    # 1. 无向多点-线-流（省域衬底 + 升序弧线 + 枢纽散点 + 组合尺寸线宽图例）
    poly_gdf = gpd.GeoDataFrame(geometry=[box(200_000, 3_400_000, 700_000, 3_800_000)], crs="EPSG:32650")
    od_rows = [
        {"x0": 300_000, "y0": 3_500_000, "x1": 600_000, "y1": 3_700_000, "flow": 500.0},
        {"x0": 280_000, "y0": 3_680_000, "x1": 580_000, "y1": 3_520_000, "flow": 1800.0},
        {"x0": 350_000, "y0": 3_550_000, "x1": 520_000, "y1": 3_620_000, "flow": 6400.0},
    ]
    hubs = gpd.GeoDataFrame(
        {"val": [40.0, 120.0, 260.0]},
        geometry=[Point(300_000, 3_500_000), Point(600_000, 3_700_000), Point(520_000, 3_620_000)],
        crs="EPSG:32650",
    )

    fig = plt.figure(figsize=(8.6, 5.8))
    try:
        ax = fig.add_axes([0.08, 0.14, 0.62, 0.76])
        ax.set_facecolor(GEO_COLORS["ocean_soft"])
        poly_gdf.plot(ax=ax, facecolor="#f7f6f4", edgecolor=GEO_COLORS["border_study"], linewidth=1.0, zorder=8)
        flow_res = add_flow_arcs(ax, od_rows, value_col="flow", directed=False, n_classes=3, zorder=5)
        assert flow_res["count"] == 3 and len(flow_res["legend_items"]) == 3
        assert flow_res["linewidths"] == sorted(flow_res["linewidths"])
        hubs.plot(ax=ax, markersize=hubs["val"], color="#d96f32", edgecolor="#ffffff", linewidth=0.8, zorder=7)
        ax.set_xlim(180_000, 720_000)
        ax.set_ylim(3_380_000, 3_820_000)
        ax.set_aspect("equal")
        ax.set_title("Flow & Hub Network Test", fontsize=16, fontweight="bold")
        add_graticule_frame(ax, crs="EPSG:32650", style="ticks_only", dms=True)
        add_scalebar_and_north(ax, crs_units="metre", loc="lower right", north_loc="upper left")

        ax_leg = fig.add_axes([0.72, 0.16, 0.25, 0.72])
        leg_info = add_size_legend(
            ax_leg,
            [("Hub High (260)", 260), ("Hub Mid (120)", 120), ("Hub Low (40)", 40)],
            layout="nested",
            title="Hub Centrality",
            line_items=flow_res["legend_items"],
            line_title="Flow Strength",
        )
        assert leg_info["layout"] == "nested"

        out = export_figure(fig, tmp_path / "flow_undir", formats=("png", "svg"), map_panels=(MapPanel("main", ax, "EPSG:32650"),))
        assert out["warnings"] == []
        typo = out["layout_diagnostics"]["typography"]
        hyg = out["layout_diagnostics"]["hygiene"]
        assert not typo["small_text_warning"] and not typo["non_even_font_warning"]
        assert not any(v for k, v in hyg.items() if k.endswith("_warning")), hyg
        svg_txt = Path(out["files"]["svg"]).read_text(encoding="utf-8")
        assert "flow_arcs" in svg_txt and "size_legend" in svg_txt
    finally:
        plt.close(fig)

    # 2. 有向对称 A<->B 弧线 + 垂直双标题气泡+线宽组合图例
    fig2 = plt.figure(figsize=(8.6, 5.6))
    try:
        ax2 = fig2.add_axes([0.08, 0.14, 0.60, 0.76])
        gdf_dir = gpd.GeoDataFrame(
            {"val": [100.0, 400.0]},
            geometry=[LineString([(300_000, 3_500_000), (600_000, 3_700_000)]), LineString([(600_000, 3_700_000), (300_000, 3_500_000)])],
            crs="EPSG:32650",
        )
        poly_gdf.plot(ax=ax2, facecolor="#f7f6f4", edgecolor="#333333", zorder=2)
        dir_res = add_flow_arcs(ax2, gdf_dir, value_col="val", directed=True, symmetric=True, n_classes=2, zorder=5)
        assert dir_res["count"] == 2 and len(dir_res["artists"]) >= 3
        ax_vleg = fig2.add_axes([0.71, 0.24, 0.26, 0.56])
        ax_vleg.set_axis_off()
        vleg_res = add_size_legend(
            ax_vleg,
            [("400", 180), ("100", 60)],
            layout="vertical",
            title="Hub Outflow",
            line_items=dir_res["legend_items"],
            line_title="Arc Magnitude",
        )
        assert vleg_res["layout"] == "vertical" and vleg_res["scale_factor"] == 1.0
        v_texts = [t.get_text() for t in ax_vleg.texts]
        assert "Hub Outflow" in v_texts and "Arc Magnitude" in v_texts
        out2 = export_figure(fig2, tmp_path / "flow_dir", formats=("png", "svg"), map_panels=(MapPanel("main", ax2, "EPSG:32650"),))
        assert out2["warnings"] == []
        assert not any(v for k, v in out2["layout_diagnostics"]["hygiene"].items() if k.endswith("_warning"))
        assert not out2["layout_diagnostics"]["typography"]["non_even_font_warning"]
    finally:
        plt.close(fig2)


def test_v906_network_four_piece_suite() -> None:
    """V9.0.6 零新依赖网络分析四件套：Trimmed-TIN 服务区面、MILP/Huff 选址、障碍物+Top-K、边状态转弯图。"""
    import importlib.util
    if any(importlib.util.find_spec(m) is None for m in ("geopandas", "networkx", "numpy", "scipy", "shapely", "matplotlib")):
        pytest.skip("当前解释器缺少网络分析依赖。")

    net_scripts = str(SKILLS / "gis-vector-and-network/scripts")
    if net_scripts not in sys.path:
        sys.path.insert(0, net_scripts)

    import geopandas as gpd
    import networkx as nx
    import numpy as np
    from shapely.geometry import LineString, Point, box

    from network_access import build_primal
    from network_advanced import apply_barriers, build_turn_graph, closest_k_facilities, turn_shortest_path
    from network_location import huff_market_share, locate, locate_milp
    from service_area_polygon import (
        clustered_concave_service_areas,
        corridor_service_areas,
        densify_reachable_samples,
        trimmed_tin_service_areas,
    )

    # 1. Trimmed-TIN 服务区面：棋盘格市区填实 + 远郊单线保留 + 无路湖泊/孤岛剔除 + 单调性
    lines = []
    # Urban 5x5 grid in [0, 800] step 200 (cost = length / 100 min -> 2 min per 200m block)
    for y in range(0, 1000, 200):
        for x in range(0, 800, 200):
            lines.append(LineString([(x, y), (x + 200, y)]))
    for x in range(0, 1000, 200):
        for y in range(0, 800, 200):
            lines.append(LineString([(x, y), (x, y + 200)]))
    # Rural highway spur out to x=1600
    lines.extend([LineString([(800, 400), (1200, 400)]), LineString([(1200, 400), (1600, 400)])])
    # Disconnected island across wide roadless lake [1600..3200]
    lines.append(LineString([(3200, 200), (3400, 200)]))

    road_gdf = gpd.GeoDataFrame(
        {
            "rid": [f"r{i}" for i in range(len(lines))],
            "direction": ["both"] * len(lines),
            "cost": [g.length / 100.0 for g in lines],
        },
        geometry=lines,
        crs="EPSG:32650",
    )
    G = build_primal(road_gdf, road_key="rid", direction="direction", cost="cost")
    origin = ("xy", 400.0, 400.0, ())
    dists = nx.single_source_dijkstra_path_length(G, origin, cutoff=12.0, weight="cost")
    pts_xy, times, r_lines = densify_reachable_samples(G, dists, [4.0, 10.0], max_spacing_m=150.0)

    tin_rings = trimmed_tin_service_areas(pts_xy, times, [4.0, 10.0], trim_m=220.0, reachable_lines=r_lines, corridor_floor_m=30.0, mode="rings", crs=road_gdf.crs)
    tin_disks = trimmed_tin_service_areas(pts_xy, times, [4.0, 10.0], trim_m=220.0, reachable_lines=r_lines, corridor_floor_m=30.0, mode="disks", crs=road_gdf.crs)
    assert len(tin_rings) == 2 and len(tin_disks) == 2
    disk4, disk10 = tin_disks.geometry.iloc[0], tin_disks.geometry.iloc[1]
    assert disk10.area > disk4.area
    assert abs((tin_rings["area_m2"].sum()) - disk10.area) < 1e-3
    # 城市街区内部无路空地 [200..400, 200..400] 自动填实
    urban_block = box(220, 220, 380, 380)
    assert disk4.intersection(urban_block).area > 0.9 * urban_block.area
    # 远郊干道末端在 10min 处被走廊保底留存 (from 800,400 is dist 4; cutoff 10 reaches x=1400)
    assert disk10.intersects(Point(1300, 400))
    # 跨湖空白与对岸孤岛被 trim_m 准确裁掉，绝不跨湖虚胖
    assert not disk10.intersects(Point(2400, 400))
    assert not disk10.intersects(Point(3300, 200))

    corr = corridor_service_areas(r_lines, [4.0, 10.0], corridor_m=50.0, mode="rings", crs=road_gdf.crs)
    conc = clustered_concave_service_areas(pts_xy, times, [4.0, 10.0], cluster_eps_m=300.0, reachable_lines=r_lines, mode="disks", crs=road_gdf.crs)
    assert len(corr) == 2 and len(conc) == 2 and conc["area_m2"].iloc[1] > conc["area_m2"].iloc[0]

    # 2. MILP 位置分配与 Huff 引力捕获
    small_costs = [[1.0, 8.0, 15.0], [9.0, 2.0, 10.0], [14.0, 9.0, 3.0], [2.0, 7.0, 12.0]]
    small_w = [2.0, 3.0, 4.0, 1.0]
    for obj_name in ("p_median", "p_center", "maximum_coverage"):
        kw = {"threshold": 4.0} if obj_name == "maximum_coverage" else {}
        ref = locate(small_costs, small_w, 2, obj_name, solver="enumerate", **kw)
        milp_res = locate_milp(small_costs, small_w, p=2, objective=obj_name, **kw)
        assert abs(ref["value"] - milp_res["value"]) < 1e-6, (obj_name, ref, milp_res)

    lscp = locate_milp(small_costs, small_w, objective="minimum_facilities", threshold=3.5)
    assert lscp["sites"] == [0, 1, 2] and lscp["value"] == 3.0

    cap_res = locate_milp([[1.0, 10.0], [1.0, 10.0], [1.0, 2.0]], [5.0, 5.0, 5.0], p=2, objective="p_median", capacities=[8.0, 10.0], required_sites=[1])
    assert cap_res["sites"] == [0, 1] and cap_res["value"] > 17.0

    # 大规模 C(30, 5)=142,506 自动路由 HiGHS MILP 秒解
    rng = np.random.default_rng(7)
    big_costs = rng.uniform(1.0, 50.0, size=(50, 30)).tolist()
    big_w = rng.uniform(1.0, 10.0, size=50).tolist()
    big_res = locate(big_costs, big_w, 5, objective="p_median", solver="auto")
    assert len(big_res["sites"]) == 5 and big_res["solver"] == "milp"

    huff = huff_market_share([[1.0, 2.0], [1.0, None]], [4.0, 4.0], beta=2.0, demand_weights=[10.0, 5.0])
    assert abs(huff["probabilities"][0][0] - 0.8) < 1e-9 and huff["probabilities"][1] == [1.0, 0.0]

    # 3. 障碍物（封路点 + 按交叠长度缩放降速区）与 Top-K 最近设施
    b_res = apply_barriers(
        G,
        point_barriers=[Point(200, 400)],  # block direct west exit from (400,400)
        polygon_barriers=[{"geometry": box(590, 380, 810, 420), "mode": "scaled_cost", "factor": 3.0}],
    )
    assert G.has_edge(("xy", 400.0, 400.0, ()), ("xy", 200.0, 400.0, ()), key=("r8", "b")) or b_res["removed_edges"] >= 2
    assert b_res["scaled_edges"] >= 1 and b_res["graph"].number_of_edges() < G.number_of_edges()

    topk = closest_k_facilities(G, {"d": origin}, {"f1": ("xy", 600.0, 400.0, ()), "f2": ("xy", 800.0, 400.0, ()), "f3": ("xy", 0.0, 0.0, ())}, k=3)
    assert [row["facility_id"] for row in topk[0]["facilities"]] == ["f1", "f2", "f3"]
    assert [row["cost"] for row in topk[0]["facilities"]] == [2.0, 4.0, 8.0]

    # 4. 边状态转弯图：禁左转绕行、禁掉头与精确转弯延误累加
    # Square loop + center chord: A(0,0)->B(10,0)->C(10,10)->D(0,10)->A(0,0), try going E(-10,0)->A(0,0)->D(0,10) (left turn)
    t_lines = [
        ("in_road", LineString([(-10, 0), (0, 0)]), 10.0),
        ("west_up", LineString([(0, 0), (0, 10)]), 10.0),
        ("bottom", LineString([(0, 0), (10, 0)]), 10.0),
        ("east_up", LineString([(10, 0), (10, 10)]), 10.0),
        ("top", LineString([(10, 10), (0, 10)]), 10.0),
    ]
    tg_df = gpd.GeoDataFrame(
        {"rid": [x[0] for x in t_lines], "direction": ["both"] * len(t_lines), "cost": [x[2] for x in t_lines]},
        geometry=[x[1] for x in t_lines],
        crs="EPSG:32650",
    )
    G_turn = build_primal(tg_df, road_key="rid", direction="direction", cost="cost")
    tg_ban_left = build_turn_graph(G_turn, weight="cost", forbidden_turns=[("in_road", "west_up")], forbid_uturns=True, straight_penalty=1.0, left_penalty=2.0)
    res_detour = turn_shortest_path(tg_ban_left, ("xy", -10.0, 0.0, ()), ("xy", 0.0, 10.0, ()), weight="cost")
    assert res_detour["ok"] and res_detour["road_ids"] == ["in_road", "bottom", "east_up", "top"]
    # travel_cost = 40.0; turns: 1 straight (in->bottom) + 2 lefts (bottom->east_up, east_up->top) = 1 + 4 = 5.0
    assert abs(res_detour["travel_cost"] - 40.0) < 1e-9 and abs(res_detour["turn_penalty_total"] - 5.0) < 1e-9 and abs(res_detour["cost"] - 45.0) < 1e-9

    # Standalone dead-end turnaround check when forbid_uturns=True vs False
    dead = gpd.GeoDataFrame(
        {"rid": ["stem", "spur"], "direction": ["both", "both"], "cost": [5.0, 5.0]},
        geometry=[LineString([(0, 0), (10, 0)]), LineString([(10, 0), (20, 0)])],
        crs="EPSG:32650",
    )
    G_dead = build_primal(dead, road_key="rid", direction="direction", cost="cost")
    tg_dead = build_turn_graph(G_dead, weight="cost", forbid_uturns=True, allow_deadend_uturns=True, uturn_penalty=3.0)
    # Direct path is just stem; check turning state around dead-end edge works without error
    assert ("edge", ("xy", 10.0, 0.0, ()), ("xy", 20.0, 0.0, ()), ("spur", "f")) in tg_dead
    assert tg_dead.has_edge(("edge", ("xy", 10.0, 0.0, ()), ("xy", 20.0, 0.0, ()), ("spur", "f")), ("edge", ("xy", 20.0, 0.0, ()), ("xy", 10.0, 0.0, ()), ("spur", "b")))


