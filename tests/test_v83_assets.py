"""Free real-target-interpreter checks; no model API calls."""
import json
from pathlib import Path

from gis_agent.tools.qgis_python import run_python_script
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.sessions import SessionStore
from gis_agent.core.context import recent_execution_refs


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / 'gis_agent/skills'


def execute(qgis_dir, folder, code):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'check.py'
    path.write_text(code, encoding='utf-8')
    return run_python_script(qgis_dir / 'bin/python-qgis-ltr.bat', folder / 'logs', str(path))


def test_network_n1_to_n6(qgis_dir, tmp_path):
    run = run_python_script(qgis_dir / 'bin/python-qgis-ltr.bat', tmp_path / 'logs',
                           str(SKILLS / 'gis-spatial-analysis/scripts/network_cases.py'))
    assert run['ok'], run
    assert set(run['result']) == {f'N{i}' for i in range(1, 7)}
    assert run['result']['N3']['nearest'][0]['cost'] == 10


def test_real_io_roundtrip(qgis_dir, tmp_path):
    script = SKILLS / 'gis-spatial-analysis/scripts/io_roundtrip.py'
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


def test_staged_persist_failure_and_continue(qgis_dir, tmp_path):
    code = f'''import sys, json, os, hashlib
from pathlib import Path
sys.path.insert(0,{str(SKILLS / 'gis-spatial-analysis/scripts')!r})
import numpy as np
from staged_compute import main
folder=Path.cwd();prepared=folder/'prefix.npy';output=folder/'stats.json'
main({{'inputs':{{}},'parameters':{{'mode':'prepare','size':10000,'rounds':20}},'outputs':{{'prepared':str(prepared)}}}})
digest=hashlib.sha256(prepared.read_bytes()).hexdigest()
try: main({{'inputs':{{'prepared':str(prepared)}},'parameters':{{'mode':'wrong'}},'outputs':{{'statistics':str(output)}}}})
except ValueError: pass
else: raise AssertionError('Expected downstream failure')
result=main({{'inputs':{{'prepared':str(prepared)}},'parameters':{{'mode':'summarize'}},'outputs':{{'statistics':str(output)}}}})
values=np.load(prepared,allow_pickle=False)
assert json.loads(output.read_text())['sum']==float(values.sum())
assert hashlib.sha256(prepared.read_bytes()).hexdigest()==digest
result['prefix_runs']=1
Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps(result))
'''
    run = execute(qgis_dir, tmp_path, code)
    assert run['ok'], run


def test_recent_refs_and_directory_history_preserve_raw_record(tmp_path):
    store = SessionStore(tmp_path / 'sessions', 'history')
    output = tmp_path / 'output'
    gdb = output / 'data.gdb'
    gdb.mkdir(parents=True)
    history = ExecutionHistory(store, output)
    args = {'script_path': 'derive.py'}
    call = {'id': 'c', 'type': 'function', 'function': {'name': 'run_python_script', 'arguments': json.dumps(args)}}
    result = {'ok': True, 'result': {'outputs': {'features': str(gdb)}}}
    message = store.tool_message('c', 'run_python_script', result, 8000)
    message['execution_id'] = 'e000000_00'
    records = [{'role': 'assistant', 'content': None, 'tool_calls': [call]}, message]
    store.save(records)
    before = store.path.read_bytes()
    refs = recent_execution_refs(records)
    assert refs == [{'id': 'e000000_00', 'tool': 'run_python_script'}]
    assert len(json.dumps(refs)) <= 512
    facts = history.rows()[0]['facts']['outputs'][0]
    assert facts['path_exists'] and facts['kind'] == 'directory' and facts['layer_verified'] is None
    item = history.query()['items'][0]
    assert item['output_refs'][0]['source'] == str(gdb)
    assert store.path.read_bytes() == before
    assert recent_execution_refs([{'role':'tool','tool_name':'read_file','execution_id':'e1'}]) == []


def test_staged_example_history_replay_mocktransport_and_family_reuse(qgis_dir, tmp_path):
    """Actual prefix and tail, current Agent protocol, then zero-start reuse."""
    import httpx
    from openai import OpenAI
    from dataclasses import replace
    from functools import partial
    from langgraph.checkpoint.memory import InMemorySaver
    from test_replay import recorded
    from gis_agent.application import AgentFactory
    from gis_agent.config import AppConfig
    from gis_agent.core.model import ModelConfig
    from gis_agent.integrations.llm import chat, make_token_counter
    from gis_agent.integrations.qgis.client import QGISClient
    from gis_agent.tools.base import Tool
    from gis_agent.persistence.evidence import file_digest
    output = tmp_path / 'output'
    output.mkdir()
    history = ExecutionHistory(SessionStore(tmp_path / 'sessions', 'staged'), output)
    history.store.save([{'role':'user','origin':'user','content':'Compute and summarize saved observations.'}])
    script = SKILLS / 'gis-spatial-analysis/scripts/staged_compute.py'
    prepared = output / 'prepared.npy'
    prefix_job = output / 'prefix.json'
    prefix_job.write_text(json.dumps({'inputs':{},'parameters':{'mode':'prepare','size':20000,'rounds':25},
                                      'outputs':{'prepared':str(prepared)}}))
    tool = Tool('run_python_script', 'Python', {}, partial(run_python_script,
                 qgis_dir / 'bin/python-qgis-ltr.bat', output / 'python_logs'))
    _, prefix = recorded(history, tool, {'script_path':str(script),'arguments':[str(prefix_job)]})
    assert prefix['ok'], prefix
    before = file_digest(prepared)
    tail_job = output / 'tail.json'
    tail_job.write_text(json.dumps({'inputs':{'prepared':str(prepared)},'parameters':{'mode':'broken'},
                                    'outputs':{'statistics':str(output/'old.json')}}))
    source_id, failed = recorded(history, tool, {'script_path':str(script),'arguments':[str(tail_job)]})
    assert not failed['ok']
    plan = {'repair_id':'staged_fix','parent_repair':None,'reason':'Fix tail using saved prefix',
        'accepted_inputs':{'prepared':{'path':str(prepared)}},
        'steps':[{'step_id':'tail','source_execution':source_id,
            'inputs':{'prepared':{'accepted':'prepared'}},
            'changes':{'candidate_script':str(script),'expected_sha256':file_digest(script),
                'job_contract':True,'side_effects':'outputs_only','deterministic':True,
                'job_parameters':{'mode':'summarize'}},
            'outputs':{'statistics':'stats.json'}}], 'targets':['tail']}
    replies = [('execution_history',{'execution_id':source_id,'section':'detail'}),
               ('local_replay',{'plan':plan}),
               ('finish_task',{'status':'completed','summary':'Tail repaired with saved observations.'})]
    requests = []
    def response(request):
        requests.append(json.loads(request.content))
        name,args = replies[len(requests)-1]
        return httpx.Response(200,json={'id':str(len(requests)),'model':'offline','object':'chat.completion',
            'choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
                'tool_calls':[{'id':f'c{len(requests)}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}],
            'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})
    config = replace(AppConfig.from_env(ROOT),memory=None,model=ModelConfig(tokenizer='bytes',supports_images=False,image_tokens=0))
    messages = history.store.load()+[{'role':'user','origin':'user','content':'Fix the tail preserving the valid prefix.'}]
    with OpenAI(api_key='offline',max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(response))) as client:
        agent = AgentFactory(config,partial(chat,client,config.model),make_token_counter(config.model),
                             QGISClient(config.qgis.process_launcher),{}).create(
                                 history.store,messages,output,InMemorySaver(),'Repair from current evidence.')
        assert agent.run(messages)['status']=='completed'
    result = next(row['result'] for row in agent.history.rows() if row['tool']=='local_replay')
    assert result['ok'], result
    assert file_digest(prepared)==before and not (output/'old.json').exists()
    stats = json.loads(Path(result['outputs']['tail']['statistics']).read_text())
    assert stats['count']==20000
    # Repeated request must not launch Python at all.
    def forbidden(*_):
        raise AssertionError('Trusted completed plan should not execute again')
    native = agent.registry.get('run_python_script')
    agent.registry.tools['run_python_script'] = replace(native, function=forbidden)
    repeated = agent.registry.execute('local_replay', {'plan':plan})
    assert repeated['ok'], repeated
    assert len(requests)==3


def test_recent_hints_do_not_add_rounds_to_ordinary_python(qgis_dir, tmp_path, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from functools import partial
    from test_acceptance import make_graph_agent, reply
    from gis_agent.core import context
    from gis_agent.core.model import ModelConfig
    from gis_agent.integrations.llm import make_token_counter
    from gis_agent.tools.base import Tool
    real_hints = context.recent_execution_refs
    outcomes = []
    for enabled in (False, True):
        folder = tmp_path / str(enabled)
        folder.mkdir()
        script = folder / 'sum.py'
        script.write_text("import os,json\nfrom pathlib import Path\nPath(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'sum':sum(range(10))}))")
        store = SessionStore(folder/'sessions','ordinary')
        calls = []
        def execute(script_path):
            calls.append(script_path)
            return run_python_script(qgis_dir/'bin/python-qgis-ltr.bat',folder/'logs',script_path)
        tool = Tool('run_python_script','Python',{'type':'object','properties':{'script_path':{'type':'string'}}},execute)
        replies = iter([reply('calc','run_python_script',{'script_path':str(script)}),
                        reply('done','finish_task',{'status':'completed','summary':'sum computed'})])
        count = []
        def model(*args):
            count.append(1)
            return next(replies)
        monkeypatch.setattr(context,'recent_execution_refs',real_hints if enabled else lambda _: [])
        agent = make_graph_agent(store,model,make_token_counter(ModelConfig(tokenizer='bytes')),InMemorySaver(),(tool,))
        agent.history = ExecutionHistory(store,folder)
        assert agent.run([{'role':'user','origin':'user','content':'Compute a sum.'}])['status']=='completed'
        facts = agent.history.rows()[0]['result']['result']
        outcomes.append((len(count),len(calls),facts))
    assert outcomes == [(2,1,{'sum':45})]*2


def test_new_asset_cli_settings_and_result_channels(qgis_dir, tmp_path):
    expected = tmp_path/'expected.csv'
    allocated = tmp_path/'allocated.csv'
    expected.write_text('zone,value\n0001,10\n0002,5\n')
    allocated.write_text('zone,value\n0001,7\n')
    cases = [
        ('gis-verification', 'allocation_balance.py',
         {'expected':str(expected),'allocations':str(allocated),'zone_key':'zone','value':'value',
          'unit':'people','output':str(tmp_path/'balances.json')}),
        ('gis-spatial-analysis', 'network_location.py',
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
