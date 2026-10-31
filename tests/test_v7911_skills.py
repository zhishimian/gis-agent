import json
import re
from pathlib import Path

import pytest
import yaml

from gis_agent.prompts import render_prompt
from gis_agent.skills import skill_index
from gis_agent.tools.qgis_python import run_python_script


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "gis_agent/skills"


def execute(qgis_dir: Path, folder: Path, code: str) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "check.py"
    script.write_text(code, encoding="utf-8")
    return run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", folder / "logs", str(script))


def script_call(qgis_dir: Path, folder: Path, skill: str, script: str, settings: dict) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    config = folder / "settings.json"
    config.write_text(json.dumps(settings), encoding="utf-8")
    return run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", folder / "logs",
                             str(SKILLS / skill / "scripts" / script), [str(config)])


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
    assert {s["name"] for s in skills} == {"gis-spatial-analysis", "gis-verification", "gis-cartography"}
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
    result = script_call(qgis_dir, data / "join_run", "gis-spatial-analysis", "spatial_join.py", settings)
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
    failed = script_call(qgis_dir, data / "mismatch_run", "gis-spatial-analysis", "spatial_join.py", settings)
    assert not failed["ok"] and "CRS mismatch" in failed["stderr"]
    settings.update(analysis_crs="EPSG:3857", output_dir=str(data / "explicit_crs"),
                    query_geometry="geometry", predicate="intersects")
    transformed = script_call(qgis_dir, data / "explicit_run", "gis-spatial-analysis", "spatial_join.py", settings)
    assert transformed["ok"] and transformed["result"]["match_pairs"] == 4


def test_processing_chain_real_area_and_output_protection(qgis_dir: Path, data: Path) -> None:
    output = data / "clip.gpkg"
    settings = {"source": f"{data / 'join.gpkg'}|layername=source_geographic", "mask": f"{data / 'join.gpkg'}|layername=reference",
                "target_crs": "EPSG:3857", "output": str(output)}
    result = script_call(qgis_dir, data / "chain", "gis-spatial-analysis", "reproject_clip.py", settings)
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
    refused = script_call(qgis_dir, data / "chain_again", "gis-spatial-analysis", "reproject_clip.py", settings)
    assert not refused["ok"] and "FileExistsError" in refused["stderr"]


def test_join_keeps_large_numeric_ids_exact(qgis_dir: Path, tmp_path: Path) -> None:
    checked = execute(qgis_dir, tmp_path, f'''import json,os,runpy
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point,box
analyze=runpy.run_path({str(SKILLS / 'gis-spatial-analysis/scripts/spatial_join.py')!r})['analyze']
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
