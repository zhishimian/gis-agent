import json
import os
import signal
import socket
import sys
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
os.environ['HF_HUB_OFFLINE'] = '1'
def no_network(*args, **kwargs):
    raise AssertionError('Crash worker forbids network')
socket.socket.connect = no_network

from langgraph.checkpoint.sqlite import SqliteSaver
from gis_agent.core.replay import RepairPlan, replay
from gis_agent.integrations.llm import make_token_counter
from gis_agent.core.model import ModelConfig
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.sessions import SessionStore
from gis_agent.persistence.evidence import file_digest
from gis_agent.tools.base import Tool
from gis_agent.tools.qgis_python import run_python_script
from test_replay import recorded
from test_acceptance import make_graph_agent, reply


def main():
    root, window, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    root.mkdir(parents=True, exist_ok=True)
    store = SessionStore(root/'sessions', 'crash')
    history = ExecutionHistory(store, root/'output')
    history.output_root.mkdir(exist_ok=True)
    python = Tool('run_python_script', 'Python', {}, partial(run_python_script,
                  Path(sys.executable), history.output_root/'python_logs'))
    plan_path = root/'requested.json'
    if not plan_path.exists():
        script = root/'original.py'
        script.write_text("import json,sys,os\nfrom pathlib import Path\n"
            "job=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
            "value=job['parameters']['missing']\n"
            "Path(job['outputs']['value']).write_text(json.dumps({'value':value}))\n"
            "Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'outputs':job['outputs']}))\n", encoding='utf-8')
        job = root/'old-job.json'
        job.write_text(json.dumps({'inputs': {}, 'parameters': {}, 'outputs': {'value': str(root/'old.json')}}))
        source, result = recorded(history, python, {'script_path': str(script), 'arguments': [str(job)]})
        assert not result['ok']
        plan_path.write_text(json.dumps({'repair_id':'repair','parent_repair':None,'reason':'Fix missing key',
            'accepted_inputs':{},'steps':[{'step_id':'tail','source_execution':source,'inputs':{},
            'changes':{'job_contract':True,'side_effects':'outputs_only','deterministic':True,
                'patches':[{'expected_sha256':file_digest(script),'old_text':"job['parameters']['missing']",'new_text':'7'}]},
            'outputs':{'value':'value.json'}}],'targets':['tail']}))
    plan = json.loads(plan_path.read_text())
    starts = root/'starts.txt'
    def execute(name, args):
        with starts.open('a') as file:
            file.write('native\n')
        return python.run(args)
    def run_plan(plan):
        return replay(RepairPlan.parse(plan), history, execute, history.output_root,
                      resolve_tool=lambda name: python, environment={'python':sys.executable})
    local = Tool('local_replay', 'Replay', {'type':'object'}, run_plan)
    def model(*args):
        if mode == 'resume':
            return reply('finish','finish_task',{'status':'completed','summary':'Recovered'})
        return reply('repair','local_replay',{'plan':plan})
    if mode == 'crash':
        import gis_agent.core.replay as module
        original_write = module.write_json
        def kill():
            signal.raise_signal(signal.SIGTERM)
        def write(path, value):
            child = path.name.startswith('r_') and path.suffix == '.json'
            if (window == 'output' and child and value.get('state') == 'completed'
                or window == 'child' and path.name == 'result.json' and path.parent.name == 'repair'):
                kill()
            original_write(path,value)
            if (window == 'plan' and path.name == 'plan.json'
                or window == 'intent' and child and value.get('state') == 'started'
                or window == 'root' and path.name.startswith('root_') and value.get('state') == 'completed'):
                kill()
        module.write_json = write
        if window == 'session':
            original_save = store.save
            def save(messages):
                original_save(messages)
                if messages[-1].get('tool_name') == 'local_replay':
                    kill()
            store.save = save
    with SqliteSaver.from_conn_string(str(root/'checkpoint.sqlite')) as saver:
        agent = make_graph_agent(store, model, make_token_counter(ModelConfig(tokenizer='bytes')), saver, (python,local))
        agent.history = history
        try:
            if mode == 'resume':
                result = agent.resume(store.read_record())
            else:
                result = agent.run([*store.load(),{'role':'user','origin':'user','content':'Correct the late script'}])
        except (ValueError, OSError) as error:
            (root/'resume.json').write_text(json.dumps({'status':'refused','error':str(error)}))
        else:
            (root/'resume.json').write_text(json.dumps(result))


if __name__ == '__main__':
    main()
