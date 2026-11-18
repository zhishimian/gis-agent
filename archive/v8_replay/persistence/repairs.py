import json
from pathlib import Path

from gis_agent.core.replay import read_receipt, valid_completion, write_receipt, digest as plan_digest, identifier
from gis_agent.persistence.executions import digest, execution_id
from gis_agent.persistence.sessions import message_units


def assistant_identity(message: dict) -> str:
    return digest({key: value for key, value in message.items() if key != 'executions'})


def root_path(history, index: int) -> Path:
    return history.record_dir / f'root_{execution_id(index, 0)}.json'


def begin_root(history, state: dict, messages: list, snapshot) -> Path:
    index = state['model_index']
    message = messages[index]
    calls = message['tool_calls']
    if len(calls) != 1 or calls[0]['function']['name'] != 'local_replay':
        raise ValueError('受控恢复只支持单独的 local_replay。')
    path = root_path(history, index)
    if path.parent.resolve() != path.parent:
        raise ValueError('关键回执目录不能经链接重定向。')
    record = {'version': 810, 'state': 'started', 'session': history.store.session_id,
              'session_path': str(history.store.path), 'output_root': str(history.output_root),
              'checkpoint_id': snapshot.config['configurable']['checkpoint_id'],
              'checkpoint_state_sha256': digest(snapshot.values), 'checkpoint_record_hash': state['record_hash'],
              'assistant_index': index, 'assistant_sha256': assistant_identity(message),
              'prefix_sha256': digest(messages[:index]), 'call_sha256': digest(calls[0]),
              'plan_sha256': plan_digest(json.loads(calls[0]['function']['arguments'])['plan'])}
    if path.exists():
        if read_receipt(path) != record:
            raise ValueError('受控调用的恢复基准已存在且冲突。')
    else:
        write_receipt(path, record)
    return path


def validate_result(history, call: dict, result: dict) -> None:
    if result.get('status') == 'unknown':
        raise ValueError('修复结果不确定，禁止自动恢复。')
    plan = json.loads(call['function']['arguments'])['plan']
    identifier(plan['repair_id'])
    root = history.output_root / 'repairs' / plan['repair_id']
    for path in history.record_dir.glob(f'r_{plan["repair_id"]}_s*.json'):
        record = read_receipt(path)
        if record['plan_sha256'] != plan_digest(plan) or record['state'] not in {'completed', 'failed'}:
            raise ValueError('存在未完成或来源冲突的子执行。')
        if record['state'] == 'completed' and not valid_completion(record):
            raise ValueError('子执行成果版本不一致。')
    if result.get('status') in {'completed', 'partial', 'failed'}:
        persisted = read_receipt(root / 'result.json')
        if persisted['plan_sha256'] != plan_digest(plan) or any(result.get(key) != value for key, value in persisted.items()):
            raise ValueError('根工具结果与持久化修订不一致。')


def complete_root(history, path: Path, call: dict, message: dict) -> None:
    record = read_receipt(path)
    result = history.read_result(message)
    # unknown 也记录原始返回，但它不能进入自动恢复。
    if result.get('status') in {'completed', 'partial', 'failed'}:
        validate_result(history, call, result)
    record.update(state='completed', completion_message=message,
                  completion_sha256=digest(message))
    write_receipt(path, record)


def recover_root(agent, snapshot, messages: list) -> bool:
    state = snapshot.values
    index = state['model_index']
    if state.get('version') != 810 or snapshot.next != ('tools',) or agent.history is None or index >= len(messages):
        return False
    message = messages[index]
    calls = message.get('tool_calls', [])
    if len(calls) != 1 or calls[0]['function']['name'] != 'local_replay':
        return False
    path = root_path(agent.history, index)
    if not path.is_file():
        return False
    record = read_receipt(path)
    expected = {
        'version': 810, 'session': agent.store.session_id, 'session_path': str(agent.store.path),
        'output_root': str(agent.history.output_root),
        'checkpoint_id': snapshot.config['configurable']['checkpoint_id'],
        'checkpoint_state_sha256': digest(state), 'checkpoint_record_hash': state['record_hash'],
        'assistant_index': index, 'assistant_sha256': assistant_identity(message),
        'prefix_sha256': digest(messages[:index]), 'call_sha256': digest(calls[0]),
        'plan_sha256': plan_digest(json.loads(calls[0]['function']['arguments'])['plan']),
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError('受控修复的 Session、调用或检查点基准冲突。')
    if len(messages) not in {index + 1, index + 2}:
        raise ValueError('恢复尾部存在额外消息。')
    if record['state'] != 'completed':
        # 未形成根结果时仅重建已持久化的终态，不启动原生计算。
        plan = json.loads(calls[0]['function']['arguments'])['plan']
        result_path = agent.history.output_root / 'repairs' / plan['repair_id'] / 'result.json'
        if not result_path.exists():
            for child in agent.history.record_dir.glob(f'r_{plan["repair_id"]}_s*.json'):
                if read_receipt(child)['state'] not in {'completed', 'failed'}:
                    return False
            result = agent.registry.execute('local_replay', {'plan': plan})
            if result.get('status') not in {'completed', 'partial', 'failed'}:
                return False
        else:
            result = read_receipt(result_path)
        validate_result(agent.history, calls[0], result)
        completion = agent.store.tool_message(calls[0]['id'], 'local_replay', result, agent.context.config.tool_limit)
        completion['execution_id'] = execution_id(index, 0)
        complete_root(agent.history, path, calls[0], completion)
        record = read_receipt(path)
    completion = record['completion_message']
    if digest(completion) != record['completion_sha256']:
        raise ValueError('根完成消息校验失败。')
    validate_result(agent.history, calls[0], agent.history.read_result(completion))
    if len(messages) == index + 2 and messages[-1] != completion:
        raise ValueError('Session 已有的工具结果与根回执冲突。')
    message.setdefault('executions', {})[calls[0]['id']] = 'finished'
    if len(messages) == index + 1:
        messages.append(completion)
    message_units(messages)
    agent.store.save(messages)
    agent.graph.update_state(agent.options(), {'model_index': len(messages), 'record_hash': agent.record_hash(),
                                              'execution_started': True}, as_node='tools')
    return True
