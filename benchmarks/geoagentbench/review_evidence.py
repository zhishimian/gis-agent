"""Aggregate factual trace evidence after generation, without model calls."""
import collections
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from benchmarks.geoagentbench.common import load,save


def run(root):
    all_calls=[];import_failures=[];counts=collections.Counter();skill_tasks=collections.defaultdict(set)
    history=[];purpose=collections.Counter();native=[]
    for work in sorted((root/'tasks').glob('*/attempt_01')):
        task=str(int(work.parent.name));calls=load(work/'evaluation/tool-calls.json')
        for call in calls:
            counts[call['tool']]+=1;all_calls.append((task,call))
            if call['tool']=='execution_history':history.append({'task':task,**call})
            result=call.get('result');text=json.dumps(result,ensure_ascii=False)
            if isinstance(result,dict) and result.get('ok') is False and re.search(r"No module named [\\\"']gis_agent(?:[\\\"']|\.)",text):
                import_failures.append({'task':task,'response':call['response'],'tool':call['tool'],
                                       'script':call.get('arguments'),'error_excerpt':text[-1600:]})
            path=str(call.get('arguments',{}).get('path','')).replace('\\','/')
            if call['tool']=='read_file' and '/skills/' in path and isinstance(result,dict) and result.get('ok'):
                name=path.split('/skills/',1)[1].split('/')[0];skill_tasks[name].add(task)
        logfile=work/'records/sessions/task.calls.jsonl'
        if logfile.exists():
            for line in logfile.read_text(encoding='utf-8-sig').splitlines():
                data=json.loads(line);purpose[str(data.get('purpose','unspecified'))]+=1
    result={'tool_counts':dict(counts),'call_log_purposes':dict(purpose),'skill_read_tasks':{k:sorted(v,key=int) for k,v in skill_tasks.items()},
            'package_import_failed_tool_returns':len(import_failures),'package_import_affected_tasks':sorted({x['task'] for x in import_failures},key=int),
            'package_import_failures':import_failures,'history_queries':history,
            'scope':'Import failures identify observed package errors; individual causation requires script/cwd evidence. Counts can overlap other diagnostic categories.'}
    save(root/'review-evidence.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in {'package_import_failures','history_queries'}},ensure_ascii=True,indent=2))


if __name__=='__main__':run(Path(sys.argv[1]).resolve())
