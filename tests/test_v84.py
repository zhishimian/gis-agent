"""Deterministic handoff protocol checks; no paid model requests."""
import json
from pathlib import Path
from contextlib import contextmanager

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import InMemorySaver
from typer.testing import CliRunner

from gis_agent.application import Conversation
from gis_agent.core.model import ModelConfig
from gis_agent.integrations.llm import make_token_counter
from gis_agent.persistence.sessions import SessionStore
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.tools.base import Tool
from gis_agent.tools.planning import finish_task
from gis_agent.tools.qgis_python import run_python_script
from test_acceptance import make_graph_agent, reply


def build(store, responses, saver, tools=()):
    replies = iter(responses)
    calls = []
    def model(messages, schemas):
        calls.append(messages)
        return next(replies)
    agent = make_graph_agent(store,model,make_token_counter(ModelConfig(tokenizer='bytes')),saver,tools)
    agent.history = ExecutionHistory(store,store.root.parent/'output')
    return Conversation(agent,store.read_record(),store.root.parent/'output'),calls


def ask(call_id='ask'):
    return reply(call_id,'finish_task',{'status':'needs_input','summary':'Geometry complete; weighted result awaits population.',
        'question':'Provide population keyed by area ID, or approve unweighted analysis; weights change the result.',
        'reason':'missing_input','unresolved':['Population-weighted accessibility']})


def test_status_contracts_and_partial_artifacts(tmp_path):
    assert not finish_task('needs_input','missing input')['ok']
    assert finish_task('needs_input','missing input',question='Which CRS is documented?',reason='missing_input')['ok']
    assert not finish_task('partial','some work')['ok']
    assert finish_task('partial','Known metadata found; one layer is unavailable',unresolved=['missing layer'])['ok']
    path=tmp_path/'done.txt';path.write_text('four completed outputs')
    assert finish_task('partial','four completed',[str(path)],['fifth missing'])['ok']
    assert not finish_task('completed','all',[str(path)],['still missing'])['ok']
    assert not finish_task('blocked','x',reason='SyntaxError')['ok']


def test_real_gis_wait_save_reopen_answer_complete(qgis_dir,tmp_path):
    store=SessionStore(tmp_path/'sessions','gis_handoff');output=tmp_path/'output';output.mkdir()
    script=output/'prefix.py'
    script.write_text("import geopandas as gpd,sys\nfrom shapely.geometry import Point\n"
        "gpd.GeoDataFrame({'id':[1]},geometry=[Point(500000,4400000).buffer(500,quad_segs=32)],crs=32650).to_file(sys.argv[1],layer='buffer',index=False)\n")
    path=output/'buffer.gpkg';starts=[]
    def compute():
        starts.append(1)
        return run_python_script(qgis_dir/'bin/python-qgis-ltr.bat',output/'python_logs',str(script),[str(path)])
    tool=Tool('buffer_stage','GIS prefix',{'type':'object'},compute)
    with SqliteSaver.from_conn_string(str(tmp_path/'checkpoint.sqlite')) as saver:
        conv,calls=build(store,[reply('compute','buffer_stage',{}),ask()],saver,(tool,))
        assert conv.send('Buffer the point and calculate population-weighted access.')['status']=='needs_input'
        request=conv.waiting['request_id'];frozen=path.read_bytes()
        prefix=store.path.read_bytes()
        assert len(calls)==2 and len(starts)==1 and not conv.pending
    with SqliteSaver.from_conn_string(str(tmp_path/'checkpoint.sqlite')) as saver:
        conv,calls=build(store,[reply('done','finish_task',{'status':'completed','summary':'Approved unweighted geometry delivered.',
                                  'artifacts':[str(path)]})],saver,(tool,))
        assert conv.waiting['request_id']==request
        assert store.path.read_bytes()==prefix
        assert conv.reply('Use unweighted analysis for this task.',request_id=request,reply_id='answer1')['status']=='completed'
        assert not conv.waiting and len(calls)==1 and len(starts)==1 and path.read_bytes()==frozen
        assert any(m.get('in_reply_to')==request for m in store.read_record())
        with pytest.raises(ValueError): conv.reply('again',request_id=request,reply_id='answer1')
        assert any(row['tool']=='buffer_stage' and row['status']=='succeeded' for row in conv.agent.history.rows())
    check=output/'check.py';check.write_text("import geopandas as gpd,json,os,sys,math\nfrom pathlib import Path\n"
        "d=gpd.read_file(sys.argv[1]);assert d.crs.to_epsg()==32650 and len(d)==1 and d.geometry.is_valid.all()\n"
        "assert abs(d.geometry.area.iloc[0]-785082.7892387)<.001\n"
        "Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'area':float(d.geometry.area.iloc[0])}))")
    assert run_python_script(qgis_dir/'bin/python-qgis-ltr.bat',output/'checks',str(check),[str(path)])['ok']


def test_multiple_answers_invalid_duplicate_cancel_and_reload(tmp_path):
    store=SessionStore(tmp_path,'answers');saver=InMemorySaver()
    conv,calls=build(store,[ask(),ask('ask2')],saver)
    conv.send('Weighted task with missing data')
    first=conv.waiting['request_id']
    with pytest.raises(ValueError): conv.reply(' ',request_id=first)
    with pytest.raises(ValueError): conv.reply('x',request_id='stale')
    conv.reply('I have no table yet',request_id=first,reply_id='one')
    assert conv.waiting['request_id']!=first
    with pytest.raises(ValueError): conv.reply('retry',reply_id='one')
    conv.cancel();assert not conv.waiting and len(calls)==2
    reopened,_=build(store,[],saver)
    assert not reopened.waiting
    from gis_agent.persistence.interaction import latest_outcome
    assert latest_outcome(store,store.read_record())['status']=='cancelled'


def test_reply_saved_before_first_model_can_restart_safely(tmp_path):
    store=SessionStore(tmp_path,'saved_reply');saver=InMemorySaver()
    conv,_=build(store,[ask()],saver);conv.send('Need weights')
    request=conv.waiting['request_id']
    messages=store.read_record()+[{'role':'user','origin':'user','content':'Approved unweighted',
                                 'in_reply_to':request,'reply_id':'durable'}]
    store.save(messages)
    conv,calls=build(store,[reply('done','finish_task',{'status':'answer','summary':'Approval recorded'})],saver)
    assert conv.pending_answer and conv.continue_answer()['status']=='answer' and len(calls)==1


def test_answer_preserves_known_dynamic_algorithms(tmp_path):
    store=SessionStore(tmp_path,'known_tools');saver=InMemorySaver()
    conv,_=build(store,[ask(),reply('done','finish_task',{'status':'answer','summary':'Updated scope accepted'})],saver)
    conv.send('Task awaiting a business choice')
    conv.agent.graph.update_state(conv.agent.options(),{'algorithms':['native:buffer']},as_node='finish')
    conv.agent.load_qgis_tool=lambda _: Tool('qgis_native_buffer','known',{'type':'object'},lambda: {'ok':True})
    original=conv.agent.chat
    def checked(messages,schemas):
        assert any(s['function']['name']=='qgis_native_buffer' for s in schemas)
        return original(messages,schemas)
    conv.agent.chat=checked
    assert conv.reply('Use the existing buffer result')['status']=='answer'


def test_cancellation_checkpoint_write_window_and_tampered_answer(tmp_path,monkeypatch):
    store=SessionStore(tmp_path,'cancel_window');saver=InMemorySaver()
    conv,_=build(store,[ask()],saver);conv.send('Missing factor')
    original=conv.agent.graph.update_state
    def fail(*a,**k): raise OSError('simulated checkpoint write failure')
    monkeypatch.setattr(conv.agent.graph,'update_state',fail)
    with pytest.raises(OSError): conv.cancel()
    monkeypatch.setattr(conv.agent.graph,'update_state',original)
    reopened,calls=build(store,[reply('done','finish_task',{'status':'answer','summary':'New request answered'})],saver)
    assert reopened.send('A new independent question')['status']=='answer' and len(calls)==1
    # Arbitrary historical edits must never obtain this narrow recovery.
    records=store.read_record();records[0]['content']='tampered';store.save(records)
    broken,_=build(store,[],saver)
    with pytest.raises(ValueError): broken.send('continue')


@pytest.mark.parametrize('mode',['normal','discover','repair','unsupported','partial','topology'])
def test_outcome_routes_keep_original_success_free_of_confirmation(tmp_path,mode):
    store=SessionStore(tmp_path,mode);saver=InMemorySaver();runs=[]
    path=tmp_path/'four.txt'
    def work():
        runs.append(1)
        if mode=='repair' and len(runs)==1: return {'ok':False,'error':'recoverable field typo'}
        path.write_text('trusted work')
        return {'ok':True,'actual_layer':'known','crs':'EPSG:32650','outputs':{'data':str(path)}}
    tool=Tool('operation','work',{'type':'object'},work)
    responses=[reply('work','operation',{})]
    if mode=='repair': responses.append(reply('fixed','operation',{}))
    if mode in {'normal','discover','repair'}:
        final={'status':'completed','summary':'Data found or code repaired','artifacts':[str(path)]}
    elif mode=='unsupported':
        final={'status':'blocked','summary':'Available formats cannot encode this requirement','unresolved':['Unsupported format'],'reason':'unsupported'}
    else:
        final={'status':'partial','summary':'Reliable independent work retained','artifacts':[str(path)],
               'unresolved':['No population' if mode=='partial' else 'Unverified road connections'],'reason':'missing_input' if mode=='partial' else 'data_quality'}
    responses.append(reply('finish','finish_task',final))
    conv,calls=build(store,responses,saver,(tool,))
    result=conv.send('Complete feasible independent work')
    assert result['status']==final['status'] and not conv.waiting
    assert len(calls)==(3 if mode=='repair' else 2)
    assert path.exists()


def test_cli_question_exit_restart_answer_and_offline_waiting(tmp_path,monkeypatch):
    from gis_agent.cli import app
    import gis_agent.application as application
    store=SessionStore(tmp_path/'sessions','cli');saver=InMemorySaver()
    replies=iter([ask(),reply('done','finish_task',{'status':'answer','summary':'Unweighted choice accepted'})])
    def model(*_): return next(replies)
    @contextmanager
    def opened(config,session):
        agent=make_graph_agent(store,model,make_token_counter(ModelConfig(tokenizer='bytes')),saver)
        yield Conversation(agent,store.read_record(),tmp_path/'output')
    monkeypatch.setattr(application,'open_conversation',opened)
    from gis_agent.config import AppConfig
    monkeypatch.setattr(AppConfig,'from_env',classmethod(lambda cls,project:None))
    monkeypatch.delenv('GIS_AGENT_SESSIONS_DIR',raising=False)
    runner=CliRunner()
    first=runner.invoke(app,['--project',str(tmp_path),'--session','cli','chat'],input='Weighted task\nexit\n')
    assert first.exit_code==0,first.output
    assert 'needs_input' in first.output
    before=store.path.read_bytes()
    status=runner.invoke(app,['--project',str(tmp_path),'--session','cli','waiting'])
    assert status.exit_code==0 and '"waiting": true' in status.output and store.path.read_bytes()==before
    leave=runner.invoke(app,['--project',str(tmp_path),'--session','cli','chat'],input='')
    assert leave.exit_code==0 and store.path.read_bytes()==before,leave.output
    second=runner.invoke(app,['--project',str(tmp_path),'--session','cli','chat'],input='Approved unweighted\nexit\n')
    assert second.exit_code==0 and 'answer' in second.output,second.output


def test_independent_process_shutdown_and_same_session_continue(tmp_path):
    import subprocess,sys
    worker=Path(__file__).with_name('handoff_worker.py')
    for phase in ['wait','answer']:
        run=subprocess.run([sys.executable,str(worker),str(tmp_path),phase],capture_output=True,timeout=60)
        assert run.returncode==0,run.stderr.decode(errors='replace')
    assert json.loads((tmp_path/'wait.json').read_text())['outcome']['status']=='needs_input'
    assert json.loads((tmp_path/'answer.json').read_text())['outcome']['status']=='completed'
    assert json.loads((tmp_path/'result.json').read_text())=={'value':42}
    assert json.loads((tmp_path/'prefix.json').read_text())=={'value':6}
