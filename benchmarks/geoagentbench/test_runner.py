"""Free protocol tests: no real provider connections."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from benchmarks.geoagentbench.common import Ledger, Protection, costs, credentials


def test_ledger_pending_and_limits(tmp_path):
    a=Ledger(tmp_path/'ledger.sqlite',1)
    first=a.reserve('task',.4, .6)
    with pytest.raises(Protection):a.reserve('task',.3,.6)
    a.settle(first,.1,{'ok':True})
    assert a.total()==pytest.approx(.1)
    a.reserve('other',.8,1)
    with pytest.raises(Protection):a.reserve('new',.2,1)
    assert Ledger(a.path).total()==pytest.approx(.9)


def test_cost_and_cache():
    v=costs({'prompt_tokens':1000,'completion_tokens':100,'prompt_tokens_details':{'cached_tokens':800}},
            '2026-11-10T12:00:00+08:00','2026-11-10T12:01:00+08:00')
    assert v['peak_cny']==pytest.approx(.00136)
    assert v['estimated_cny']==v['peak_cny']
    with pytest.raises(ValueError):costs({},'','')


def test_budget_cli_rejects_invalid_and_preserves_existing(tmp_path,monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from benchmarks.geoagentbench import run
    from benchmarks.geoagentbench.common import HOST
    monkeypatch.setattr(run,'frozen_sources',lambda:{})
    config={'source_hashes':{},'budget_cny':100.}
    (tmp_path/'config.json').write_text(json.dumps(config),encoding='utf-8')
    assert run.initialize(tmp_path,SimpleNamespace(budget_cny=1.))==config
    child=subprocess.run([str(HOST),str(Path(run.__file__)), 'prepare','--run-dir',str(tmp_path/'new'),
                          '--budget-cny','nan'],capture_output=True,timeout=15)
    assert child.returncode==2 and not (tmp_path/'new').exists()


def test_only_transport_is_retryable():
    from benchmarks.geoagentbench.common import retryable_transport
    from gis_agent.core.model import ModelError
    from openai import APIConnectionError
    import httpx
    err=ModelError('connection');err.__cause__=APIConnectionError(request=httpx.Request('POST','https://example.invalid'))
    assert retryable_transport(err)
    assert not retryable_transport(ValueError('invalid parameter'))


def test_literal_credentials_no_execution(tmp_path):
    p=tmp_path/'ref.py'
    p.write_text("raise Exception('MUST NOT EXECUTE')\nclient=OpenAI(api_key='test-only',base_url='https://example.invalid')\nr=create(model='test-model')")
    assert credentials(p)==('test-only','https://example.invalid','test-model')


def test_real_sdk_mock_function_protocol():
    import httpx
    from openai import OpenAI
    from gis_agent.core.model import ModelConfig
    from gis_agent.integrations.llm import chat
    count=0
    def handler(request):
        nonlocal count
        count+=1
        content=json.loads(request.content)
        assert 'api_key' not in content
        assert content['max_tokens']==1024
        message={'role':'assistant','content':None,'reasoning_content':'test', 'tool_calls':[
            {'id':'a','type':'function','function':{'name':'echo','arguments':'{"text":"ok"}'}}]}
        return httpx.Response(200,json={'id':'mock','object':'chat.completion','created':1,'model':'test',
            'choices':[{'index':0,'message':message,'finish_reason':'tool_calls'}],
            'usage':{'prompt_tokens':100,'completion_tokens':10,'total_tokens':110}})
    client=OpenAI(api_key='test-only',max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    reply=chat(client,ModelConfig(max_tokens=1024),[{'role':'user','content':'test'}],[])
    assert reply.message['tool_calls'][0]['function']['name']=='echo'
    assert reply.message['reasoning_content']=='test'
    assert count==1


def test_numeric_rules_and_boolean(tmp_path):
    from benchmarks.geoagentbench.evaluate import check_rule
    (tmp_path/'r.json').write_text('{"mse":32,"visible":true}')
    assert check_rule('CHECK:JSON_VALUE:r.json:mse:<6000',tmp_path)['passed']
    assert check_rule('CHECK:JSON_VALUE:r.json:visible:==True',tmp_path)['passed']
    (tmp_path/'r.json').write_text('{"visible":"true"}')
    assert not check_rule('CHECK:JSON_VALUE:r.json:visible:==True',tmp_path)['passed']


def test_real_child_scope(tmp_path):
    import subprocess, os
    from benchmarks.geoagentbench.common import PROJECT
    work=tmp_path/'work'
    for name in ['output','temp','records/sessions']:(work/name).mkdir(parents=True,exist_ok=True)
    script=work/'output/check.py'
    script.write_text('''import json, os
from pathlib import Path
import numpy as np
from gis_agent.integrations.plotting.runtime import configure_plotting
configure_plotting()
assert not any('API_KEY' in k for k in os.environ)
try:
    Path(os.environ['GAB_PROJECT']).joinpath('timu暂存/gis-benchmarks/GABench/benchmark/benchmark.csv').read_bytes()
    raise AssertionError('Reference readable')
except PermissionError: pass
try:
    import socket
    socket.create_connection(('example.com',443))
    raise AssertionError('Network allowed')
except PermissionError: pass
np.save(Path(__file__).with_name('small.npy'),np.arange(3))
Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'sum':int(np.arange(3).sum()),'scope':'passed'}))
''',encoding='utf-8')
    request=work/'output/request.json';request.write_text(json.dumps({'script':str(script),'arguments':[]}))
    result=work/'output/result.json'
    child=Path(__file__).with_name('child_entry.py')
    env=os.environ|{'GAB_WORK':str(work),'GAB_PROJECT':str(PROJECT),'GAB_EXTRA':str(tmp_path),
        'GIS_AGENT_SCRIPT_REQUEST':str(request),'GIS_AGENT_RESULT_PATH':str(result),'GIS_AGENT_PROJECT_ROOT':str(PROJECT),
        'DASHSCOPE_API_KEY':'test-only','TEMP':str(work/'temp'),'TMP':str(work/'temp')}
    p=subprocess.run(['E:/exe/qgis/bin/python-qgis-ltr.bat','-B',str(child),str(PROJECT/'gis_agent/integrations/qgis/script_entry.py')],
                      capture_output=True,env=env,timeout=90,cwd=script.parent)
    assert p.returncode==0,p.stderr.decode('utf-8',errors='replace')
    assert json.loads(result.read_text())['sum']==3


def test_scientific_counterexamples_real_qgis():
    import subprocess
    code='''import sys
sys.path.insert(0, 'E:/vscode/gis-agent')
import numpy as np
from benchmarks.geoagentbench.scientific_checks import fill,flow_lengths
a=np.array([[5.,5.,5.],[5.,1.,5.],[5.,5.,5.]])
assert fill(a,np.ones(a.shape,bool))[1,1]==5
d=np.array([[1.,1.,0.]])
u,v,b,n,t=flow_lengths(d,np.ones(d.shape,bool),(0,10,0,0,0,-10))
assert np.allclose(u,[[0,10,20]]) and np.allclose(v,[[20,10,0]])
assert np.unique(b).size==1 and n==3
print('counterexamples passed')
'''
    proc=subprocess.run(['E:/exe/qgis/bin/python-qgis-ltr.bat','-B','-c',code],capture_output=True,timeout=60)
    assert proc.returncode==0,proc.stderr.decode('utf-8',errors='replace')


def test_worker_cross_process_single_writer(tmp_path):
    import subprocess
    from benchmarks.geoagentbench.common import HOST,PROJECT
    code='''import sys,time,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import benchmarks.geoagentbench.worker as w
work=Path(sys.argv[2]);(work/'records').mkdir(exist_ok=True)
def fake(work,run):
    with (work/'started').open('a') as f:f.write('one\\n')
    time.sleep(1)
    (work/'records/result.json').write_text('{}')
w.execute=fake
w.locked_execute(work,work)
'''
    processes=[subprocess.Popen([str(HOST),'-c',code,str(PROJECT),str(tmp_path)]) for _ in range(2)]
    assert [p.wait(timeout=30) for p in processes]==[0,0]
    assert (tmp_path/'started').read_text().splitlines()==['one']


def test_initialize_removes_hard_call_limit_and_sets_budget_guard(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from benchmarks.geoagentbench import run
    monkeypatch.setattr(run,'frozen_sources',lambda:{})
    monkeypatch.setattr(run,'credentials',lambda _ref:('k','https://example.invalid','m'))
    spec=run.initialize(tmp_path,SimpleNamespace(credential_reference='dummy.py',budget_cny=15.,workers=3,standalone=True))
    assert spec['max_calls'] is None
    assert spec['task_budget_cny']==pytest.approx(4.)
    assert spec['standalone'] is True
