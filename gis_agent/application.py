import hashlib
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from openai import DefaultHttpxClient, OpenAI

from gis_agent.agent import Agent
from gis_agent.agents.delivery import DeliveryReview
from gis_agent.agents.subtasks import SubtaskRunner
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
from gis_agent.persistence.evidence import file_digest
from gis_agent.persistence.sessions import SessionStore
from gis_agent.persistence.json import json_text
from gis_agent.prompts import render_prompt
from gis_agent.tools.builtin import builtin_tools
from gis_agent.tools.cartography import make_cartography_finish, make_cartography_rule_tool, make_cartography_tools
from gis_agent.tools.delivery import make_delivery_tools
from gis_agent.tools.files import file_tools
from gis_agent.tools.images import make_image_tool
from gis_agent.tools.memory import make_memory_tools
from gis_agent.tools.planning import make_planning_tools
from gis_agent.tools.qgis_python import make_qgis_python_tools
from gis_agent.tools.registry import ToolRegistry
from gis_agent.tools.session import make_session_tool
from gis_agent.tools.base import Tool
from gis_agent.tools.verification import make_check_plan_tool, make_verification_tools, make_verifier_finish


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
        finish_tool: Tool | None = None, memory: MemoryStore | None = None,
        turn: MemoryTurn | None = None, require_review: bool = True, log_dir: Path | None = None,
        completion_check: Callable[[int], dict[str, Any]] | None = None,
    ) -> Agent:
        plan = Plan.from_messages(messages)
        registry = ToolRegistry()
        planning = make_planning_tools(plan)
        if finish_tool is not None:
            planning = [tool for tool in planning if tool.name != "finish_task"] + [finish_tool]
        tools = [
            *builtin_tools, *file_tools, make_search_tool(self.catalog),
            *make_qgis_python_tools(
                self.config.qgis.python_launcher,
                log_dir if log_dir is not None else self.config.output_root / "python_logs",
            ),
            *planning, make_session_tool(store), *(extra_tools or []),
        ]
        if self.config.model.supports_images:
            tools.append(make_image_tool(store.root / f"{store.session_id}.assets" / "images"))
        if memory is not None:
            tools.extend(make_memory_tools(memory, store, messages, turn))
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
            memory=memory, memory_turn=turn, checkpointer=saver, require_review=require_review,
            completion_check=completion_check,
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

        def create_verifier(
            store: SessionStore, messages: list[dict[str, Any]], output_dir: Path,
            saver: BaseCheckpointSaver, request: dict[str, Any],
        ) -> Agent:
            sources = {item["index"] for item in request["requirements"]}
            checks = request.get("checks", [])
            return factory.create(
                store, messages, output_dir, saver,
                render_prompt("verifier.j2", output_dir=output_dir, supports_images=config.model.supports_images),
                extra_tools=[make_check_plan_tool(store, messages, sources, initial_checks=checks)],
                finish_tool=make_verifier_finish(
                    messages, sources, output_dir, store=store, initial_checks=checks,
                ),
                require_review=False, log_dir=output_dir / "python_logs",
            )

        signature = hashlib.sha256(json_text({
            "version": 3, "model": asdict(config.model),
            "prompt": render_prompt("verifier.j2", output_dir="", supports_images=config.model.supports_images),
        }).encode("utf-8")).hexdigest()
        runner = SubtaskRunner(store, messages, output_dir, create_verifier, signature)
        delivery = DeliveryReview(runner)
        assets = Path(__file__).resolve().parent / "assets" / "cartography"
        runtime = Path(__file__).resolve().parent / "integrations" / "qgis" / "cartography_runtime.py"
        resources = [runtime, *sorted(assets.rglob("*.json")), *sorted(assets.rglob("*.py"))]

        def cartography_prompt(output_dir: Path | str) -> str:
            return render_prompt(
                "cartographer.j2", output_dir=output_dir, supports_images=config.model.supports_images,
                assets=assets, runtime_dir=runtime.parent, font_files=[str(path) for path in config.qgis.font_files],
            )

        def create_cartographer(
            store: SessionStore, messages: list[dict[str, Any]], output_dir: Path,
            saver: BaseCheckpointSaver, request: dict[str, Any],
        ) -> Agent:
            return factory.create(
                store, messages, output_dir, saver, cartography_prompt(output_dir),
                extra_tools=[make_cartography_rule_tool(assets / "rules.json")],
                finish_tool=make_cartography_finish(store, messages, output_dir, request),
                require_review=False, log_dir=output_dir / "python_logs",
            )

        cartography_signature = hashlib.sha256(json_text({
            "version": 1, "model": asdict(config.model), "prompt": cartography_prompt(""),
            "resources": [{"path": str(path), "sha256": file_digest(path)} for path in resources],
            "fonts": [{"path": str(path), "sha256": file_digest(path) if path.is_file() else None}
                      for path in config.qgis.font_files],
        }).encode("utf-8")).hexdigest()
        cartographer = SubtaskRunner(store, messages, output_dir, create_cartographer, cartography_signature, "cartographer")
        memory = MemoryStore(config.memory) if config.memory is not None else None
        turn = MemoryTurn() if memory is not None else None
        agent = factory.create(
            store, messages, output_dir, saver,
            render_prompt(
                "system.j2", output_dir=output_dir,
                supports_images=config.model.supports_images, supports_subtasks=True,
                supports_cartography=True, cartography_runtime=runtime.parent,
            ),
            extra_tools=[
                *make_verification_tools(runner), *make_delivery_tools(delivery),
                *make_cartography_tools(cartographer, resources, config.qgis.font_files, config.model.supports_images),
            ],
            completion_check=delivery.check, memory=memory, turn=turn,
        )
        yield Conversation(agent, messages, output_dir)
