from pathlib import Path
from time import perf_counter

from gis_agent.core.replay import RepairPlan, ReplayError, replay
from gis_agent.persistence.evidence import file_digest
from gis_agent.persistence.executions import digest
from gis_agent.tools.base import Tool


def make_replay_tool(history, registry, resolve_tool, launchers: tuple[Path, ...]) -> Tool:
    environment = None
    watched = {}
    probe = Path(__file__).resolve().parents[1] / 'integrations/qgis/replay_environment.py'

    def run(plan: dict) -> dict:
        nonlocal environment, watched
        started = perf_counter()
        try:
            parsed = RepairPlan.parse(plan)
            if environment is None:
                measured = registry.execute('run_python_script', {'script_path': str(probe)})
                if not measured.get('ok'):
                    return {'ok': False, 'status': 'needs_revision', 'error': '无法确认受控执行环境。', 'diagnostic': measured}
                files = [*measured['result']['files'], *(str(path) for path in launchers),
                         str(probe), str(Path(__file__).resolve()),
                         str(Path(__file__).with_name('qgis_python.py')),
                         str(Path(__file__).with_name('registry.py')), str(Path(__file__).with_name('base.py')),
                         str(Path(__file__).resolve().parents[1] / 'integrations/qgis/adapter.py'),
                         str(Path(__file__).resolve().parents[1] / 'integrations/qgis/python_runtime.py'),
                         str(Path(__file__).resolve().parents[1] / 'integrations/qgis/script_entry.py')]
                watched = {path: file_digest(Path(path)) for path in files}
                environment = {'versions': measured['result']['versions'], 'identity': digest(watched)}
            if any(file_digest(Path(path)) != sha for path, sha in watched.items()):
                return {'ok': False, 'status': 'needs_revision', 'error': '受管理环境已变化，请在新会话重新核对。'}
            preparation_ms = (perf_counter() - started) * 1000
            result = replay(parsed, history, registry.execute, history.output_root,
                            resolve_tool=resolve_tool, environment=environment)
            return result | {'preparation_ms': preparation_ms}
        except (ValueError, KeyError, TypeError) as error:
            return {'ok': False, 'status': 'needs_revision', 'error': f'{type(error).__name__}: {error}'}

    binding = {'type': 'object', 'description': 'One of {accepted:name} or {step:step_id,output:port}.'}
    return Tool('local_replay',
        '可选：用execution_history真实ID修订参数或冻结Python补丁，适合昂贵已保存前缀、明确文件依赖与需保留旧版本的局部修复；一次连续执行所需阶段。'
        '普通小修改可继续edit_file/run_python_script。本工具必须单独调用。'
        f'Python job契约、示例和限制按需读取：{probe.with_name("replay.md")}',
        {'type': 'object', 'properties': {'plan': {'type': 'object', 'properties': {
            'repair_id': {'type': 'string'}, 'parent_repair': {'type': ['string', 'null']}, 'reason': {'type': 'string'},
            'accepted_inputs': {'type': 'object', 'description': 'name -> {path,layer?}, or {execution_id,output,adopt_current:true,reason}.'},
            'steps': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'step_id': {'type': 'string'}, 'source_execution': {'type': 'string'},
                'inputs': {'type': 'object', 'additionalProperties': binding},
                'changes': {'type': 'object', 'description': 'QGIS: {parameter_overrides:{...}}. Python: see referenced job contract.'},
                'outputs': {'type': 'object', 'additionalProperties': {'type': 'string'}, 'description': 'port -> new relative filename.'}},
                'required': ['step_id', 'source_execution', 'inputs', 'changes', 'outputs'], 'additionalProperties': False}},
            'targets': {'type': 'array', 'items': {'type': 'string'}}},
            'required': ['repair_id', 'parent_repair', 'reason', 'accepted_inputs', 'steps', 'targets'],
            'additionalProperties': False}}, 'required': ['plan'], 'additionalProperties': False}, run)
