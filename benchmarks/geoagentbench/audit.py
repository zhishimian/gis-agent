"""Post-run evidence audit, accounting and immutable artifact inventory."""
import collections
from datetime import datetime
from pathlib import Path
from benchmarks.geoagentbench.common import *


def audit(run):
    if not (run/'formal-grading-ready.json').exists():
        raise ValueError('Run and permitted infrastructure recovery must finish first')
    spec=load(run/'config.json');task_rows=[];totals=collections.Counter();phase_totals={}
    key,_,_=credentials(spec['credential_reference'])
    secret=key.encode();leaks=[];frozen={};changed_inputs=[]
    for phase in ['tasks','pilot']:
        phase_totals[phase]=collections.Counter()
        for work in sorted((run/phase).glob('*/attempt_*')):
            usage=load(work/'records/usage.json') if (work/'records/usage.json').exists() else []
            counts=collections.Counter()
            for row in usage:
                counts['attempted_requests']+=1
                counts['received_requests']+=row.get('state')=='received'
                counts['transport_failures']+=row.get('state')=='transport_error'
                for field in ['input_tokens','cached_tokens','output_tokens','reasoning_tokens','peak_cny','estimated_cny','no_cache_peak_cny']:
                    counts[field]+=row.get(field,0) or 0
                if row.get('state')!='received':counts['unknown_usage_reserved_cny']+=row['reserved_cny']
            phase_totals[phase].update(counts)
            for p in (work/'records').rglob('*'):
                if p.is_file() and p.suffix.lower() in {'.json','.jsonl','.log','.txt'}:
                    with p.open('rb') as f:
                        carry=b''
                        for data in iter(lambda:f.read(1024*1024),b''):
                            block=carry+data
                            if secret in block:leaks.append(str(p.relative_to(run)));break
                            carry=block[-len(secret):]
            if phase=='tasks':
                status=load(work/'status.json')
                archives=[load(p) for p in (work/'records').glob('infra-recovery-*/status.json')]
                first=archives[0] if archives else status
                active=status['elapsed_seconds']+sum(x['elapsed_seconds'] for x in archives)
                first_start=load(work/'records/started.json')['time']
                span=(datetime.fromisoformat(status['ended'])-datetime.fromisoformat(first_start)).total_seconds()
                task_rows.append({'id':work.parent.name,'first_pass_status':first['status'],
                    'final_status':status['status'],'infrastructure_resumes':len(archives),'active_process_seconds':active,
                    'wall_span_seconds':span,'usage':dict(counts)})
                for item in load(work/'input-manifest.json'):
                    p=work/item['relative']
                    if not p.is_file() or digest(p)!=item['sha256']:changed_inputs.append(str(p))
                for p in (work/'output').rglob('*'):
                    if p.is_file() and '__pycache__' not in p.parts:
                        frozen[p.relative_to(run).as_posix()]={'bytes':p.stat().st_size,'sha256':digest(p)}
    with Ledger(run/'ledger.sqlite',spec['budget_cny']).connect() as db:
        ledger=[{'id':a,'task':b,'reserved_cny':c,'settled_cny':d,'metadata':json.loads(e) if e else None}
                for a,b,c,d,e in db.execute('SELECT id,task,reserved,settled,metadata FROM charges ORDER BY id')]
    save(run/'audit/ledger.json',ledger)
    save(run/'audit/output-frozen.json',frozen)
    report={'time':now(),'product_source_unchanged':frozen_sources()==spec['source_hashes'],
        'changed_inputs':changed_inputs,'credential_literal_matches_in_logs':leaks,
        'phase_totals':{k:dict(v) for k,v in phase_totals.items()},'tasks':task_rows,
        'first_pass_status':dict(collections.Counter(t['first_pass_status'] for t in task_rows)),
        'final_status':dict(collections.Counter(t['final_status'] for t in task_rows)),
        'budget_limit_cny':spec['budget_cny'],'conservative_settled_and_unreconciled_reserved_cny':sum(x['settled_cny'] if x['settled_cny'] is not None else x['reserved_cny'] for x in ledger),
        'files_frozen':len(frozen),'frozen_output_bytes':sum(v['bytes'] for v in frozen.values()),
        'billing_statement_checked':False}
    save(run/'audit/summary.json',report)
    return report
