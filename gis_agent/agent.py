import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from gis_agent.core.context import ContextLimit, ContextManager
from gis_agent.core.auxiliary import AuxiliaryError
from gis_agent.core.memory import MemoryStore, MemoryTurn, extract_memories
from gis_agent.core.model import ModelReply
from gis_agent.core.planning import Plan
from gis_agent.persistence.sessions import SessionStore, message_units
from gis_agent.prompts import render_prompt
from gis_agent.tools.base import Tool
from gis_agent.tools.registry import ToolRegistry


logger = logging.getLogger(__name__)
PASSIVE_TOOLS = {
    'update_plan', 'finish_task', 'read_session_messages',
    'search_memory', 'remember_memory', 'forget_memory', 'read_verification', 'define_checks', 'read_delivery',
    'read_cartography', 'read_cartography_rules',
}


class RunState(TypedDict):
    turn_start: int
    model_index: int
    responses_used: int
    review_started: bool
    execution_started: bool
    algorithms: list[str]
    callable_names: list[str]
    memory_errors: list[str]
    handled_sources: list[int]
    handled_bodies: list[str]
    background: str
    record_hash: str
    auxiliary_used: int
    outcome: dict[str, Any] | None


@dataclass
class Agent:
    registry: ToolRegistry
    base_tools: list[Tool]
    load_qgis_tool: Callable[[str], Tool]
    plan: Plan
    instructions: str
    chat: Callable[..., ModelReply]
    store: SessionStore
    context: ContextManager
    memory: MemoryStore | None = None
    memory_turn: MemoryTurn | None = None
    checkpointer: BaseCheckpointSaver | None = None
    require_review: bool = True
    completion_check: Callable[[int], dict[str, Any]] | None = None
    evidence_catalog: Callable[[], list[dict[str, Any]]] | None = None
    graph: Any = field(init=False, repr=False)
    messages: list[dict[str, Any]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.memory is not None and self.memory_turn is None:
            raise ValueError('启用记忆时必须提供 MemoryTurn。')
        builder = StateGraph(RunState)
        builder.add_node('model', self.model)
        builder.add_node('tools', self.tools)
        builder.add_node('finish', self.finish)
        builder.add_edge(START, 'model')
        builder.add_conditional_edges('model', self.route, {'continue': 'tools', 'finish': 'finish'})
        builder.add_conditional_edges('tools', self.route, {'continue': 'model', 'finish': 'finish'})
        builder.add_edge('finish', END)
        self.graph = builder.compile(
            checkpointer=self.checkpointer if self.checkpointer is not None else InMemorySaver(),
            interrupt_after=['tools'],
        )

    def options(self) -> dict[str, Any]:
        return {'configurable': {'thread_id': self.store.session_id}, 'recursion_limit': 16}

    def record_hash(self) -> str:
        return hashlib.sha256(self.store.path.read_bytes()).hexdigest()

    def verify_record(self, state: RunState) -> None:
        if self.record_hash() != state['record_hash']:
            raise ValueError(
                'Session 已领先于检查点或被外部修改，不能自动重放。'
                '请检查已有产物和执行标记；必要时新建会话并提供已有成果路径。'
            )

    def recall(self, start: int) -> str:
        if self.memory is None:
            return ''
        query = self.messages[start]['content'] + ' ' + self.plan.goal
        return json.dumps(self.memory.recall(query), ensure_ascii=False)

    def run(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self.graph.get_state(self.options()).next:
            raise ValueError('当前会话仍有待续跑的图，请先调用 resume。')
        message_units(messages)
        self.messages = messages
        self.context.auxiliary.reset()
        start = len(messages) - 1
        if start < 0 or messages[start]['role'] != 'user' or messages[start].get('origin') not in {'user', 'delegation'}:
            raise ValueError('新一轮必须从用户输入或委派输入开始。')
        if self.memory_turn is not None:
            self.memory_turn.reset(start)
        self.store.save(messages)
        state: RunState = {
            'turn_start': start, 'model_index': len(messages), 'responses_used': 0,
            'review_started': False, 'execution_started': False, 'algorithms': [],
            'callable_names': [], 'memory_errors': [], 'handled_sources': [], 'handled_bodies': [],
            'background': self.recall(start), 'record_hash': self.record_hash(),
            'auxiliary_used': 0, 'outcome': None,
        }
        return self.drive(state)

    def resume(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        snapshot = self.graph.get_state(self.options())
        if not snapshot.next:
            raise ValueError('没有待续跑的检查点。')
        self.verify_record(snapshot.values)
        messages[:] = self.store.read_record()
        self.messages = messages
        restored = Plan.from_messages(messages)
        self.plan.goal, self.plan.steps = restored.goal, restored.steps
        self.context.auxiliary.used = snapshot.values['auxiliary_used']
        if self.memory_turn is not None:
            self.memory_turn.reset(snapshot.values['turn_start'])
            self.memory_turn.handled_sources.update(snapshot.values['handled_sources'])
            self.memory_turn.handled_bodies.update(snapshot.values['handled_bodies'])
        return self.drive(None)

    def drive(self, state: RunState | None) -> dict[str, Any]:
        # 每批工具后提交检查点，再续跑同一个图，不设置任务总响应次数。
        while True:
            self.graph.invoke(state, self.options(), durability='sync')
            snapshot = self.graph.get_state(self.options())
            if not snapshot.next:
                return snapshot.values['outcome']
            self.verify_record(snapshot.values)
            state = None

    def available(self, state: RunState) -> list[Tool]:
        tools = {tool.name: tool for tool in self.base_tools}
        for algorithm_id in state['algorithms']:
            tool = self.load_qgis_tool(algorithm_id)
            tools[tool.name] = tool
        return list(tools.values())

    def model(self, state: RunState) -> dict[str, Any]:
        message_units(self.messages)
        business = {
            'plan': self.plan.snapshot(), 'review_started': state['review_started'],
            'execution_started': state['execution_started'], 'responses_used': state['responses_used'],
            'latest_user_message': max(i for i, item in enumerate(self.messages) if item['role'] == 'user' and item.get('origin') != 'program'),
            'recent_tool_messages': {item['tool_call_id']: i for i, item in enumerate(self.messages) if item['role'] == 'tool' and i >= len(self.messages) - 20},
        }
        if self.evidence_catalog is not None:
            business['available_evidence'] = self.evidence_catalog()
        try:
            request = self.context.prepare(self.instructions, self.messages, business, self.available(state), state['background'])
        except (ContextLimit, AuxiliaryError) as error:
            return {'outcome': {'ok': False, 'status': 'blocked', 'summary': str(error)}}
        reply = self.chat(request.messages, request.schemas)
        self.store.record_model_call({'purpose': 'main', **reply.metadata()})
        logger.info('模型返回：%s；请求估算 token：%s', reply.metadata(), request.estimated_tokens)
        outcome = None
        if reply.finish_reason not in {'stop', 'tool_calls'}:
            message = {
                'role': 'assistant', 'content': '模型响应未完整结束，未执行其中的工具调用。',
                'response': {**reply.metadata(), 'raw_message': reply.message},
            }
            outcome = {'ok': False, 'status': 'blocked', 'summary': f'模型结束状态为 {reply.finish_reason}，请检查输出预算。'}
        else:
            message = {**reply.message, 'response': reply.metadata()}
            if not message.get('tool_calls'):
                message.pop('tool_calls', None)
        self.messages.append(message)
        self.store.save(self.messages)
        return {
            'responses_used': state['responses_used'] + 1,
            'callable_names': sorted(request.callable_names), 'record_hash': self.record_hash(),
            'auxiliary_used': self.context.auxiliary.used, 'outcome': outcome,
        }

    def tools(self, state: RunState) -> RunState:
        state = dict(state)
        message = self.messages[state['model_index']]
        calls = message.get('tool_calls', [])
        self.available(state)
        if not calls:
            self.messages.append({'role': 'user', 'origin': 'program', 'content': render_prompt('continue.txt')})
            self.store.save(self.messages)
        for call in calls:
            name = call['function']['name']
            try:
                arguments = json.loads(call['function']['arguments'])
            except json.JSONDecodeError as error:
                result = {'ok': False, 'error': f'工具参数不是有效 JSON：{error}'}
            else:
                if not isinstance(arguments, dict):
                    result = {'ok': False, 'error': '工具参数必须是 JSON 对象。'}
                elif name not in state['callable_names']:
                    result = {'ok': False, 'error': f'本次没有提供工具 {name}，请先搜索。'}
                elif name == 'finish_task' and len(calls) != 1:
                    result = {'ok': False, 'error': 'finish_task 必须单独调用。'}
                else:
                    message.setdefault('executions', {})[call['id']] = 'started'
                    self.store.save(self.messages)
                    if name not in PASSIVE_TOOLS:
                        state['execution_started'] = True
                    result = self.registry.execute(name, arguments)
                    if name == 'search_qgis_tools':
                        algorithms = list(state['algorithms'])
                        for item in result:
                            tool = self.load_qgis_tool(item['algorithm_id'])
                            if item['algorithm_id'] in algorithms:
                                algorithms.remove(item['algorithm_id'])
                            algorithms.append(item['algorithm_id'])
                            item['tool_name'] = tool.name
                        state['algorithms'] = algorithms
                    if name == 'finish_task' and result['ok']:
                        result = self.accept_finish(result, state)
                    message['executions'][call['id']] = 'finished'
            if name in {'remember_memory', 'forget_memory'}:
                errors = set(state['memory_errors'])
                if result.get('ok'):
                    errors.discard(name)
                    state['background'] = self.recall(state['turn_start'])
                else:
                    errors.add(name)
                state['memory_errors'] = sorted(errors)
            stored = self.store.tool_message(call['id'], name, result, self.context.config.tool_limit)
            self.messages.append(stored)
            self.store.save(self.messages)
            logger.info('工具 %s：%s', name, stored['content'][:1200])
        state['model_index'] = len(self.messages)
        state['record_hash'] = self.record_hash()
        if self.memory_turn is not None:
            state['handled_sources'] = sorted(self.memory_turn.handled_sources)
            state['handled_bodies'] = sorted(self.memory_turn.handled_bodies)
        return state

    def accept_finish(self, result: dict[str, Any], state: RunState) -> dict[str, Any]:
        status = result["status"]
        if state["memory_errors"] and status in {"answer", "completed"}:
            return {"ok": False, "error": "记忆操作仍有失败项，请重试对应操作或报告 blocked。"}
        if status == "answer" and state["execution_started"]:
            return {"ok": False, "error": "本轮已执行操作，请报告任务状态。"}
        if status == "completed" and self.require_review:
            if self.completion_check is not None:
                state["review_started"] = True
                reviewed = self.completion_check(state["turn_start"])
                if not reviewed["ok"]:
                    return {**reviewed, "status": "review_required"}
                result = {**result, "delivery": reviewed["delivery"], "artifacts": reviewed["artifacts"]}
            elif not state["review_started"]:
                state["review_started"] = True
                return {
                    **result, "status": "review_required", "instruction": render_prompt("review.txt"),
                    "unfinished": self.plan.unfinished(),
                }
        if status == "completed" and self.plan.unfinished():
            return {"ok": False, "error": "计划仍有未完成项，请继续处理或报告阻碍。", "unfinished": self.plan.unfinished()}
        state["outcome"] = result
        return result

    def finish(self, state: RunState) -> dict[str, Any]:
        outcome = dict(state['outcome'])
        self.messages.append({'role': 'assistant', 'content': outcome['summary']})
        self.store.save(self.messages)
        if self.memory is not None and outcome['status'] in {'answer', 'completed'}:
            try:
                maintenance = extract_memories(self.memory, self.store, self.messages, self.memory_turn, self.context.auxiliary)
            except (OSError, ValueError, KeyError, TypeError) as error:
                maintenance = {'status': 'failed', 'error': str(error)}
            outcome['memory'] = maintenance
            self.store.record_model_call({'purpose': 'memory_maintenance', **maintenance})
            logger.info('记忆维护：%s', maintenance)
        return {'outcome': outcome, 'record_hash': self.record_hash(), 'auxiliary_used': self.context.auxiliary.used}

    @staticmethod
    def route(state: RunState) -> str:
        return 'finish' if state['outcome'] is not None else 'continue'
