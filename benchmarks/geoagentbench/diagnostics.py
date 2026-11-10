"""Descriptive post-run diagnostics. Categories are evidence tags, not causal verdicts."""
import collections
import json
from pathlib import Path
from benchmarks.geoagentbench.common import load, save


PATTERNS = {
    'environment_missing_dependency': ['modulenotfounderror','no module named','importerror','cannot import name'],
    'crs_units': ['crserror','projerror','invalid projection','crs mismatch','crs不','坐标系'],
    'io_schema': ['drivererror','data source','datasource','not recognized as a supported','field not found','keyerror','no such file','filenotfound','cannot open','无法读取','字段'],
    'api_or_parameters': ['typeerror','attributeerror','unexpected keyword','invalid parameter','missing required','参数'],
    'code_runtime': ['syntaxerror','nameerror','indexerror','valueerror','zerodivisionerror'],
    'experiment_scope': ['benchmark scope','benchmark file outside','benchmark mutation','benchmark subprocess','network disabled'],
    'resource_limits': ['memoryerror','timed out','timeout','request count','budget','protection'],
}


def diagnose(run):
    results=load(run/'results.json')
    counts=collections.Counter();per_task=[];skill_counts=collections.Counter();assets=collections.defaultdict(list)
    for task in results:
        work=Path(task['directory']);calls=load(work/'evaluation/tool-calls.json')
        errors=load(work/'evaluation/failures.json');tags=collections.Counter()
        for error in errors:
            text=json.dumps(error.get('result'),ensure_ascii=False).lower()
            matches=[name for name,words in PATTERNS.items() if any(word in text for word in words)]
            for name in matches or ['other_tool_failure']:tags[name]+=1;counts[name]+=1
        used=set()
        # Static code evidence is marked as such. It does not alone prove runtime use.
        for script in (work/'output').rglob('*.py'):
            if 'python_logs' in script.parts:continue
            text=script.read_text(encoding='utf-8',errors='replace')
            for marker in ['gis_agent.plotting','configure_plotting','export_figure','classify_values','network_cases',
                           'geometry_facts','identity_audit','allocation_balance','run_processing','staged_compute']:
                if marker in text:used.add(marker)
        for name in task['skills_read']:skill_counts[name]+=1
        for marker in used:assets[marker].append(task['id'])
        signature=collections.Counter((c['tool'],json.dumps(c.get('arguments'),sort_keys=True)) for c in calls)
        per_task.append({'id':task['id'],'error_tags':dict(tags),'skills_read':task['skills_read'],
                         'script_asset_markers':sorted(used),'repeated_identical_calls':sum(n-1 for n in signature.values() if n>1),
                         'toolchain':[{'response':c['response'],'tool':c['tool'],'execution_id':c.get('execution_id'),
                                       'failed':isinstance(c.get('result'),dict) and c['result'].get('ok') is False} for c in calls]})
    result={'error_tag_counts_overlapping':dict(counts),'tasks_reading_each_skill':dict(skill_counts),
            'script_asset_markers':dict(assets),'tasks':per_task,
            'limits':'Error tags can overlap. Missing a Skill read does not establish discovery failure. Static code markers need runtime correlation.'}
    save(run/'diagnostics.json',result)
    return result
