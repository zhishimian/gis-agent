import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from openai import DefaultHttpxClient, OpenAI

from gis_agent.agent import Agent
from gis_agent.config import AppConfig
from gis_agent.core.auxiliary import AuxiliaryCalls
from gis_agent.core.context import ContextManager
from gis_agent.core.memory import MemoryStore, MemoryTurn
from gis_agent.core.planning import Plan
from gis_agent.integrations.llm import chat, make_token_counter
from gis_agent.integrations.qgis.adapter import load_qgis_tool
from gis_agent.integrations.qgis.catalog import load_catalog, make_search_tool
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.persistence.sessions import SessionStore
from gis_agent.prompts import render_prompt
from gis_agent.tools.builtin import builtin_tools
from gis_agent.tools.files import file_tools
from gis_agent.tools.memory import make_memory_tools
from gis_agent.tools.planning import make_planning_tools
from gis_agent.tools.qgis_python import make_qgis_python_tools
from gis_agent.tools.registry import ToolRegistry
from gis_agent.tools.session import make_session_tool


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
        self.messages.append({'role': 'user', 'origin': 'user', 'content': text})
        return self.agent.run(self.messages)

    def resume(self) -> dict[str, Any]:
        return self.agent.resume(self.messages)


@contextmanager
def open_conversation(config: AppConfig, session_id: str) -> Iterator[Conversation]:
    store = SessionStore(config.session_root, session_id)
    config.session_root.mkdir(parents=True, exist_ok=True)
    output_dir = config.output_root / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    messages = store.read_record()
    plan = Plan.from_messages(messages)
    memory = MemoryStore(config.memory) if config.memory is not None else None
    turn = MemoryTurn() if memory is not None else None
    registry = ToolRegistry()
    qgis = QGISClient(config.qgis.process_launcher)
    catalog = load_catalog(qgis)
    tools = [
        *builtin_tools, *file_tools, make_search_tool(catalog),
        *make_qgis_python_tools(config.qgis.python_launcher, config.output_root / 'python_logs'),
        *make_planning_tools(plan), make_session_tool(store),
    ]
    if memory is not None:
        tools.extend(make_memory_tools(memory, store, messages, turn))
    for tool in tools:
        registry.register(tool)
    with OpenAI(
        api_key=os.environ[config.api_key_env], base_url=config.model.base_url,
        max_retries=config.max_retries,
        http_client=DefaultHttpxClient(trust_env=config.trust_env),
    ) as client, SqliteSaver.from_conn_string(str(config.session_root / 'checkpoints.sqlite')) as saver:
        call = partial(chat, client, config.model)
        agent = Agent(
            registry=registry, base_tools=tools,
            load_qgis_tool=partial(load_qgis_tool, qgis, catalog, registry), plan=plan,
            instructions=render_prompt('system.j2', output_dir=output_dir), chat=call,
            store=store, context=ContextManager(
                store, config.context,
                AuxiliaryCalls(call, store.record_model_call, make_token_counter(config.model), config.context.request_token_limit),
                {tool.name for tool in tools},
            ), memory=memory, memory_turn=turn, checkpointer=saver,
        )
        yield Conversation(agent, messages, output_dir)
