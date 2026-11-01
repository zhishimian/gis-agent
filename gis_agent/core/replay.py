import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from gis_agent.persistence.evidence import file_digest
from gis_agent.persistence.executions import ExecutionHistory, digest
from gis_agent.persistence.json import write_json


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
        qgis_call(step, row, tool, bindings, outputs)
        prepared[step.step_id] = row, tool, outputs
    if root.exists():
        raise ReplayError('修订目录已存在；请使用新 repair_id。')
    root.mkdir(parents=True)
    write_json(root / 'plan.json', asdict(plan))
    report = {'ok': False, 'status': 'failed', 'repair_id': plan.repair_id, 'completed': [], 'reused': [],
              'failed': [], 'pending': [s.step_id for s in ordered], 'outputs': {}, 'execution_refs': {}}
    for index, step in enumerate(ordered):
        row, tool, outputs = prepared[step.step_id]
        bindings = {name: (report['outputs'][b['step']][b['output']] if 'step' in b else
                           accepted[b['accepted']]['path'] + (f"|layername={accepted[b['accepted']]['layer']}" if accepted[b['accepted']]['layer'] else ''))
                    for name, b in step.inputs.items()}
        arguments = qgis_call(step, row, tool, bindings, outputs)
        reference = f'r_{plan.repair_id}_s{index:02d}'
        receipt = history.record_dir / f'{reference}.json'
        record = {'version': 1, 'origin': 'replay_child', 'execution_id': reference,
                  'repair_id': plan.repair_id, 'step_id': step.step_id, 'source_execution': step.source_execution,
                  'resolved_call': {'tool': tool.name, 'arguments': arguments}, 'state': 'started'}
        write_json(receipt, record)
        started = perf_counter()
        result = execute(tool.name, arguments)
        record.update(result=result, elapsed_ms=(perf_counter() - started) * 1000)
        report['pending'].remove(step.step_id)
        report['execution_refs'][step.step_id] = reference
        if not isinstance(result, dict) or not result.get('ok'):
            record['state'] = 'failed'
            write_json(receipt, record)
            report['failed'].append({'step_id': step.step_id, 'result': result})
            break
        versions = {name: file_version(path) for name, path in outputs.items()}
        record.update(state='completed', output_versions=versions)
        write_json(receipt, record)
        report['completed'].append(step.step_id)
        report['outputs'][step.step_id] = outputs
    report['ok'] = not report['failed'] and not report['pending']
    report['status'] = 'completed' if report['ok'] else ('partial' if report['completed'] else 'failed')
    write_json(root / 'result.json', report)
    return report
