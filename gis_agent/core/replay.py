import json
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
from gis_agent.persistence.executions import ExecutionHistory, digest
from gis_agent.persistence.json import write_json
from gis_agent.tools.files import edit_file


class ReplayError(ValueError):
    pass


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


def file_version(source: str) -> dict:
    path = Path(source).resolve()
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
        sidecars = [Path(str(path) + suffix) for suffix in ('.aux.xml', '.ovr', '.msk')]
        sidecars += [path.with_suffix(suffix) for suffix in ('.tfw', '.tifw', '.wld', '.aux.xml')]
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
            if destination in destinations:
                raise ReplayError('输出路径冲突。')
            destinations.add(destination)
        for binding in step.inputs.values():
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
            record = json.loads(path.read_text(encoding='utf-8'))
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
    if not metadata or not metadata.get('algorithm_id', '').startswith(('native:', 'gdal:')):
        raise ReplayError('只能重放明确的本地 QGIS 算法或受控 Python。')
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
    compile(script.read_text(encoding='utf-8'), str(script), 'exec')
    for name, data in helpers.items():
        path = local_path(directory, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return script


def replay(plan: RepairPlan, history: ExecutionHistory, execute: Callable, output_dir: Path,
           *, resolve_tool: Callable, environment: dict | None = None) -> dict:
    root = output_dir.resolve() / 'repairs' / plan.repair_id
    ordered = order_steps(plan, root)
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
    if root.exists():
        if json.loads((root / 'plan.json').read_text(encoding='utf-8')) != json.loads(json.dumps(asdict(plan))):
            raise ReplayError('repair_id 已关联不同计划。')
        result_path = root / 'result.json'
        if not result_path.exists():
            return {'ok': False, 'status': 'unknown', 'repair_id': plan.repair_id,
                    'error': '已有修订未形成终态，需检查意图和部分产物，禁止自动重试。'}
        previous = json.loads(result_path.read_text(encoding='utf-8'))
        for reference in previous['execution_refs'].values():
            record = json.loads((history.record_dir / f'{reference}.json').read_text(encoding='utf-8'))
            if record['state'] == 'completed' and (not validate_outputs(record['output_versions']) or record.get('environment') != environment):
                return previous | {'ok': False, 'status': 'unknown', 'error': '完成回执与输出或环境不一致。'}
        return previous
    candidates = cached_steps(plan, history, output_dir)
    root.mkdir(parents=True)
    write_json(root / 'plan.json', asdict(plan))
    accepted, copy_ms = seal_inputs(accepted, root)
    write_json(root / 'inputs.json', accepted)
    report = {'ok': False, 'status': 'failed', 'repair_id': plan.repair_id, 'completed': [], 'reused': [],
              'failed': [], 'pending': [s.step_id for s in ordered], 'outputs': {}, 'execution_refs': {},
              'metrics': {'input_copy_ms': copy_ms, 'fingerprint_ms': 0.0, 'native_starts': 0}}
    for index, step in enumerate(ordered):
        row, tool, outputs, code = prepared[step.step_id]
        bindings = {name: (report['outputs'][b['step']][b['output']] if 'step' in b else
                           accepted[b['accepted']]['path'] + (f"|layername={accepted[b['accepted']]['layer']}" if accepted[b['accepted']]['layer'] else ''))
                    for name, b in step.inputs.items()}
        if code is not None:
            script = freeze_python(step, *code, root)
            frozen_versions = [file_version(str(path)) for path in script.parent.rglob('*') if path.is_file()]
            job = script.parent / 'job.json'
            write_json(job, {'inputs': bindings, 'parameters': step.changes.get('job_parameters', {}), 'outputs': outputs})
            arguments = {'script_path': str(script), 'arguments': [str(job)]}
        else:
            arguments = qgis_call(step, row, tool, bindings, outputs)
        started = perf_counter()
        signature, versions = signature_for(step, tool, arguments, bindings, outputs, code, environment)
        report['metrics']['fingerprint_ms'] += (perf_counter() - started) * 1000
        cacheable = environment is not None and (
            tool.execution_metadata and tool.execution_metadata.get('algorithm_id') in {
                'native:reprojectlayer', 'native:buffer', 'native:intersection', 'native:clip',
                'native:dissolve', 'native:fixgeometries',
            } or step.changes.get('deterministic') is True)
        match = next((record for record in candidates if cacheable and record.get('cacheable')
                      and record.get('signature') == signature and validate_outputs(record['output_versions'])), None)
        reference = f'r_{plan.repair_id}_s{index:02d}'
        receipt = history.record_dir / f'{reference}.json'
        record = {'version': 1, 'origin': 'replay_child', 'execution_id': reference,
                  'repair_id': plan.repair_id, 'step_id': step.step_id, 'source_execution': step.source_execution,
                  'resolved_call': {'tool': tool.name, 'arguments': arguments}, 'state': 'started',
                  'started_at': datetime.now(timezone.utc).isoformat(), 'environment': environment,
                  'signature': signature, 'input_versions': versions, 'cacheable': cacheable,
                  'dependency_level': 'controlled', 'outputs': outputs}
        if match:
            record.update(state='completed', reused_from=match['execution_id'], output_versions=match['output_versions'],
                          result=match['result'], elapsed_ms=0.0, finished_at=datetime.now(timezone.utc).isoformat())
            write_json(receipt, record)
            report['pending'].remove(step.step_id)
            report['reused'].append(step.step_id)
            report['outputs'][step.step_id] = {name: item['path'] for name, item in record['output_versions'].items()}
            report['execution_refs'][step.step_id] = reference
            continue
        write_json(receipt, record)
        started = perf_counter()
        report['metrics']['native_starts'] += 1
        result = execute(tool.name, arguments)
        record.update(result=result, elapsed_ms=(perf_counter() - started) * 1000,
                      finished_at=datetime.now(timezone.utc).isoformat())
        report['pending'].remove(step.step_id)
        report['execution_refs'][step.step_id] = reference
        if not isinstance(result, dict) or not result.get('ok'):
            record['state'] = 'failed'
            write_json(receipt, record)
            report['failed'].append({'step_id': step.step_id, 'result': result})
            break
        output_versions = {name: file_version(path) for name, path in outputs.items()}
        if not all(same_version(version) for version in versions.values()):
            raise ReplayError('受控输入在执行期间变化，不能发布成功。')
        if code is not None and not all(same_version(version) for version in frozen_versions):
            raise ReplayError('冻结脚本在执行期间变化。')
        record.update(state='completed', output_versions=output_versions)
        write_json(receipt, record)
        report['completed'].append(step.step_id)
        report['outputs'][step.step_id] = outputs
    report['ok'] = not report['failed'] and not report['pending']
    report['status'] = 'completed' if report['ok'] else ('partial' if report['completed'] else 'failed')
    write_json(root / 'result.json', report)
    return report
