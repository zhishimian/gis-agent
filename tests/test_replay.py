import json
import sqlite3
from dataclasses import replace
from copy import deepcopy
from pathlib import Path

import pytest

from gis_agent.core.replay import RepairPlan, ReplayError, replay
from gis_agent.integrations.qgis.adapter import make_tool
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.qgis_python import run_python_script
from gis_agent.tools.base import Tool
from gis_agent.persistence.evidence import file_digest
from functools import partial
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


@pytest.fixture
def python_repair(tmp_path, qgis_dir):
    root = tmp_path / 'output'
    root.mkdir()
    script = tmp_path / 'monolith.py'
    prefix = root / 'prefix.txt'
    data = root / 'intermediate.npy'
    script.write_text(
        "import numpy as np,json,sys,os\nfrom pathlib import Path\n"
        f"if len(sys.argv)==1:\n    Path({str(prefix)!r}).write_text('computed once')\n"
        f"    np.save({str(data)!r},np.arange(10))\n    raise KeyError('late failure')\n"
        "job=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        "values=np.load(job['inputs']['values'])\n"
        "result=values['missing']\n"
        "np.save(job['outputs']['sum'],result)\n"
        "np.save(job['outputs']['count'],np.array(values.size))\n"
        "Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'outputs':job['outputs']}),encoding='utf-8')\n",
        encoding='utf-8')
    history = ExecutionHistory(SessionStore(tmp_path / 'sessions', 'python'), root)
    tool = Tool('run_python_script', 'Python', {}, partial(run_python_script,
        qgis_dir / 'bin/python-qgis-ltr.bat', root / 'python_logs'))
    registry = ToolRegistry()
    registry.register(tool)
    source, result = recorded(history, tool, {'script_path': str(script)})
    assert not result['ok'] and data.is_file()
    plan = {'repair_id': 'python_fix', 'parent_repair': None, 'reason': 'Reuse persisted prefix',
            'accepted_inputs': {'values': {'path': str(data)}},
            'steps': [{'step_id': 'tail', 'source_execution': source,
                       'inputs': {'values': {'accepted': 'values'}},
                       'changes': {'job_contract': True, 'side_effects': 'outputs_only', 'deterministic': True,
                                   'patches': [{'expected_sha256': result['script_sha256'],
                                                'old_text': "result=values['missing']", 'new_text': 'result=values.sum()'}]},
                       'outputs': {'sum': 'sum.npy', 'count': 'count.npy'}}], 'targets': ['tail']}
    return history, registry, plan, script, prefix


def test_real_python_patch_reuses_persisted_prefix(python_repair, qgis_dir):
    history, registry, value, script, prefix = python_repair
    before = script.read_bytes(), prefix.stat().st_mtime_ns
    result = replay(RepairPlan.parse(value), history, registry.execute, history.output_root, resolve_tool=registry.get)
    assert result['ok'], result
    assert (script.read_bytes(), prefix.stat().st_mtime_ns) == before
    check = history.output_root / 'check.py'
    check.write_text("import numpy as np,sys\nassert np.load(sys.argv[1])==45\nassert np.load(sys.argv[2])==10\n", encoding='utf-8')
    assert run_python_script(qgis_dir / 'bin/python-qgis-ltr.bat', history.output_root / 'python_logs',
        str(check), list(result['outputs']['tail'].values()))['ok']
    receipt = json.loads((history.record_dir / (result['execution_refs']['tail'] + '.json')).read_text())
    frozen = Path(receipt['resolved_call']['arguments']['script_path'])
    assert frozen != script and 'values.sum()' in frozen.read_text()
    assert Path(receipt['result']['script_snapshot']).read_bytes() == frozen.read_bytes()


@pytest.mark.parametrize('failure', ['hash', 'duplicate', 'dependency'])
def test_python_patch_failures_do_not_run(python_repair, failure):
    history, registry, value, script, prefix = python_repair
    changes = value['steps'][0]['changes']
    if failure == 'hash':
        changes['patches'][0]['expected_sha256'] = '0' * 64
    elif failure == 'duplicate':
        changes['patches'][0]['old_text'] = 'values'
    else:
        changes['dependencies'] = {'helper.py': {'path': str(script), 'expected_sha256': '0' * 64}}
    with pytest.raises(ReplayError):
        replay(RepairPlan.parse(value), history, registry.execute, history.output_root, resolve_tool=registry.get)
    assert not (history.output_root / 'repairs/python_fix/sum.npy').exists()


def test_python_cache_identity_and_changed_content(python_repair):
    import os
    history, registry, value, script, prefix = python_repair
    environment = {'managed': 'local-test'}
    starts = []
    def execute(name, args):
        starts.append(name)
        return registry.execute(name, args)
    def run(plan):
        return replay(RepairPlan.parse(plan), history, execute, history.output_root,
                      resolve_tool=registry.get, environment=environment)
    first = run(value)
    assert first['ok'] and len(starts) == 1
    assert run(value) == first and len(starts) == 1
    conflict = deepcopy(value)
    conflict['reason'] = 'different'
    with pytest.raises(ReplayError, match='不同计划'):
        run(conflict)
    second = deepcopy(value)
    second.update(repair_id='second', parent_repair='python_fix')
    result = run(second)
    assert result['reused'] == ['tail'] and len(starts) == 1, result
    source = Path(value['accepted_inputs']['values']['path'])
    stat = source.stat()
    content = bytearray(source.read_bytes())
    content[-8:] = (100).to_bytes(8, 'little')
    source.write_bytes(content)
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = deepcopy(value)
    changed.update(repair_id='changed', parent_repair='second')
    assert run(changed)['completed'] == ['tail'] and len(starts) == 2
    Path(first['outputs']['tail']['sum']).unlink()
    assert run(value)['status'] == 'unknown' and len(starts) == 2
    child = history.query(execution_id=result['execution_refs']['tail'], section='detail', max_characters=8000)
    assert child['ok']


def test_helper_candidate_and_parameter_cache_invalidation(python_repair):
    history, registry, value, script, prefix = python_repair
    helper = history.output_root / 'helper.py'
    helper.write_text('factor=2\n')
    candidate = history.output_root / 'candidate.py'
    candidate.write_text(script.read_text().replace("result=values['missing']",
        "from helper import factor\nresult=values.sum()*factor*job['parameters']['scale']"))
    changes = value['steps'][0]['changes']
    changes.pop('patches')
    changes.update(candidate_script=str(candidate), expected_sha256=file_digest(candidate),
        dependencies={'helper.py': {'path': str(helper), 'expected_sha256': file_digest(helper)}}, job_parameters={'scale': 1})
    def run(plan):
        return replay(RepairPlan.parse(plan), history, registry.execute, history.output_root,
                      resolve_tool=registry.get, environment={'managed': 'local-test'})
    first = run(value)
    assert first['ok']
    for index, modify in enumerate(('helper', 'code', 'parameter', 'environment')):
        current = deepcopy(value)
        current.update(repair_id=f'change{index}', parent_repair='python_fix')
        if modify == 'helper':
            helper.write_text('factor=3\n')
            current['steps'][0]['changes']['dependencies']['helper.py']['expected_sha256'] = file_digest(helper)
        elif modify == 'code':
            candidate.write_text(candidate.read_text() + '\nprint("revision")\n')
            current['steps'][0]['changes']['expected_sha256'] = file_digest(candidate)
        elif modify == 'parameter':
            current['steps'][0]['changes']['job_parameters']['scale'] = 3
        else:
            current['steps'][0]['changes']['job_parameters']['scale'] = 4
        current['steps'][0]['changes']['expected_sha256'] = file_digest(candidate)
        current['steps'][0]['changes']['dependencies']['helper.py']['expected_sha256'] = file_digest(helper)
        assert run(current)['completed'] == ['tail']


@pytest.mark.parametrize('fault', ['cycle', 'port', 'collision'])
def test_dependency_graph_rejected_before_execution(tmp_path, fault):
    from gis_agent.core.replay import order_steps
    value = {'repair_id': 'graph', 'parent_repair': None, 'reason': 'test', 'accepted_inputs': {},
             'steps': [{'step_id': 'a', 'source_execution': 'e000000_00', 'inputs': {}, 'changes': {}, 'outputs': {'x': 'a.json'}},
                       {'step_id': 'b', 'source_execution': 'e000000_00', 'inputs': {'x': {'step': 'a', 'output': 'x'}},
                        'changes': {}, 'outputs': {'x': 'b.json'}}], 'targets': ['b']}
    if fault == 'cycle':
        value['steps'][0]['inputs'] = {'x': {'step': 'b', 'output': 'x'}}
    elif fault == 'port':
        value['steps'][1]['inputs']['x']['output'] = 'missing'
    else:
        value['steps'][1]['outputs']['x'] = 'a.json'
    with pytest.raises(ReplayError):
        order_steps(RepairPlan.parse(value), tmp_path)


def test_qgis_family_reuses_independent_branch_and_gpkg_changes(gis_repair):
    history, registry, starts, value = gis_repair
    branch = deepcopy(value['steps'][0])
    branch.update(step_id='independent', outputs={'OUTPUT': 'independent.gpkg'})
    branch['changes']['parameter_overrides']['DISTANCE'] = 20
    value['steps'].append(branch)
    value['targets'].append('independent')
    def run(plan):
        return replay(RepairPlan.parse(plan), history, registry.execute, history.output_root,
                      resolve_tool=registry.get, environment={'managed': 'qgis-test'})
    first = run(value)
    assert first['ok'] and len(starts) == 6
    next_plan = deepcopy(value)
    next_plan.update(repair_id='adjust', parent_repair='fix')
    next_plan['steps'][0]['changes']['parameter_overrides']['DISTANCE'] = 300
    adjusted = run(next_plan)
    assert adjusted['completed'] == ['buffer', 'overlay'] and adjusted['reused'] == ['independent']
    assert len(starts) == 8
    with sqlite3.connect(history.output_root / 'zones.gpkg') as db:
        db.execute('PRAGMA user_version=42')
    third = deepcopy(next_plan)
    third.update(repair_id='zones_changed', parent_repair='adjust')
    changed = run(third)
    assert changed['completed'] == ['overlay'] and changed['reused'] == ['buffer', 'independent']
    assert len(starts) == 9
    (history.output_root / 'zones.gpkg-wal').write_bytes(b'active')
    fourth = deepcopy(third)
    fourth.update(repair_id='wal', parent_repair='zones_changed')
    with pytest.raises(ReplayError, match='活动日志'):
        run(fourth)
    assert len(starts) == 9


def test_tiff_content_and_sidecar_identity(tmp_path, qgis_dir):
    from gis_agent.core.replay import file_version, same_version
    script = tmp_path / 'raster.py'
    raster = tmp_path / 'grid.tif'
    script.write_text("from osgeo import gdal,osr\nimport sys\np=sys.argv[1]\n"
        "d=gdal.GetDriverByName('GTiff').Create(p,3,3,1,gdal.GDT_Float32)\n"
        "s=osr.SpatialReference();s.ImportFromEPSG(int(sys.argv[2]));d.SetProjection(s.ExportToWkt())\n"
        "d.SetGeoTransform([0,10,0,30,0,-10]);d.GetRasterBand(1).SetNoDataValue(float(sys.argv[3]))\n"
        "d.GetRasterBand(1).Fill(4);d=None\n", encoding='utf-8')
    def create(crs, nodata):
        assert run_python_script(qgis_dir/'bin/python-qgis-ltr.bat', tmp_path/'python_logs', str(script),
                                 [str(raster), str(crs), str(nodata)])['ok']
    create(32650, -9999)
    original = file_version(str(raster))
    create(32649, -9999)
    assert not same_version(original)
    changed = file_version(str(raster))
    create(32649, -999)
    assert not same_version(changed)
    Path(str(raster)+'.aux.xml').write_text('<PAMDataset/>')
    with pytest.raises(ReplayError, match='附属'):
        file_version(str(raster))


def test_single_agent_mocktransport_history_repair_and_continue(python_repair, tmp_path):
    import httpx
    from openai import OpenAI
    from langgraph.checkpoint.memory import InMemorySaver
    from gis_agent.application import AgentFactory
    from gis_agent.config import AppConfig
    from gis_agent.integrations.llm import chat, make_token_counter
    from gis_agent.core.model import ModelConfig
    history, registry, value, script, prefix = python_repair
    requests = []
    expected = [
        ('execution_history', {'execution_id': value['steps'][0]['source_execution'], 'section': 'detail', 'max_characters': 8000}),
        ('local_replay', {'plan': value}),
        ('finish_task', {'status': 'completed', 'summary': 'Repaired the persisted tail.'})]
    def response(request):
        requests.append(json.loads(request.content))
        name, args = expected[len(requests)-1]
        if name == 'local_replay':
            assert 'late failure' in json.dumps(requests[-1])
        if name == 'finish_task':
            assert 'r_python_fix_s00' in json.dumps(requests[-1])
        return httpx.Response(200, json={'id': f'test{len(requests)}', 'object': 'chat.completion',
            'model': 'offline', 'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'c{len(requests)}', 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(args)}}]}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})
    config = replace(AppConfig.from_env(Path(__file__).resolve().parents[1]), memory=None,
                     session_root=history.store.root, output_root=history.output_root.parent,
                     model=ModelConfig(tokenizer='bytes', supports_images=False, image_tokens=0))
    messages = [*history.store.load(), {'role': 'user', 'origin': 'user', 'content': 'Fix the late error without recomputing saved inputs.'}]
    with OpenAI(api_key='offline', max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(response))) as client:
        agent = AgentFactory(config, partial(chat, client, config.model), make_token_counter(config.model),
                             QGISClient(config.qgis.process_launcher), {}).create(
            history.store, messages, history.output_root, InMemorySaver(), 'Use current evidence to repair.')
        assert agent.run(messages)['status'] == 'completed'
    assert len(requests) == 3
    rows = agent.history.rows()
    assert any(row['pairing'] == 'replay_child' and row['status'] == 'succeeded' for row in rows)
    assert prefix.read_text() == 'computed once'
    results = [row['result'] for row in rows if row['tool'] == 'local_replay']
    assert results[0]['ok'], results
    assert len(json.dumps(results[0])) < 4000
