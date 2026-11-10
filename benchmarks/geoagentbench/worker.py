"""One independent Agent session. Called by run.py, never solves benchmark tasks."""
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.geoagentbench.common import *


def execute(work, run):
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    from openai import OpenAI, DefaultHttpxClient
    from langgraph.checkpoint.sqlite import SqliteSaver
    from gis_agent.application import AgentFactory
    from gis_agent.config import AppConfig
    from gis_agent.integrations.llm import chat, make_token_counter, request_view
    from gis_agent.integrations.qgis.client import QGISClient
    from gis_agent.integrations.qgis.catalog import load_catalog
    from gis_agent.persistence.sessions import SessionStore
    from gis_agent.prompts import render_prompt
    from gis_agent.skills import skill_index
    spec = load(run / 'config.json')
    if frozen_sources() != spec['source_hashes']:
        raise Protection('Frozen product source changed')
    work, run = work.resolve(), run.resolve()
    record = work / 'records'
    record.mkdir(parents=True, exist_ok=True)
    def event(kind, **values):
        with (record / 'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({'time': now(), 'kind': kind, **values}, ensure_ascii=False, default=str) + '\n')
    logging.basicConfig(filename=record / 'runtime.log', encoding='utf-8', level=logging.INFO)
    key, url, model_name = credentials(spec['credential_reference'])
    config = AppConfig.from_env(PROJECT)
    model = replace(config.model, base_url=url, model=model_name, max_tokens=spec['max_output_tokens'],
                    provider='deepseek', context_window=1048576, supports_images=True)
    wrapper = record / 'python-isolated.bat'
    wrapper.write_text('@echo off\r\ncall "' + str(config.qgis.python_launcher) + '" -B "' +
                       str(Path(__file__).with_name('child_entry.py')) + '" %*\r\n', encoding='utf-8')
    config = replace(config, model=model, session_root=record / 'sessions', output_root=work,
                     memory=None, max_retries=0, qgis=replace(config.qgis, python_launcher=wrapper),
                     context=replace(config.context, request_token_limit=350000))
    for name in ('TEMP', 'TMP'):
        os.environ[name] = str(work / 'temp')
    os.environ.update(GAB_WORK=str(work), GAB_PROJECT=str(PROJECT), GAB_EXTRA=str(run / 'environment/baseline-empty'),
                      MPLCONFIGDIR=str(work / 'temp/matplotlib'), PROJ_NETWORK='OFF')
    # Credential is held only in the host client. Children never inherit a model key.
    for name in list(os.environ):
        if any(s in name.upper() for s in ('API_KEY', 'ACCESS_KEY', 'SECRET')):
            os.environ.pop(name, None)
    ledger = Ledger(run / 'ledger.sqlite', spec['budget_cny'])
    task_key = work.relative_to(run).as_posix()
    rows = load(record / 'usage.json') if (record / 'usage.json').exists() else []
    started = time.perf_counter()
    with OpenAI(api_key=key, base_url=url, max_retries=0, timeout=180,
                http_client=DefaultHttpxClient(trust_env=False)) as client:
        del key
        def metered(messages, schemas, _transport_retry=True):
            if len(rows) >= spec['max_calls'] or time.perf_counter() - started > spec['task_seconds']:
                raise Protection('Task request count or elapsed-time protection')
            view, images = request_view(messages, model)
            input_upper = len(json.dumps({'messages': view, 'tools': schemas}, ensure_ascii=False).encode('utf-8')) + 16384 + 64 * len(messages) + images * 65536
            reserve = (input_upper * 2 + model.max_tokens * 8) / 1e6
            identifier = ledger.reserve(task_key, reserve, spec['task_budget_cny'])
            number = len(rows) + 1
            row = {'number': number, 'started': now(), 'state': 'sending', 'reserved_cny': reserve, 'ledger_id': identifier}
            rows.append(row)
            save(record / 'usage.json', rows)
            save(record / f'requests/{number:04d}.json', {'model': model.model, 'messages': view, 'tools': schemas, 'max_tokens': model.max_tokens})
            t = time.perf_counter()
            # Limited transport retries only; every attempt has its own reservation and log.
            try:
                reply = chat(client, model, messages, schemas)
            except Exception as error:
                row.update(state='transport_error', error_type=type(error).__name__,
                           elapsed_seconds=time.perf_counter()-t)
                save(record/'usage.json',rows)
                event('model_transport_error',number=number,retry=bool(_transport_retry and retryable_transport(error)))
                if _transport_retry and retryable_transport(error):
                    time.sleep(2)
                    return metered(messages,schemas,False)
                raise
            ended = now()
            measured = costs(reply.usage or {}, row['started'], ended)
            ledger.settle(identifier, measured['peak_cny'], measured)
            row.update(state='received', ended=ended, elapsed_seconds=time.perf_counter() - t,
                       usage=reply.usage, model=reply.model, finish_reason=reply.finish_reason, **measured)
            save(record / f'replies/{number:04d}.json', reply.message)
            save(record / 'usage.json', rows)
            event('model_response', number=number, tools=[x['function']['name'] for x in reply.message.get('tool_calls') or []], cost_cny=measured['estimated_cny'])
            return reply

        qgis = QGISClient(config.qgis.process_launcher)
        catalog = load_catalog(qgis)
        store = SessionStore(config.session_root, 'task')
        store.root.mkdir(parents=True, exist_ok=True)
        messages = store.read_record()
        with SqliteSaver.from_conn_string(str(record / 'checkpoint.sqlite')) as saver:
            prompt = render_prompt('system.j2', output_dir=work / 'output', supports_images=True,
                                   supports_memory=False, skills=skill_index())
            (record / 'system_prompt.txt').write_text(prompt, encoding='utf-8')
            save(record / 'runtime_config.json', {'model': asdict(model), 'context': asdict(config.context),
                 'sdk_retries': 0, 'explicit_transport_retry':1, 'memory': False, 'head': spec['head'], 'scope': 'File/tool guards, not an OS sandbox'})
            agent = AgentFactory(config, metered, make_token_counter(model), qgis, catalog).create(
                store, messages, work / 'output', saver, prompt)
            base_execute = agent.registry.execute
            repeated = []
            def observed(name, args):
                def check(value, writing=False):
                    if isinstance(value, str) and Path(value.split('|')[0]).is_absolute():
                        p = Path(value.split('|')[0]).resolve()
                        roots = [work / 'output', work / 'temp', work / 'scripts'] if writing else [work, PROJECT / 'gis_agent']
                        return any(p == r or p.is_relative_to(r) for r in roots)
                    if isinstance(value, (list, tuple)):
                        return all(check(v, writing) for v in value)
                    if isinstance(value, dict):
                        return all(check(v, writing) for v in value.values())
                    return True
                if not check(args, name in {'write_file', 'edit_file'}):
                    event('scope_refused', tool=name)
                    return {'ok': False, 'error': 'Benchmark scope: current inputs, outputs and GIS-Agent technical resources only.'}
                event('tool_start', tool=name, arguments=args)
                begin = time.perf_counter()
                result = base_execute(name, args)
                failed = isinstance(result, dict) and result.get('ok') is False
                event('tool_end', tool=name, failed=failed, elapsed_seconds=time.perf_counter() - begin)
                signature = json.dumps([name, args], sort_keys=True, ensure_ascii=False) if failed else None
                repeated.append(signature)
                if signature and len(repeated) >= 5 and all(s == signature for s in repeated[-5:]):
                    raise Protection('Five identical consecutive tool failures')
                return result
            agent.registry.execute = observed
            save(record / 'tool_schemas.json', agent.registry.schemas())
            event('agent_start')
            if messages:
                result = agent.resume(messages)
            else:
                messages.append({'role': 'user', 'origin': 'user', 'content': (work / 'prompt.txt').read_text(encoding='utf-8')})
                result = agent.run(messages)
            save(record / 'result.json', {'outcome': result, 'elapsed_seconds': time.perf_counter() - started, 'ended': now()})
            event('agent_end', status=result.get('status'))


def locked_execute(work,run):
    """One writer per original Session, including overlapping supervisor queues."""
    import msvcrt
    lock=work/'records/worker.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+b') as stream:
        stream.seek(0);stream.write(b'1');stream.flush()
        deadline=time.monotonic()+1900
        while True:
            try:
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1);break
            except OSError:
                if time.monotonic()>deadline:raise Protection('Timed out waiting for current Session writer')
                time.sleep(1)
        try:
            if (work/'records/result.json').exists():return
            while (run/'infrastructure-pause.json').exists():
                time.sleep(5)
            # Admission only: do not interrupt an already running native GIS operation.
            import ctypes
            class Memory(ctypes.Structure):
                _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),
                          *[(name,ctypes.c_ulonglong) for name in ['total','available','page_total','page_available','virtual_total','virtual_available','extended']]]
            minimum=1536*1024**2 if work.parent.name.isdigit() and int(work.parent.name) in range(47,53) else 768*1024**2
            waiting=None
            while True:
                memory=Memory();memory.length=ctypes.sizeof(memory)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))
                if memory.available>=minimum:break
                if waiting is None:
                    waiting=now();save(work/'records/resource-wait.json',{'started':waiting,'minimum_free_bytes':minimum})
                time.sleep(5)
            if waiting:
                save(work/'records/resource-wait.json',{'started':waiting,'ended':now(),'minimum_free_bytes':minimum})
            execute(work,run)
        finally:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


if __name__ == '__main__':
    work, run = map(Path, sys.argv[1:3])
    try:
        locked_execute(work, run)
    except Exception as error:
        save(work / 'records/error.json', {'type': type(error).__name__, 'message': str(error), 'ended': now()})
        (work / 'records/exception.txt').write_text(traceback.format_exc(), encoding='utf-8')
        sys.exit(1)
