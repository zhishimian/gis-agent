import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from uuid import uuid4
import hashlib
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from openai import DefaultHttpxClient, OpenAI

from gis_agent.agent import Agent
from gis_agent.config import AppConfig
from gis_agent.core.auxiliary import AuxiliaryCalls
from gis_agent.core.context import ContextManager
from gis_agent.core.memory import MemoryStore, MemoryTurn
from gis_agent.core.planning import Plan
from gis_agent.core.model import ModelReply, TokenCounter
from gis_agent.integrations.llm import chat, make_token_counter
from gis_agent.integrations.qgis.adapter import load_qgis_tool
from gis_agent.integrations.qgis.catalog import load_catalog, make_search_tool
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.persistence.sessions import SessionStore
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.interaction import latest_outcome
from gis_agent.persistence.json import json_text
from gis_agent.prompts import render_prompt
from gis_agent.tools.builtin import builtin_tools
from gis_agent.skills import skill_index
from gis_agent.tools.files import file_tools
from gis_agent.tools.images import make_image_tool
from gis_agent.tools.memory import make_memory_tools
from gis_agent.tools.planning import make_planning_tools
from gis_agent.tools.qgis_python import make_qgis_python_tools
from gis_agent.tools.registry import ToolRegistry
from gis_agent.tools.session import make_session_tool
from gis_agent.tools.history import make_history_tool
from gis_agent.tools.replay import make_replay_tool
from gis_agent.tools.base import Tool


@dataclass
class Conversation:
    agent: Agent
    messages: list[dict[str, Any]]
    output_dir: Path

    @property
    def pending(self) -> bool:
        return bool(self.agent.graph.get_state(self.agent.options()).next)

    def send(self, text: str) -> dict[str, Any]:
        if self.pending:
            raise ValueError('请先续跑当前任务，再提交新输入。')
        if not text.strip():
            raise ValueError('回复不能为空。')
        if self.waiting:
            return self.reply(text)
        self._verify_boundary()
        self.messages.append({'role': 'user', 'origin': 'user', 'content': text})
        return self.agent.run(self.messages)

    @property
    def waiting(self) -> dict | None:
        outcome = latest_outcome(self.agent.store, self.messages)
        return outcome if outcome and outcome['status'] == 'needs_input' else None

    def _verify_boundary(self):
        if self.messages != self.agent.store.read_record():
            raise ValueError('Session已被其他客户端修改，请重新打开。')
        snapshot = self.agent.graph.get_state(self.agent.options())
        if snapshot.values:
            if (not snapshot.next and self.messages and self.messages[-1].get('cancelled_request')
                    and self.agent.record_hash() != snapshot.values.get('record_hash')):
                prefix = self.messages[:-1]
                previous = latest_outcome(self.agent.store, prefix)
                if (hashlib.sha256(json_text(prefix).encode('utf-8')).hexdigest() == snapshot.values['record_hash']
                        and previous and previous['status'] == 'needs_input'
                        and previous['request_id'] == self.messages[-1]['cancelled_request']):
                    # User cancellation persisted before a failed checkpoint update.
                    self.agent.graph.update_state(self.agent.options(), {
                        'outcome':self.messages[-1]['cancellation'],'record_hash':self.agent.record_hash(),
                        'model_index':len(self.messages)},as_node='finish')
                    snapshot = self.agent.graph.get_state(self.agent.options())
            self.agent.verify_record(snapshot.values)

    def reply(self, text: str, *, request_id: str | None = None, reply_id: str | None = None) -> dict:
        if self.pending:
            raise ValueError('请先续跑现有检查点。')
        waiting = self.waiting
        if not waiting or (request_id is not None and request_id != waiting['request_id']):
            raise ValueError('问题已处理或request_id与当前等待不符。')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('回复不能为空；可退出保留问题，或取消任务。')
        reply_id = reply_id or uuid4().hex
        if any(m.get('reply_id') == reply_id for m in self.messages):
            raise ValueError('该reply_id已提交，不重复执行。')
        self._verify_boundary()
        self.messages.append({'role':'user','origin':'user','content':text.strip(),
                              'in_reply_to':waiting['request_id'],'reply_id':reply_id})
        return self.agent.run(self.messages)

    @property
    def pending_answer(self) -> bool:
        return bool(not self.pending and self.messages and self.messages[-1].get('in_reply_to'))

    def continue_answer(self) -> dict:
        if not self.pending_answer:
            raise ValueError('没有尚未执行的补充信息。')
        snapshot = self.agent.graph.get_state(self.agent.options())
        prefix = self.messages[:-1]
        # Only one genuine linked user answer may be ahead of a terminal checkpoint.
        expected = hashlib.sha256(json_text(prefix).encode('utf-8')).hexdigest()
        if (snapshot.values.get('record_hash') != expected or
                snapshot.values.get('outcome', {}).get('status') != 'needs_input' or
                latest_outcome(self.agent.store, prefix)['request_id'] != self.messages[-1]['in_reply_to']):
            raise ValueError('补充信息与原等待检查点不符，拒绝自动执行。')
        if self.messages != self.agent.store.read_record():
            raise ValueError('Session记录已变化。')
        return self.agent.run(self.messages)

    def cancel(self) -> dict:
        if self.pending or not self.waiting:
            raise ValueError('只允许取消已安全等待的任务；运行中任务先保留现有现场。')
        self._verify_boundary()
        waiting = self.waiting
        result = {'ok':True,'status':'cancelled','summary':'用户取消，已有成果保留。',
                  'artifacts':waiting.get('artifacts',[]),'unresolved':waiting.get('unresolved',[])}
        self.messages.append({'role':'user','origin':'user','content':'取消当前等待任务。',
                              'cancelled_request':waiting['request_id'],'cancellation':result})
        self.agent.store.save(self.messages)
        self.agent.graph.update_state(self.agent.options(), {'outcome':result,
            'record_hash':self.agent.record_hash(),'model_index':len(self.messages)}, as_node='finish')
        return result

    def resume(self) -> dict[str, Any]:
        return self.agent.resume(self.messages)


@dataclass
class AgentFactory:
    config: AppConfig
    call: Callable[..., ModelReply]
    count_tokens: TokenCounter
    qgis: QGISClient
    catalog: dict[str, dict[str, Any]]

    def create(
        self, store: SessionStore, messages: list[dict[str, Any]], output_dir: Path,
        saver: BaseCheckpointSaver, instructions: str, *, extra_tools: list[Tool] | None = None,
        memory: MemoryStore | None = None, turn: MemoryTurn | None = None,
    ) -> Agent:
        plan = Plan.from_messages(messages)
        registry = ToolRegistry()
        history = ExecutionHistory(store, output_dir)
        planning = make_planning_tools(plan)
        tools = [
            *builtin_tools, *file_tools, make_search_tool(self.catalog),
            *make_qgis_python_tools(
                self.config.qgis.python_launcher,
                output_dir / "python_logs", self.config.qgis.font_files,
            ),
            *planning, make_session_tool(store), make_history_tool(history), *(extra_tools or []),
        ]
        if self.config.model.supports_images:
            tools.append(make_image_tool(store.root / f"{store.session_id}.assets" / "images"))
        if memory is not None:
            tools.extend(make_memory_tools(memory, store, messages, turn))
        def resolve_replay_tool(name: str) -> Tool:
            if name not in registry.tools:
                row = next((row for row in history.rows() if row['tool'] == name and row['integrity'] == 'ok'), None)
                algorithm = (row or {}).get('facts', {}).get('algorithm_id') or ((row or {}).get('result') or {}).get('algorithm_id')
                if not algorithm:
                    raise ValueError('历史工具无法解析为当前算法。')
                load_qgis_tool(self.qgis, self.catalog, registry, algorithm)
            return registry.get(name)
        tools.append(make_replay_tool(history, registry, resolve_replay_tool,
                                      (self.config.qgis.process_launcher, self.config.qgis.python_launcher)))
        for tool in tools:
            registry.register(tool)
        return Agent(
            registry=registry, base_tools=tools,
            load_qgis_tool=partial(load_qgis_tool, self.qgis, self.catalog, registry), plan=plan,
            instructions=instructions, chat=self.call, store=store,
            context=ContextManager(
                store, self.config.context,
                AuxiliaryCalls(self.call, store.record_model_call, self.count_tokens, self.config.context.request_token_limit),
                {tool.name for tool in tools},
            ),
            memory=memory, memory_turn=turn, checkpointer=saver, history=history,
        )


@contextmanager
def open_conversation(config: AppConfig, session_id: str) -> Iterator[Conversation]:
    store = SessionStore(config.session_root, session_id)
    config.session_root.mkdir(parents=True, exist_ok=True)
    output_dir = config.output_root / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    messages = store.read_record()
    qgis = QGISClient(config.qgis.process_launcher)
    catalog = load_catalog(qgis)
    with OpenAI(
        api_key=os.environ[config.api_key_env], base_url=config.model.base_url,
        max_retries=config.max_retries,
        http_client=DefaultHttpxClient(trust_env=config.trust_env),
    ) as client, SqliteSaver.from_conn_string(str(config.session_root / "checkpoints.sqlite")) as saver:
        factory = AgentFactory(config, partial(chat, client, config.model), make_token_counter(config.model), qgis, catalog)

        memory = MemoryStore(config.memory) if config.memory is not None else None
        turn = MemoryTurn() if memory is not None else None
        agent = factory.create(
            store, messages, output_dir, saver,
            render_prompt(
                "system.j2", output_dir=output_dir,
                supports_images=config.model.supports_images, supports_memory=memory is not None,
                skills=skill_index(),
            ),
            memory=memory, turn=turn,
        )
        yield Conversation(agent, messages, output_dir)
