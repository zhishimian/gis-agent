import json
import hashlib
import os
from contextlib import contextmanager
import re
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from datetime import datetime, timezone
from typing import Any

from gis_agent.persistence.evidence import file_digest
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.json import write_json
from gis_agent.tools.files import edit_file


class ReplayError(ValueError):
    pass


LOCAL_ALGORITHMS = {'native:reprojectlayer', 'native:buffer', 'native:intersection',
                    'native:clip', 'native:dissolve', 'native:fixgeometries'}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def write_receipt(path: Path, record: dict) -> None:
    write_json(path, record | {'record_sha256': digest(record)})


def read_receipt(path: Path) -> dict:
    if path.is_symlink():
        raise ReplayError('关键回执不能通过链接读取。')
    record = json.loads(path.read_text(encoding='utf-8'))
    expected = record.pop('record_sha256', None)
    if not expected or digest(record) != expected:
        raise ReplayError(f'关键回执完整性校验失败：{path.name}')
    return record


@dataclass(frozen=True)
class ReplayStep:
    step_id: str
    source_execution: str
    inputs: dict
    changes: dict
    outputs: dict[str, str]


@dataclass(frozen=True)
class RepairPlan:
    repair_id: str
    parent_repair: str | None
    reason: str
    steps: tuple[ReplayStep, ...]
    targets: tuple[str, ...]
    accepted_inputs: dict

    @classmethod
    def parse(cls, value: dict) -> 'RepairPlan':
        try:
            if (not isinstance(value, dict) or not isinstance(value.get('steps'), list)
                    or not isinstance(value.get('targets'), list) or not isinstance(value.get('accepted_inputs'), dict)):
                raise ReplayError('steps/targets 必须是数组，accepted_inputs 必须是对象。')
            for step in value['steps']:
                if not isinstance(step, dict) or any(not isinstance(step.get(key), dict) for key in ('inputs', 'changes', 'outputs')):
                    raise ReplayError('阶段 inputs/changes/outputs 必须是对象。')
            return cls(**(value | {'steps': tuple(ReplayStep(**s) for s in value['steps']),
                                  'targets': tuple(value['targets'])}))
        except (TypeError, KeyError) as error:
            raise ReplayError(f'无效修复计划：{error}') from error


def local_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ReplayError('输出必须是修订目录内的相对文件名。')
    return path


def identifier(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', value):
        raise ReplayError('修订和阶段 ID 只允许 1 到 40 个字母、数字、下划线或横线。')


@contextmanager
def repair_lock(output_dir: Path, repair_id: str):
    identifier(repair_id)
    directory = output_dir.resolve() / 'repairs'
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() != directory:
        raise ReplayError('修订目录不能经链接重定向。')
    path = directory / f'.{repair_id}.lock'
    if path.is_symlink():
        raise ReplayError('锁文件不能是链接。')
    with path.open('a+b') as file:
        if path.stat().st_size == 0:
            file.write(b'0')
            file.flush()
        file.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ReplayError('同一修订仍在执行。') from error
            try:
                yield
            finally:
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ReplayError('同一修订仍在执行。') from error
            try:
                yield
            finally:
                fcntl.flock(file, fcntl.LOCK_UN)


def file_version(source: str) -> dict:
    path = Path(source).resolve()
    if path.drive.startswith('\\\\'):
        raise ReplayError('首版不封存网络共享输入。')
    if not path.is_file() or path.suffix.lower() not in {'.gpkg', '.tif', '.tiff', '.json', '.csv', '.npy', '.py'}:
        raise ReplayError(f'不支持的本地输入或文件不存在：{path}')
    if path.suffix.lower() == '.gpkg':
        if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise ReplayError(f'GeoPackage 存在活动日志：{path}')
        with sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True) as connection:
            if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ReplayError(f'GeoPackage 损坏：{path}')
            connection.execute('SELECT table_name FROM gpkg_contents LIMIT 1').fetchall()
    if path.suffix.lower() in {'.tif', '.tiff'}:
        with path.open('rb') as file:
            if file.read(4) not in {b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+'}:
                raise ReplayError(f'文件缺少 TIFF 标记：{path}')
        sidecars = [Path(str(path) + suffix) for suffix in ('.aux.xml', '.ovr', '.msk')]
        sidecars += [path.with_suffix(suffix) for suffix in ('.tfw', '.tifw', '.wld', '.aux.xml', '.prj', '.rpb', '.rpc')]
        sidecars += list(path.parent.glob(path.name + '.*'))
        if any(item.exists() for item in sidecars):
            raise ReplayError(f'栅格包含未封存的外部附属文件：{path}')
    return {'path': str(path), 'sha256': file_digest(path), 'size': path.stat().st_size}


def same_version(version: dict) -> bool:
    try:
        current = file_version(version['path'])
        return all(current[key] == version[key] for key in ('sha256', 'size'))
    except (OSError, ValueError, sqlite3.Error):
        return False


def order_steps(plan: RepairPlan, root: Path) -> list[ReplayStep]:
    identifier(plan.repair_id)
    if plan.parent_repair is not None:
        identifier(plan.parent_repair)
        if plan.parent_repair == plan.repair_id:
            raise ReplayError('修订不能继承自身。')
    steps = {step.step_id: step for step in plan.steps}
    if not steps or len(steps) != len(plan.steps) or not plan.targets:
        raise ReplayError('阶段和目标必须非空，阶段 ID 不得重复。')
    destinations = set()
    for step in plan.steps:
        identifier(step.step_id)
        if not step.outputs:
            raise ReplayError('阶段必须声明输出。')
        for filename in step.outputs.values():
            destination = local_path(root, filename)
            if Path(filename).parts[0] in {'plan.json', 'inputs.json', 'result.json', 'attempts', 'inputs'}:
                raise ReplayError('输出不能覆盖修订记录、冻结代码或封存输入。')
            if any(destination == other or destination.is_relative_to(other) or other.is_relative_to(destination)
                   for other in destinations):
                raise ReplayError('输出路径冲突。')
            destinations.add(destination)
        for binding in step.inputs.values():
            if not isinstance(binding, dict):
                raise ReplayError('输入绑定必须是对象。')
            if set(binding) == {'accepted'}:
                if binding['accepted'] not in plan.accepted_inputs:
                    raise ReplayError('输入引用不存在。')
            elif set(binding) == {'step', 'output'}:
                if binding['step'] not in steps or binding['output'] not in steps[binding['step']].outputs:
                    raise ReplayError('阶段输出端口不存在。')
            else:
                raise ReplayError('输入绑定必须引用 accepted 或 step/output。')
    ordered, visiting, visited = [], set(), set()
    def visit(key: str) -> None:
        if key not in steps or key in visiting:
            raise ReplayError('依赖循环或目标不存在。')
        if key in visited:
            return
        visiting.add(key)
        for binding in steps[key].inputs.values():
            if 'step' in binding:
                visit(binding['step'])
        visiting.remove(key)
        visited.add(key)
        ordered.append(steps[key])
    for key in steps:
        visit(key)
    needed = set()
    def include(key: str) -> None:
        if key not in steps:
            raise ReplayError('目标不存在。')
        if key in needed:
            return
        needed.add(key)
        for binding in steps[key].inputs.values():
            if 'step' in binding:
                include(binding['step'])
    for key in plan.targets:
        include(key)
    return [step for step in ordered if step.step_id in needed]


def sources(history: ExecutionHistory) -> dict[str, dict]:
    return {row['execution_id']: row for row in history.rows()}


def accept_inputs(plan: RepairPlan, rows: dict) -> dict:
    result = {}
    for name, reference in plan.accepted_inputs.items():
        path = reference.get('path')
        if 'execution_id' in reference:
            row = rows.get(reference['execution_id'])
            if not row or row['integrity'] != 'ok' or row['status'] != 'succeeded':
                raise ReplayError('采用的历史输入没有可信成功结果。')
            path = (row['result'].get('outputs') or {}).get(reference.get('output'))
            if reference.get('adopt_current') is not True or not reference.get('reason'):
                raise ReplayError('旧输入必须明确 adopt_current 并说明采用理由。')
        if not path or '://' in path or '|' in path:
            raise ReplayError('首版只接受本地文件；图层用 layer 选择器。')
        result[name] = file_version(path) | {'layer': reference.get('layer'),
                                           'historical_identity': 'unverified', 'level': 'declared'}
    return result


def seal_inputs(accepted: dict, root: Path) -> tuple[dict, float]:
    started = perf_counter()
    result = {}
    for index, (name, version) in enumerate(accepted.items()):
        path = root / 'inputs' / f'{index:03d}{Path(version["path"]).suffix}'
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(version['path'], path)
        copied = file_version(str(path))
        if copied['sha256'] != version['sha256'] or not same_version(version):
            raise ReplayError('输入在封存期间变化。')
        result[name] = version | copied | {'original_path': version['path'], 'level': 'controlled'}
    return result, (perf_counter() - started) * 1000


def validate_outputs(versions: dict) -> bool:
    return bool(versions) and all(same_version(version) for version in versions.values())


def valid_completion(record: dict) -> bool:
    return (record.get('state') == 'completed' and validate_outputs(record.get('output_versions', {}))
            and all(same_version(version) for version in record.get('input_versions', {}).values())
            and all(same_version(version) for version in record.get('code_versions', [])))


def cached_steps(plan: RepairPlan, history: ExecutionHistory, output_dir: Path) -> list[dict]:
    candidates, visited = [], set()
    parent = plan.parent_repair
    while parent:
        identifier(parent)
        if parent in visited:
            raise ReplayError('修订继承链循环。')
        visited.add(parent)
        directory = output_dir.resolve() / 'repairs' / parent
        original = json.loads((directory / 'plan.json').read_text(encoding='utf-8'))
        for path in history.record_dir.glob(f'r_{parent}_s*.json'):
            record = read_receipt(path)
            if record.get('plan_sha256') != digest(original):
                raise ReplayError('父修订计划与子回执不一致。')
            if record.get('origin') == 'replay_child' and record.get('state') == 'completed':
                candidates.append(record)
        parent = original.get('parent_repair')
    return candidates


def signature_for(step, tool, arguments, bindings, outputs, code, environment):
    versions = {}
    for name, source in bindings.items():
        path, *selector = source.split('|', 1)
        versions[name] = file_version(path) | {'selector': selector}
    normalized = {key: value for key, value in arguments.items() if key not in bindings and key not in outputs}
    if code is not None:
        normalized = {'parameters': step.changes.get('job_parameters', {}),
                      'code': file_digest(Path(arguments['script_path'])),
                      'dependencies': {name: digest_bytes(data) for name, data in code[1].items()}}
    signature = digest({'tool': tool.name, 'metadata': tool.execution_metadata, 'parameters': normalized,
                        'inputs': {name: {k: v for k, v in version.items() if k != 'path'} for name, version in versions.items()},
                        'outputs': step.outputs, 'implementation': file_digest(Path(__file__)), 'environment': environment})
    return signature, versions


def qgis_call(step: ReplayStep, row: dict, tool, bindings: dict, outputs: dict) -> dict:
    metadata = tool.execution_metadata
    if not metadata or metadata.get('algorithm_id') not in LOCAL_ALGORITHMS:
        raise ReplayError('首版受控QGIS仅支持重投影、缓冲、叠加、裁剪、融合和几何修复；其他方法可继续自由Python。')
    previous = row.get('facts', {}).get('definition_sha256')
    if previous and previous != metadata['definition_sha256']:
        raise ReplayError('算法定义已变化。')
    if set(step.changes) - {'parameter_overrides'}:
        raise ReplayError('QGIS 阶段只接受 parameter_overrides。')
    changes = step.changes.get('parameter_overrides', {})
    if changes.keys() & (bindings.keys() | outputs.keys()):
        raise ReplayError('参数修改与已绑定输入输出冲突。')
    arguments = dict(row['arguments'])
    for name, definition in metadata['parameters'].items():
        if name not in arguments and definition.get('default') is not None:
            arguments[name] = definition['default']
        if definition['destination'] and name in arguments and name not in outputs:
            raise ReplayError(f'输出未声明：{name}')
        if definition['type'] in {'source', 'vector', 'raster', 'maplayer', 'multilayer', 'file'}:
            if name in arguments and arguments[name] not in (None, '') and name not in bindings:
                raise ReplayError(f'文件输入未声明：{name}')
    arguments.update(changes)
    arguments.update(bindings)
    arguments.update(outputs)
    if arguments.keys() - tool.parameters['properties'].keys():
        raise ReplayError('参数不在当前 Schema 中。')
    for name, definition in metadata['parameters'].items():
        if definition['destination'] and name in arguments and name not in outputs:
            raise ReplayError(f'输出未声明：{name}')
        if definition['type'] in {'source', 'vector', 'raster', 'maplayer', 'multilayer', 'file'}:
            if arguments.get(name) not in (None, '') and name not in bindings:
                raise ReplayError(f'文件输入未声明：{name}')
    if arguments.get('project_path'):
        raise ReplayError('首版不自动复用外部工程上下文。')
    return arguments


def python_code(step: ReplayStep, row: dict, history: ExecutionHistory) -> tuple[bytes, dict[str, bytes]]:
    changes = step.changes
    if changes.get('job_contract') is not True or changes.get('side_effects') != 'outputs_only':
        raise ReplayError('Python 必须明确 job_contract=true、side_effects=outputs_only，并声明所有文件依赖。')
    if changes.get('patches') and changes.get('candidate_script'):
        raise ReplayError('补丁和候选脚本互斥。')
    if changes.get('candidate_script'):
        source = Path(changes['candidate_script']).resolve()
        expected = changes.get('expected_sha256')
    else:
        if not history.read_resource(row, 'script', limit=512)['ok']:
            raise ReplayError('历史脚本快照不能核实。')
        source = Path(row['links']['script_snapshot'])
        expected = row['links'].get('script_sha256')
    code = source.read_bytes()
    if not expected or digest_bytes(code) != expected:
        raise ReplayError('候选或历史脚本 SHA-256 不匹配。')
    code.decode('utf-8')
    helpers = {}
    for name, reference in changes.get('dependencies', {}).items():
        local_path(Path('/bundle').resolve(), name)
        if name == 'script.py' or Path(name).suffix.lower() not in {'.py', '.json', '.csv', '.npy'}:
            raise ReplayError('辅助依赖必须使用明确的相对文件名，不能覆盖 script.py。')
        data = Path(reference['path']).read_bytes()
        if digest_bytes(data) != reference.get('expected_sha256'):
            raise ReplayError(f'辅助依赖版本不匹配：{name}')
        helpers[name] = data
    return code, helpers


def digest_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def freeze_python(step: ReplayStep, code: bytes, helpers: dict[str, bytes], root: Path) -> Path:
    directory = root / 'attempts' / step.step_id
    directory.mkdir(parents=True)
    script = directory / 'script.py'
    script.write_bytes(code)
    for index, patch in enumerate(step.changes.get('patches', [])):
        if index == 0 and not patch.get('expected_sha256'):
            raise ReplayError('首个补丁必须包含 expected_sha256。')
        result = edit_file(str(script), **patch)
        if not result['ok']:
            raise ReplayError(f'补丁失败：{result}')
    try:
        compile(script.read_text(encoding='utf-8'), str(script), 'exec')
    except SyntaxError as error:
        raise ReplayError(f'修订代码语法错误：{error}') from error
    for name, data in helpers.items():
        path = local_path(directory, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return script


def replay(plan: RepairPlan, history: ExecutionHistory, execute: Callable, output_dir: Path,
           *, resolve_tool: Callable, environment: dict | None = None) -> dict:
    with repair_lock(output_dir, plan.repair_id):
        return _replay(plan, history, execute, output_dir, resolve_tool=resolve_tool, environment=environment)


def _replay(plan: RepairPlan, history: ExecutionHistory, execute: Callable, output_dir: Path,
            *, resolve_tool: Callable, environment: dict | None = None) -> dict:
    root = output_dir.resolve() / 'repairs' / plan.repair_id
    ordered = order_steps(plan, root)
    if root.resolve() != root:
        raise ReplayError('修订目录不能经链接重定向。')
    rows = sources(history)
    accepted = accept_inputs(plan, rows)
    prepared = {}
    for step in ordered:
        row = rows.get(step.source_execution)
        if not row or row['integrity'] != 'ok' or not isinstance(row['arguments'], dict):
            raise ReplayError(f'找不到完整的原执行：{step.source_execution}')
        tool = resolve_tool(row['tool'])
        outputs = {name: str(local_path(root, filename)) for name, filename in step.outputs.items()}
        bindings = {name: ('<dependency>' if 'step' in binding else accepted[binding['accepted']]['path'])
                    for name, binding in step.inputs.items()}
        code = python_code(step, row, history) if tool.name == 'run_python_script' else None
        if code is None:
            qgis_call(step, row, tool, bindings, outputs)
        prepared[step.step_id] = row, tool, outputs, code
    previous_records = {}
    if root.exists():
        if digest(json.loads((root / 'plan.json').read_text(encoding='utf-8'))) != digest(asdict(plan)):
            raise ReplayError('repair_id 已关联不同计划。')
        result_path = root / 'result.json'
        for index, step in enumerate(ordered):
            path = history.record_dir / f'r_{plan.repair_id}_s{index:02d}.json'
            if path.exists():
                record = read_receipt(path)
                if record['plan_sha256'] != digest(asdict(plan)) or record['environment'] != environment:
                    raise ReplayError('子回执与计划或环境不一致。')
                if record['state'] not in {'completed', 'failed'}:
                    return unknown_result(plan, '存在执行意图且结果不确定，禁止自动重试。')
                if record['state'] == 'completed' and not valid_completion(record):
                    return unknown_result(plan, '完成回执与文件版本不一致。')
                previous_records[step.step_id] = record
        if result_path.exists():
            previous = read_receipt(result_path)
            if (previous.get('plan_sha256') != digest(asdict(plan))
                    or set(previous['execution_refs']) != set(previous_records)):
                return unknown_result(plan, '根结果与子回执范围不一致。')
            return previous
        if (root / 'inputs.json').exists():
            accepted = read_receipt(root / 'inputs.json')
            if not all(same_version(version) for version in accepted.values()):
                return unknown_result(plan, '冻结输入已经变化。')
    candidates = cached_steps(plan, history, output_dir)
    if not root.exists():
        root.mkdir(parents=True)
        write_json(root / 'plan.json', asdict(plan))
    copy_ms = 0.0
    if not (root / 'inputs.json').exists():
        accepted, copy_ms = seal_inputs(accepted, root)
        write_receipt(root / 'inputs.json', accepted)
    report = {'ok': False, 'status': 'failed', 'repair_id': plan.repair_id, 'completed': [], 'reused': [],
              'failed': [], 'pending': [s.step_id for s in ordered], 'outputs': {}, 'execution_refs': {},
              'metrics': {'input_copy_ms': copy_ms, 'fingerprint_ms': 0.0, 'native_starts': 0}}
    for index, step in enumerate(ordered):
        row, tool, outputs, code = prepared[step.step_id]
        prior = previous_records.get(step.step_id)
        if prior:
            report['pending'].remove(step.step_id)
            report['execution_refs'][step.step_id] = prior['execution_id']
            if prior['state'] == 'failed':
                report['failed'].append({'step_id': step.step_id, 'result': prior['result']})
                break
            report['completed'].append(step.step_id)
            report['outputs'][step.step_id] = {name: item['path'] for name, item in prior['output_versions'].items()}
            continue
        bindings = {name: (report['outputs'][b['step']][b['output']] if 'step' in b else
                           accepted[b['accepted']]['path'] + (f"|layername={accepted[b['accepted']]['layer']}" if accepted[b['accepted']]['layer'] else ''))
                    for name, b in step.inputs.items()}
        if any(Path(path).exists() for path in outputs.values()):
            return unknown_result(plan, f'阶段 {step.step_id} 已存在未确认输出，禁止覆盖。')
        for path in outputs.values():
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        if code is not None:
            script = freeze_python(step, *code, root)
            frozen_versions = [file_version(str(path)) for path in script.parent.rglob('*') if path.is_file()]
            job = script.parent / 'job.json'
            write_json(job, {'inputs': bindings, 'parameters': step.changes.get('job_parameters', {}), 'outputs': outputs})
            frozen_versions.append(file_version(str(job)))
            arguments = {'script_path': str(script), 'arguments': [str(job)]}
        else:
            arguments = qgis_call(step, row, tool, bindings, outputs)
        started = perf_counter()
        signature, versions = signature_for(step, tool, arguments, bindings, outputs, code, environment)
        report['metrics']['fingerprint_ms'] += (perf_counter() - started) * 1000
        cacheable = environment is not None and (
            tool.execution_metadata and tool.execution_metadata.get('algorithm_id') in LOCAL_ALGORITHMS
            or step.changes.get('deterministic') is True)
        match = next((record for record in candidates if cacheable and record.get('cacheable')
                      and record.get('signature') == signature and valid_completion(record)), None)
        reference = f'r_{plan.repair_id}_s{index:02d}'
        receipt = history.record_dir / f'{reference}.json'
        record = {'version': 1, 'origin': 'replay_child', 'execution_id': reference, 'plan_sha256': digest(asdict(plan)),
                  'repair_id': plan.repair_id, 'step_id': step.step_id, 'source_execution': step.source_execution,
                  'resolved_call': {'tool': tool.name, 'arguments': arguments}, 'state': 'started',
                  'started_at': datetime.now(timezone.utc).isoformat(), 'environment': environment,
                  'signature': signature, 'input_versions': versions, 'cacheable': cacheable,
                  'dependency_level': 'controlled', 'outputs': outputs, 'metadata': tool.execution_metadata,
                  'code_versions': frozen_versions if code is not None else []}
        if match:
            record.update(state='completed', reused_from=match['execution_id'], output_versions=match['output_versions'],
                          result=match['result'], elapsed_ms=0.0, finished_at=datetime.now(timezone.utc).isoformat())
            write_receipt(receipt, record)
            report['pending'].remove(step.step_id)
            report['reused'].append(step.step_id)
            report['outputs'][step.step_id] = {name: item['path'] for name, item in record['output_versions'].items()}
            report['execution_refs'][step.step_id] = reference
            continue
        write_receipt(receipt, record)
        started = perf_counter()
        report['metrics']['native_starts'] += 1
        try:
            result = execute(tool.name, arguments)
        except Exception as error:
            record.update(state='unknown', error=f'{type(error).__name__}: {error}',
                          elapsed_ms=(perf_counter()-started)*1000)
            write_receipt(receipt, record)
            return unknown_result(plan, f'阶段 {step.step_id} 异常，外部结果未知：{record["error"]}')
        record.update(result=result, elapsed_ms=(perf_counter() - started) * 1000,
                      finished_at=datetime.now(timezone.utc).isoformat(),
                      facts=history.facts(result, arguments, tool.execution_metadata, capture_request=True))
        report['pending'].remove(step.step_id)
        report['execution_refs'][step.step_id] = reference
        if not isinstance(result, dict) or not result.get('ok'):
            record['state'] = 'failed'
            write_receipt(receipt, record)
            report['failed'].append({'step_id': step.step_id, 'result': result})
            break
        output_versions = {name: file_version(path) for name, path in outputs.items()}
        if not all(same_version(version) for version in versions.values()):
            raise ReplayError('受控输入在执行期间变化，不能发布成功。')
        if code is not None and not all(same_version(version) for version in frozen_versions):
            raise ReplayError('冻结脚本在执行期间变化。')
        record.update(state='completed', output_versions=output_versions)
        write_receipt(receipt, record)
        report['completed'].append(step.step_id)
        report['outputs'][step.step_id] = outputs
    report['ok'] = not report['failed'] and not report['pending']
    report['status'] = 'completed' if report['ok'] else ('partial' if report['completed'] else 'failed')
    report['plan_sha256'] = digest(asdict(plan))
    write_receipt(root / 'result.json', report)
    return report


def unknown_result(plan: RepairPlan, error: str) -> dict:
    return {'ok': False, 'status': 'unknown', 'repair_id': plan.repair_id, 'error': error,
            'completed': [], 'reused': [], 'failed': [], 'pending': list(plan.targets), 'outputs': {}, 'execution_refs': {}}
