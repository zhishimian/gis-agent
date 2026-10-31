import json
import struct
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from PIL import Image

from gis_agent.tools.qgis_python import run_python_script


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "gis_agent/skills"


def execute(qgis_dir: Path, folder: Path, code: str) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "check.py"
    script.write_text(code, encoding="utf-8")
    return run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", folder / "logs", str(script))


def test_parallel_edges_expose_a_feasible_but_nonoptimal_route(qgis_dir: Path, tmp_path: Path) -> None:
    run = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", tmp_path / "logs",
                            str(SKILLS / "gis-spatial-analysis/scripts/parallel_edges.py"))
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
