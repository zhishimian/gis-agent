from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
import pytest

from gis_agent.agent import Agent
from gis_agent.application import Conversation
from gis_agent.core.auxiliary import AuxiliaryCalls
from gis_agent.core.context import ContextConfig, ContextManager
from gis_agent.core.model import ModelConfig, ModelReply, TokenCounter
from gis_agent.core.planning import Plan
from gis_agent.integrations.llm import make_token_counter
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.base import Tool
from gis_agent.tools.planning import make_planning_tools
from gis_agent.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def qgis_dir() -> Path:
    value = os.environ.get("GIS_AGENT_QGIS_DIR") or dotenv_values(ROOT / ".env").get("GIS_AGENT_QGIS_DIR")
    if not value:
        pytest.skip("请设置 GIS_AGENT_QGIS_DIR。")
    path = Path(value).expanduser().resolve()
    for launcher in ("qgis_process-qgis-ltr.bat", "python-qgis-ltr.bat"):
        if not (path / "bin" / launcher).is_file():
            pytest.skip("未找到 QGIS；可设置 GIS_AGENT_QGIS_DIR 为安装目录。")
    return path


@pytest.fixture(scope="session")
def count_tokens():
    return make_token_counter(ModelConfig())


@pytest.fixture
def points(tmp_path: Path) -> Path:
    path = tmp_path / "points.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": index},
                        "geometry": {"type": "Point", "coordinates": [x, 0]},
                    }
                    for index, x in enumerate((0, 1000), start=1)
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def unexpected_model_call(*args: Any) -> ModelReply:
    pytest.fail("这个确定性检查不应调用模型。")


def make_context(
    store: SessionStore,
    config: ContextConfig,
    pinned: set[str],
    count_tokens: TokenCounter,
    call: Callable[..., ModelReply] = unexpected_model_call,
) -> ContextManager:
    return ContextManager(
        store,
        config,
        AuxiliaryCalls(call, store.record_model_call, count_tokens, config.request_token_limit),
        pinned,
    )


def reply(call_id: str, name: str, arguments: dict[str, Any]) -> ModelReply:
    return ModelReply(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
                }
            ],
        },
        "fixed",
        None,
        "tool_calls",
    )


def response(number: int, name: str, arguments: dict[str, Any]) -> ModelReply:
    return ModelReply(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call-{number}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
                }
            ],
        },
        "offline",
        None,
        "tool_calls",
    )


def geojson(path: Path, features: list[tuple[dict, dict]]) -> Path:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
                "features": [
                    {"type": "Feature", "properties": properties, "geometry": geometry}
                    for properties, geometry in features
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def polygon(x: int) -> dict:
    return {"type": "Polygon", "coordinates": [[[x, 0], [x + 10, 0], [x + 10, 10], [x, 10], [x, 0]]]}


def make_graph_agent(
    store: SessionStore,
    call: Callable[..., ModelReply],
    count_tokens: TokenCounter,
    saver: Any,
    extra_tools: tuple[Tool, ...] = (),
) -> Agent:
    plan = Plan.from_messages(store.read_record())
    tools = [*make_planning_tools(plan), *extra_tools]
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return Agent(
        registry,
        tools,
        unexpected_model_call,
        plan,
        "按要求执行并复核。",
        call,
        store,
        make_context(store, ContextConfig(), {tool.name for tool in tools}, count_tokens, call),
        checkpointer=saver,
    )


def build(store: SessionStore, responses, saver: Any, tools: tuple[Tool, ...] = ()):
    replies = iter(responses)
    calls = []

    def model(messages, schemas):
        calls.append(messages)
        return next(replies)

    agent = make_graph_agent(store, model, make_token_counter(ModelConfig(tokenizer="bytes")), saver, tools)
    agent.history = ExecutionHistory(store, store.root.parent / "output")
    return Conversation(agent, store.read_record(), store.root.parent / "output"), calls


def ask(call_id: str = "ask") -> ModelReply:
    return reply(
        call_id,
        "finish_task",
        {
            "status": "needs_input",
            "summary": "Geometry complete; weighted result awaits population.",
            "question": "Provide population keyed by area ID, or approve unweighted analysis; weights change the result.",
            "reason": "missing_input",
            "unresolved": ["Population-weighted accessibility"],
        },
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """为外部 QGIS 启动及 live API 用例自动打标，支持快速分层验证。"""
    for item in items:
        if "qgis_dir" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.slow)
        if "live" in item.name:
            item.add_marker(pytest.mark.live)
