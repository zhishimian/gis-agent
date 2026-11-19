"""One-command GeoAgentBench runner. All reference material stays outside agent workspaces.

Usage (from project root):
  D:/ac/envs/gis-agent/python.exe benchmarks/geoagentbench/run.py run --run-dir outputs/gab_v0_NAME
  ... run --run-dir outputs/gab_v0_NAME --ids 4,9 --resume
  ... run --run-dir outputs/gab_v0_NAME --rerun-failed
  ... evaluate --run-dir outputs/gab_v0_NAME
New reruns create attempt directories. They never replace the baseline attempt.
"""
import argparse
import concurrent.futures
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.geoagentbench.common import *


def initialize(run, args):
    if (run / 'config.json').exists():
        spec = load(run / 'config.json')
        if frozen_sources() != spec['source_hashes']:
            raise Protection('Product source differs from frozen baseline')
        return spec
    run.mkdir(parents=True, exist_ok=True)
    _, url, model = credentials(args.credential_reference)
    spec = {'created': now(), 'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip(),
            'source_hashes': frozen_sources(), 'model': model, 'base_url': url,
            'credential_reference': str(Path(args.credential_reference).resolve()),
            'max_output_tokens': 16384, 'max_calls': None, 'task_seconds': 1800,
            'task_budget_cny': 4., 'budget_cny': args.budget_cny, 'workers': args.workers,
            'standalone': bool(args.standalone),
            'pricing': {'verified': '2026-11-10', 'input_peak_per_million': 2, 'cached_peak_per_million': .2,
                        'output_peak_per_million': 8, 'peak_hours_beijing': '08:00-22:00',
                        'sources': ['https://help.aliyun.com/zh/model-studio/model-pricing',
                                    'https://help.aliyun.com/zh/model-studio/context-cache']},
            'memory': 'disabled; isolated tasks', 'sdk_retries': 0,
            'extra_python_packages': 'standalone uv .venv GeoPython (42 packages, no desktop QGIS)' if args.standalone else 'not connected; original QGIS Python environment only',
            'evaluation': 'outcomes first; no automatic tool-sequence or VLM correctness score'}
    save(run / 'config.json', spec)
    for relative in spec['source_hashes']:
        target = run / 'snapshot' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / relative, target)
    save(run / 'source-material-hashes.json', {str(p): digest(p) for p in [
        MATERIALS / 'geoagentbench-questions-only.json', MATERIALS / 'geoagentbench-index-organizer.json',
        SOURCE / 'benchmark/benchmark.csv']})
    (run / 'environment/python').mkdir(parents=True, exist_ok=True)
    return spec


def prepare(run, identifier, phase='tasks', attempt=1):
    task = next(t for t in load(MATERIALS / 'geoagentbench-questions-only.json') if t['id'] == str(identifier))
    index = next(t for t in load(MATERIALS / 'geoagentbench-index-organizer.json') if t['id'] == str(identifier))
    work = run / phase / f'{int(identifier):02d}' / f'attempt_{attempt:02d}'
    if (work / 'input-manifest.json').exists():
        return work
    work.mkdir(parents=True, exist_ok=True)
    manifest = []
    for relative, source in index['resolved_inputs'].items():
        if not relative.startswith('dataset/') or Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise ValueError('Unexpected input path')
        # Defensive exclusion: no reference output directory can enter an agent workspace.
        if relative.startswith('dataset/result/'):
            raise ValueError('Reference output classified as input')
        destination = work / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        manifest.append({'relative': relative, 'bytes': destination.stat().st_size, 'sha256': digest(destination)})
        if destination.suffix.lower() == '.shp':
            # Preserve optional projection/encoding/index files when supplied.
            for suffix in ('.prj', '.cpg', '.qix', '.sbn', '.sbx', '.shp.xml'):
                relative_sidecar = Path(relative).with_suffix(suffix)
                supplemented = MATERIALS / 'supplement/GABench' / relative_sidecar
                original = supplemented if supplemented.is_file() else SOURCE / relative_sidecar
                if original.is_file():
                    sidecar = destination.with_suffix(suffix)
                    shutil.copyfile(original, sidecar)
                    manifest.append({'relative': sidecar.relative_to(work).as_posix(), 'bytes': sidecar.stat().st_size, 'sha256': digest(sidecar)})
    for name in ('output', 'temp', 'records'):
        (work / name).mkdir(exist_ok=True)
    save(work / 'input-manifest.json', manifest)
    prompt = ('Complete the following GIS task using the supplied local inputs. Choose your own tools and code.\n\n'
              + task['task'] + '\n\nInput descriptions:\n' + task['data']
              + '\n\nRequested drawing style:\n' + task['drawing_style']
              + '\n\nRuntime paths:\nWorking directory: ' + str(work)
              + '\nThe dataset/... paths above are relative to this working directory. Use absolute paths when calling tools.'
              + '\nOutput directory: ' + str(work / 'output')
              + '\nAvailable input files:\n' + '\n'.join(str(work / x['relative']) for x in manifest)
              + '\n\nKeep the scripts and analytical data you produce so the results can be inspected. '
                'State material assumptions and any incomplete requirements in your final delivery. '
                'Only the supplied data and installed tools/libraries are available; no external network access or follow-up human input is available during this run.')
    (work / 'prompt.txt').write_text(prompt, encoding='utf-8')
    return work


def task_run(work, run, spec, resume=False):
    status = work / 'status.json'
    if status.exists():
        return load(status)
    if (work / 'records/started.json').exists() and not resume:
        return {'id': work.parent.name, 'status': 'interrupted_requires_resume'}
    if not (work / 'records/started.json').exists():
        save(work / 'records/started.json', {'time': now()})
    begin = time.perf_counter()
    with (work / 'records/worker.log').open('ab') as log:
        proc = subprocess.Popen([str(HOST), '-B', str(Path(__file__).with_name('worker.py')), str(work), str(run)],
                                cwd=work, stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                env=os.environ | {'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'})
        timed_out = False
        try:
            code = proc.wait(timeout=spec['task_seconds'] + 120)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
            code, timed_out = -1, True
    result = load(work / 'records/result.json') if (work / 'records/result.json').exists() else None
    error = load(work / 'records/error.json') if (work / 'records/error.json').exists() else None
    changed = [x['relative'] for x in load(work / 'input-manifest.json') if not (work / x['relative']).is_file()
               or digest(work / x['relative']) != x['sha256']]
    row = {'id': work.parent.name, 'attempt': work.name, 'returncode': code, 'timeout': timed_out,
           'elapsed_seconds': time.perf_counter() - begin, 'result': result, 'error': error,
           'input_changed': changed, 'status': 'timeout' if timed_out else
           (result['outcome'].get('status', 'unknown') if result else
            'protection_stop' if error and error.get('type')=='Protection' else 'infrastructure_error'), 'ended': now()}
    save(status, row)
    print(json.dumps({'task': row['id'], 'attempt': work.name, 'status': row['status'],
                      'seconds': round(row['elapsed_seconds'], 1)}, ensure_ascii=True), flush=True)
    return row


def probe(run):
    from openai import OpenAI, DefaultHttpxClient
    from gis_agent.integrations.llm import chat
    from gis_agent.core.model import ModelConfig
    from PIL import Image
    spec = load(run / 'config.json')
    key, url, model = credentials(spec['credential_reference'])
    ledger = Ledger(run / 'ledger.sqlite', spec['budget_cny'])
    replies = []
    messages = [{'role': 'user', 'content': 'Compatibility test only. Call echo with text="ok". After its result, reply briefly.'}]
    schemas = [{'type': 'function', 'function': {'name': 'echo', 'description': 'Echo a test string',
                 'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}}]
    cfg = ModelConfig(model=model, base_url=url, max_tokens=1024)
    with OpenAI(api_key=key, base_url=url, max_retries=0, timeout=90,
                http_client=DefaultHttpxClient(trust_env=False)) as client:
        for i in range(2):
            reservation = ledger.reserve('connection_probe', .05)
            start = now()
            r = chat(client, cfg, messages, schemas)
            cost = costs(r.usage or {}, start, now())
            ledger.settle(reservation, cost['peak_cny'], cost)
            replies.append({'reply': r.message, 'usage': r.usage, 'cost': cost, 'model': r.model})
            messages.append(r.message)
            if i == 0:
                calls = r.message.get('tool_calls') or []
                if not calls or calls[0]['function']['name'] != 'echo':
                    raise ValueError('Provider did not produce expected function call')
                for call in calls:
                    messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': '{"ok":true,"text":"ok"}'})
        # Real image/tool compatibility, no benchmark answers involved.
        import base64, io
        image = Image.new('RGB', (16, 16), 'red')
        buffer = io.BytesIO(); image.save(buffer, format='PNG')
        reservation = ledger.reserve('connection_probe', .05)
        start = now()
        reply = client.chat.completions.create(model=model, max_tokens=128, messages=[{'role':'user','content':[
            {'type':'text','text':'What is the main color? One word.'},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()}}]}])
        cost = costs(reply.usage.model_dump(), start, now()); ledger.settle(reservation, cost['peak_cny'], cost)
        replies.append({'vision':reply.choices[0].message.content,'usage':reply.usage.model_dump(),'cost':cost})
    save(run / 'connection-probe.json', replies)
    print('Provider function-call round trip and image input verified; credentials were not logged.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'probe', 'run', 'evaluate'])
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--ids', default='all')
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--rerun-failed', action='store_true')
    parser.add_argument('--resume-infra', action='store_true', help='Resume only a transport-interrupted original Session, at most twice')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--budget-cny', type=float, default=50., help='New runs only; existing config budget is preserved')
    parser.add_argument('--no-evaluate', action='store_true', help='Additional scheduler joins a running batch; evaluate after the whole batch')
    parser.add_argument('--standalone', action='store_true', help='Use standalone .venv GeoPython without desktop QGIS')
    parser.add_argument('--credential-reference', default='E:/vscode/bishe/1.py')
    args = parser.parse_args()
    if args.budget_cny<=0 or not math.isfinite(args.budget_cny):
        parser.error('--budget-cny must be finite and positive')
    run = args.run_dir.resolve()
    spec = initialize(run, args)
    ids = list(range(1, 54)) if args.ids == 'all' else [int(x) for x in args.ids.split(',')]
    if any(x < 1 or x > 53 for x in ids):
        parser.error('Task IDs must be 1..53')
    if args.command == 'probe':
        probe(run); return
    if args.command == 'evaluate':
        from benchmarks.geoagentbench.evaluate import evaluate
        evaluate(run); return
    jobs = []
    for identifier in ids:
        phase = 'pilot' if args.pilot else 'tasks'
        base = run / phase / f'{identifier:02d}'
        attempt = 1
        if args.resume_infra:
            work=base/'attempt_01';status=work/'status.json';error_path=work/'records/error.json'
            if not status.exists() or load(status)['status']!='infrastructure_error' or not error_path.exists():
                continue
            error=load(error_path)
            if error.get('type')!='ModelError' or not any(x in error.get('message','').lower() for x in ['connection','timeout','timed out','429','502','503','504']):
                continue
            recoveries=list((work/'records').glob('infra-recovery-*/status.json'))
            if len(recoveries)>=2:continue
            archive=work/'records'/f'infra-recovery-{len(recoveries)+1:02d}'
            archive.mkdir(parents=True,exist_ok=False)
            shutil.move(status,archive/'status.json')
            for path in [error_path,work/'records/exception.txt']:
                if path.exists():shutil.move(path,archive/path.name)
            jobs.append(work)
            continue
        if args.rerun_failed:
            previous = sorted(base.glob('attempt_*/status.json'))
            if not previous or load(previous[-1])['status'] == 'completed':
                continue
            attempt = max(int(p.parent.name.split('_')[-1]) for p in previous) + 1
        jobs.append(prepare(run, identifier, phase, attempt))
    if args.command == 'prepare':
        print(f'Prepared {len(jobs)} isolated task workspaces.'); return
    if not (run / 'connection-probe.json').exists():
        probe(run)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(task_run, w, run, spec, args.resume or args.resume_infra) for w in jobs]
        for f in concurrent.futures.as_completed(futures):
            f.result()
    index_name='pilot-index.json' if args.pilot else ('additional-index-'+args.ids.replace(',','-')+'.json' if args.no_evaluate else 'run-index.json')
    if (run/index_name).exists():
        # Retain previous admission batches, including empty resume invocations.
        import time
        index_name=Path(index_name).stem+f'-{time.time_ns()}.json'
    save(run / index_name,
         [load(w / 'status.json') for w in jobs if (w / 'status.json').exists()])
    if not args.pilot and not args.no_evaluate:
        from benchmarks.geoagentbench.evaluate import evaluate
        evaluate(run)


if __name__ == '__main__':
    main()
