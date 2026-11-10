"""Outcome evidence and conservative triage. Human reviews require cited evidence."""
import collections
import csv
import json
import re
import subprocess
from pathlib import Path
from benchmarks.geoagentbench.common import *

LABELS={'correct','partial','wrong','uncertain','infrastructure_error'}


def probe(command, timeout=180):
    process=subprocess.Popen(command,cwd=PROJECT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        stdout,stderr=process.communicate(timeout=timeout)
        return process.returncode,stderr.decode('utf-8',errors='replace')[-3000:]
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
        process.communicate()
        return -1,'Read-only evaluator exceeded its time limit; correctness remains uncertain.'


def check_rule(result, output):
    _, kind, pattern, key, condition=result.split(':',4)
    matches=list(output.rglob(pattern))
    matches=[p for p in matches if 'python_logs' not in p.parts]
    if len(matches)!=1:
        return {'passed':False,'reason':'Missing or ambiguous required result','matches':list(map(str,matches))}
    p=matches[0]
    value=load(p).get(key) if kind=='JSON_VALUE' else next(csv.DictReader(p.open(encoding='utf-8-sig'))).get(key)
    if condition.lower()=='==true':passed=value is True
    elif condition.lower()=='==false':passed=value is False
    elif condition=='EXISTS':passed=value is not None
    else:
        match=re.fullmatch(r'(<=|>=|==|!=|<|>)(-?[\d.]+)',condition)
        if not match:raise ValueError('Unsupported condition')
        import operator
        passed={'<':operator.lt,'>':operator.gt,'<=':operator.le,'>=':operator.ge,'==':operator.eq,'!=':operator.ne}[match[1]](float(value),float(match[2]))
    return {'passed':bool(passed),'path':str(p),'key':key,'value':value,'condition':condition,
            'scope':'Specified field only. Does not establish full scientific correctness.'}


def trace(work):
    file=work/'records/sessions/task.json'
    if not file.exists():return {'calls':[],'failures':[],'skills':{}}
    messages=load(file)
    calls=[];failures=[];pending={};skills=collections.defaultdict(list);response=0
    for message in messages:
        if message['role']=='assistant' and message.get('tool_calls'):
            response+=1
            for call in message['tool_calls']:
                try:args=json.loads(call['function']['arguments'])
                except (ValueError,TypeError):args={'unparsed':call['function']['arguments']}
                item={'response':response,'tool':call['function']['name'],'arguments':args,'id':call['id']}
                calls.append(item);pending[call['id']]=item
        elif message['role']=='tool':
            item=pending.pop(message['tool_call_id'],{'response':response,'tool':message.get('name'),'id':message['tool_call_id']})
            if message.get('asset'):
                try:result=load(work/'records/sessions'/message['asset']['path'])
                except Exception as e:result={'asset_error':str(e)}
            else:
                try:result=json.loads(message['content'])
                except (ValueError,TypeError):result=message['content']
            item.update(result=result,execution_id=message.get('execution_id'))
            if isinstance(result,dict) and result.get('ok') is False:failures.append(item)
            path=str(item.get('arguments',{}).get('path','')).replace('\\','/')
            if item.get('tool')=='read_file' and '/skills/' in path and isinstance(result,dict) and result.get('ok'):
                skills[path.split('/skills/',1)[1].split('/',1)[0]].append({'response':item['response'],'path':path})
    save(work/'evaluation/tool-calls.json',calls)
    save(work/'evaluation/failures.json',failures)
    return {'calls':calls,'failures':failures,'skills':dict(skills),'session_messages':len(messages)}


def evaluate(run):
    spec=load(run/'config.json')
    if spec.get('defer_evaluation_until_finalized') and not (run/'formal-grading-ready.json').exists():
        save(run/'evaluation-deferred.json',{'time':now(),'reason':'Wait for all supervisors and permitted original-Session infrastructure resumes before scoring.'})
        return
    questions=load(MATERIALS/'geoagentbench-index-organizer.json')
    reviews=load(run/'reviews.json') if (run/'reviews.json').exists() else {}
    results=[]
    for task in questions:
        work=run/'tasks'/f"{int(task['id']):02d}"/'attempt_01'
        if not (work/'status.json').exists():continue
        status=load(work/'status.json')
        (work/'evaluation').mkdir(exist_ok=True)
        if not (work/'evaluation/inventory.json').exists():
            code,stderr=probe(['E:/exe/qgis/bin/python-qgis-ltr.bat',str(Path(__file__).with_name('inventory.py')),str(work)])
            if code:save(work/'evaluation/inventory-error.json',{'returncode':code,'stderr':stderr})
        evidence=trace(work)
        usage=load(work/'records/usage.json') if (work/'records/usage.json').exists() else []
        inventory=load(work/'evaluation/inventory.json') if (work/'evaluation/inventory.json').exists() else []
        if int(task['id']) in {7,21,22,30,34,41,44,46,47,48,52} and not (work/'evaluation/scientific-checks.json').exists():
            code,stderr=probe(['E:/exe/qgis/bin/python-qgis-ltr.bat',str(Path(__file__).with_name('scientific_checks.py')),str(work),task['id']])
            if code:
                save(work/'evaluation/scientific-error.json',{'returncode':code,'stderr':stderr})
        received=[x for x in usage if x.get('state')=='received' or 'input_tokens' in x]
        archives=list((work/'records').glob('infra-recovery-*/status.json'))
        active_elapsed=status['elapsed_seconds']+sum(load(p).get('elapsed_seconds',0) for p in archives)
        result={'id':task['id'],'domain':task['domain'],'execution_status':status['status'],
                'label':'uncertain','confidence':'low','basis':['Requires outcome review; file existence alone does not establish correctness.'],
                'expected':task['result'],'elapsed_seconds':active_elapsed,
                'attempted_requests':len(usage),'responses':len(received),'tool_calls':len(evidence['calls']),'tool_failures':len(evidence['failures']),
                'skills_read':evidence['skills'],
                'execution_history_calls':sum(x['tool']=='execution_history' for x in evidence['calls']),
                'local_replay_calls':sum(x['tool']=='local_replay' for x in evidence['calls']),
                'usage':{k:sum(x.get(k,0) or 0 for x in usage) for k in ['input_tokens','cached_tokens','output_tokens','reasoning_tokens','estimated_cny','peak_cny','no_cache_peak_cny']},
                'inventory':inventory,'directory':str(work)}
        if (work/'evaluation/scientific-checks.json').exists():
            result['scientific_checks']=load(work/'evaluation/scientific-checks.json')
        if task['result'].startswith('CHECK:'):
            try:result['objective_rule']=check_rule(task['result'],work/'output')
            except Exception as e:result['objective_rule']={'passed':False,'error':str(e)}
        elif task['id']=='9':
            matches=list((work/'output').rglob('deforestation_rate.csv'))
            if len(matches)==1:
                reference=SOURCE/'dataset/result/deforestation_rate.csv'
                ref=float(next(csv.DictReader(reference.open(encoding='utf-8-sig')))['percentage_deforestation'])
                result['reference_numeric']={'reference_value':ref,'candidate_csv':matches[0].read_text(encoding='utf-8-sig')[:4000],
                                             'scope':'Compare semantics, units and denominator before deciding'}
        if status['status']=='infrastructure_error':
            result.update(label='infrastructure_error',basis=[status.get('error')],confidence='high')
        if task['id'] in reviews:
            review=reviews[task['id']]
            if review['label'] not in LABELS:raise ValueError('Unknown review label')
            result.update(review)
        save(work/'evaluation/score.json',result)
        results.append(result)
    save(run/'results.json',results)
    summary={'tasks':len(results),'labels':dict(collections.Counter(x['label'] for x in results)),
             'execution_status':dict(collections.Counter(x['execution_status'] for x in results)),
             'objective_rules':{x['id']:x['objective_rule'] for x in results if 'objective_rule' in x},
             'responses':sum(x['responses'] for x in results),'tools':sum(x['tool_calls'] for x in results),
             'tool_failures':sum(x['tool_failures'] for x in results),
             'costs':{key:sum(x['usage'][key] for x in results) for key in ['estimated_cny','peak_cny','no_cache_peak_cny']},
             'source_unchanged':frozen_sources()==spec['source_hashes']}
    save(run/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=True),flush=True)
