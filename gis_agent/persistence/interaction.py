"""Read business handoffs from existing messages, with no extra state store."""
from gis_agent.persistence.evidence import tool_result


def latest_outcome(store, messages):
    for index in range(len(messages)-1, -1, -1):
        message = messages[index]
        if message.get('role') == 'user' and message.get('origin') != 'program':
            if message.get('cancelled_request'):
                return message['cancellation']
            return None
        if message.get('tool_name') == 'finish_task':
            value = tool_result(store, message)
            if isinstance(value, dict) and value.get('ok') and value.get('status'):
                return value | {'request_id': message.get('execution_id') or f'q{index}'}
    return None
