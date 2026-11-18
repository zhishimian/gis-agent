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
