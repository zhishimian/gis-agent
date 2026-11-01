import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from gis_agent.core.replay import RepairPlan, ReplayError, replay
from gis_agent.integrations.qgis.adapter import make_tool
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.qgis_python import run_python_script
from gis_agent.tools.registry import ToolRegistry


def recorded(history, tool, arguments):
    messages = history.store.read_record()
    index = len(messages)
    call = {'id': f'c{index}', 'type': 'function', 'function': {
        'name': tool.name, 'arguments': json.dumps(arguments)}}
    messages.append({'role': 'assistant', 'content': None, 'tool_calls': [call]})
    history.store.save(messages)
    history.begin(index, 0, call, tool.execution_metadata)
    result = tool.run(arguments)
    message = history.store.tool_message(call['id'], tool.name, result, 8000)
    history.complete(f'e{index:06d}_00', message, index + 1, 1, arguments)
    history.store.save([*messages, message])
    return f'e{index:06d}_00', result


@pytest.fixture
def gis_repair(tmp_path, qgis_dir):
    root = tmp_path / 'output'
    root.mkdir()
    script = tmp_path / 'inputs.py'
    script.write_text(
        "import geopandas as gpd,sys\nfrom shapely.geometry import Point,box\n"
        "from pathlib import Path\np=Path(sys.argv[1])\n"
        "gpd.GeoDataFrame({'id':[7],'label':['source']},geometry=[Point(500000,3500000)],crs=32650).to_file(p/'point.gpkg',layer='point')\n"
        "gpd.GeoDataFrame({'zone':[2]},geometry=[box(499800,3499800,500400,3500400)],crs=32650).to_file(p/'zones.gpkg',layer='zones')\n", encoding='utf-8')
    assert run_python_script(qgis_dir / 'bin/python-qgis-ltr.bat', root / 'python_logs', str(script), [str(root)])['ok']
    history = ExecutionHistory(SessionStore(tmp_path / 'sessions', 'repair'), root)
    client = QGISClient(qgis_dir / 'bin/qgis_process-qgis-ltr.bat')
    registry = ToolRegistry()
    starts = []
    for algorithm in ('native:reprojectlayer', 'native:buffer', 'native:intersection'):
        tool = make_tool(algorithm, {'name': algorithm}, client.query('help', algorithm), client)
        original = tool.function
        def counted(_original=original, _algorithm=algorithm, **arguments):
            starts.append(_algorithm)
            return _original(**arguments)
        registry.register(replace(tool, function=counted))
    projected, result = recorded(history, registry.get('qgis_native_reprojectlayer'), {
        'INPUT': str(root / 'point.gpkg'), 'TARGET_CRS': 'EPSG:32650', 'OUTPUT': str(root / 'projected.gpkg')})
    assert result['ok'], result
    buffer, result = recorded(history, registry.get('qgis_native_buffer'), {
        'INPUT': str(root / 'projected.gpkg'), 'DISTANCE': 50, 'SEGMENTS': 32, 'OUTPUT': str(root / 'old_buffer.gpkg')})
    assert result['ok'], result
    overlay, result = recorded(history, registry.get('qgis_native_intersection'), {
        'INPUT': str(root / 'old_buffer.gpkg'), 'OVERLAY': str(root / 'zones.gpkg'), 'OUTPUT': str(root / 'old_overlay.gpkg')})
    assert result['ok'], result
    plan = {
        'repair_id': 'fix', 'parent_repair': None, 'reason': 'Correct the requested distance',
        'accepted_inputs': {
            'projected': {'execution_id': projected, 'output': 'OUTPUT', 'adopt_current': True, 'reason': 'Use current projected input'},
            'zones': {'path': str(root / 'zones.gpkg')}},
        'steps': [
            {'step_id': 'buffer', 'source_execution': buffer, 'inputs': {'INPUT': {'accepted': 'projected'}},
             'changes': {'parameter_overrides': {'DISTANCE': 500}}, 'outputs': {'OUTPUT': 'buffer.gpkg'}},
            {'step_id': 'overlay', 'source_execution': overlay,
             'inputs': {'INPUT': {'step': 'buffer', 'output': 'OUTPUT'}, 'OVERLAY': {'accepted': 'zones'}},
             'changes': {}, 'outputs': {'OUTPUT': 'overlay.gpkg'}}], 'targets': ['overlay']}
    return history, registry, starts, plan


def features(path):
    with sqlite3.connect(path) as db:
        table = db.execute('select table_name from gpkg_geometry_columns').fetchone()[0]
        return db.execute('select * from "' + table + '"').fetchall(), db.execute('select srs_id from gpkg_geometry_columns').fetchall()


def test_real_qgis_local_parameter_repair(gis_repair):
    history, registry, starts, value = gis_repair
    before = {p.name: p.read_bytes() for p in history.output_root.glob('old*.gpkg')}
    result = replay(RepairPlan.parse(value), history, registry.execute, history.output_root, resolve_tool=registry.get)
    assert result['ok'], result
    assert starts == ['native:reprojectlayer', 'native:buffer', 'native:intersection', 'native:buffer', 'native:intersection']
    for name, data in before.items():
        assert (history.output_root / name).read_bytes() == data
    root = history.output_root / 'independent'
    root.mkdir()
    assert registry.execute('qgis_native_reprojectlayer', {'INPUT': str(history.output_root / 'point.gpkg'),
        'TARGET_CRS': 'EPSG:32650', 'OUTPUT': str(root / 'projected.gpkg')})['ok']
    assert registry.execute('qgis_native_buffer', {'INPUT': str(root / 'projected.gpkg'), 'DISTANCE': 500,
        'SEGMENTS': 32, 'OUTPUT': str(root / 'buffer.gpkg')})['ok']
    assert registry.execute('qgis_native_intersection', {'INPUT': str(root / 'buffer.gpkg'),
        'OVERLAY': str(history.output_root / 'zones.gpkg'), 'OUTPUT': str(root / 'overlay.gpkg')})['ok']
    assert features(result['outputs']['buffer']['OUTPUT']) == features(root / 'buffer.gpkg')
    assert features(result['outputs']['overlay']['OUTPUT']) == features(root / 'overlay.gpkg')


def test_plan_validation_and_failed_stage(gis_repair):
    history, registry, starts, value = gis_repair
    value['steps'][0]['outputs']['OUTPUT'] = '../escape.gpkg'
    with pytest.raises(ReplayError, match='相对'):
        replay(RepairPlan.parse(value), history, registry.execute, history.output_root, resolve_tool=registry.get)
    assert len(starts) == 3
    value['steps'][0]['outputs']['OUTPUT'] = 'buffer.gpkg'
    result = replay(RepairPlan.parse(value), history, lambda *a: {'ok': False, 'error': 'actual tool refusal'},
                    history.output_root, resolve_tool=registry.get)
    assert result['status'] == 'failed' and result['failed'][0]['step_id'] == 'buffer'
    assert result['pending'] == ['overlay']
