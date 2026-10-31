import json
import math
from functools import partial
from pathlib import Path

import httpx
import pytest
from openai import OpenAI

from gis_agent import config as configuration
from gis_agent.agent import Agent
from gis_agent.config import AppConfig, configured_model
from gis_agent.core.auxiliary import AuxiliaryCalls
from gis_agent.core.context import ContextConfig, ContextManager
from gis_agent.core.model import DEEPSEEK_MAX_OUTPUT_TOKENS, ModelConfig
from gis_agent.core.planning import Plan
from gis_agent.integrations.llm import chat, make_token_counter
from gis_agent.persistence.sessions import SessionStore, message_units
from gis_agent.tools.files import file_tools
from gis_agent.tools.planning import make_planning_tools
from gis_agent.tools.qgis_python import run_python_script
from gis_agent.tools.registry import ToolRegistry


ROOT = Path(__file__).resolve().parents[1]


def test_output_limit_and_request_budget(qgis_dir: Path, tmp_path: Path, monkeypatch) -> None:
    for key in list(configuration.os.environ):
        if key.startswith("GIS_AGENT_"):
            monkeypatch.delenv(key)
    monkeypatch.setattr(configuration, "load_dotenv", lambda _: None)
    monkeypatch.setenv("GIS_AGENT_QGIS_DIR", str(qgis_dir))
    config = AppConfig.from_env(tmp_path)
    assert config.model.max_tokens == ModelConfig().max_tokens == DEEPSEEK_MAX_OUTPUT_TOKENS == 393216
    assert config.context.request_token_limit == 638976
    assert config.context.request_token_limit + config.model.max_tokens + 16384 == config.model.context_window
    monkeypatch.setenv("GIS_AGENT_MAX_OUTPUT_TOKENS", "32768")
    assert configured_model().max_tokens == 32768
    monkeypatch.delenv("GIS_AGENT_MAX_OUTPUT_TOKENS")
    monkeypatch.setenv("GIS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("GIS_AGENT_MODEL", "offline-model")
    monkeypatch.setenv("GIS_AGENT_CONTEXT_WINDOW", "1000000")
    assert configured_model().max_tokens == 8192


@pytest.mark.parametrize("arguments", ['{"path":', '{"path":"unused","content":"complete"}'])
def test_length_rejects_entire_batch_and_keeps_raw_response(tmp_path: Path, arguments: str) -> None:
    target = tmp_path / "must-not-exist.txt"
    raw = {"role": "assistant", "content": None, "reasoning_content": "unfinished reasoning", "tool_calls": [
        {"id": "complete", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": str(target), "content": "forbidden"})}},
        {"id": "cut", "type": "function", "function": {"name": "write_file", "arguments": arguments}},
    ]}
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0,
            "model": "offline", "choices": [{"index": 0, "finish_reason": "length", "message": raw}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 393216, "total_tokens": 393236}})

    store = SessionStore(tmp_path, "cut")
    plan = Plan()
    tools = [*file_tools, *make_planning_tools(plan)]
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    model = ModelConfig(tokenizer="bytes")
    counter = make_token_counter(model)

    def unexpected(*_):
        pytest.fail("截断测试不应加载额外算法或调用辅助模型。")

    context = ContextManager(store, ContextConfig(), AuxiliaryCalls(unexpected, store.record_model_call, counter), {tool.name for tool in tools})
    with OpenAI(api_key="offline", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handle))) as client:
        agent = Agent(registry, tools, unexpected, plan, "保存测试文本。", partial(chat, client, model), store, context)
        result = agent.run([{"role": "user", "origin": "user", "content": "保存文件。"}])
    assert result["status"] == "blocked" and not target.exists()
    assert len(seen) == 1 and seen[0]["max_tokens"] == 393216
    saved = store.load()
    message_units(saved)
    cut = next(item for item in saved if item.get("response", {}).get("finish_reason") == "length")
    assert cut["response"]["raw_message"] == raw
    assert not cut.get("tool_calls") and not any(item["role"] == "tool" for item in saved)
    request_view = store.project(saved, 8000)
    assert not any("forbidden" in str(item) or "unfinished reasoning" in str(item) for item in request_view)
    usage = json.loads((tmp_path / "cut.calls.jsonl").read_text(encoding="utf-8"))
    assert usage["usage"]["completion_tokens"] == 393216


def test_large_complete_call_is_accepted_offline(tmp_path: Path) -> None:
    seen = []
    body = "x" * 40000
    target = tmp_path / "complete.txt"
    replies = iter([
        {"role": "assistant", "content": None, "tool_calls": [{"id": "write", "type": "function",
         "function": {"name": "write_file", "arguments": json.dumps({"path": str(target), "content": body})}}]},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "finish", "type": "function",
         "function": {"name": "finish_task", "arguments": json.dumps({"status": "completed", "summary": "完成", "artifacts": [str(target)]})}}]},
    ])

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0,
            "model": "offline", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": next(replies)}]})

    store = SessionStore(tmp_path, "complete")
    plan = Plan()
    tools = [*file_tools, *make_planning_tools(plan)]
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    model = ModelConfig(tokenizer="bytes")
    counter = make_token_counter(model)
    context = ContextManager(store, ContextConfig(), AuxiliaryCalls(None, store.record_model_call, counter), {tool.name for tool in tools})
    with OpenAI(api_key="offline", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handle))) as client:
        agent = Agent(registry, tools, lambda _: None, plan, "写入完整文本。", partial(chat, client, model), store, context)
        assert agent.run([{"role": "user", "origin": "user", "content": "写入文件。"}])["status"] == "completed"
    assert target.read_text(encoding="utf-8") == body
    assert len(seen) == 2 and all(item["max_tokens"] == 393216 for item in seen)
    message_units(store.load())


def test_holdout_selection_counterexample(qgis_dir: Path, tmp_path: Path) -> None:
    result = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", tmp_path / "logs",
        str(ROOT / "gis_agent/skills/gis-verification/scripts/validation_split.py"))
    assert result["ok"], result
    facts = result["result"]
    groups = [set(facts[name]) for name in ("train_ids", "validation_ids", "test_ids")]
    assert all(not left & right for i, left in enumerate(groups) for right in groups[i + 1:])
    assert facts["selected_on_validation"] == "low" and facts["selected_on_test"] == "high"
    assert facts["final_test_rmse"] == math.sqrt((16 + 25) / 2)
    assert facts["test_selected_rmse"] == math.sqrt((0 + 1) / 2)
    assert facts["test_selected_rmse"] < facts["final_test_rmse"]


def test_terrain_masks_nested_outlets_and_cache(qgis_dir: Path, tmp_path: Path) -> None:
    result = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", tmp_path / "logs",
        str(ROOT / "gis_agent/skills/gis-spatial-analysis/scripts/terrain_counterexamples.py"))
    assert result["ok"], result
    facts = result["result"]
    assert facts["upper_catchment"] == [0, 1, 2]
    assert facts["lower_catchment"] == [0, 1, 2, 3, 4] and facts["lower_partition"] == [3, 4]
    assert facts["unsafe_stencil_mean"] == (10 + 12 + 14 - 9999) / 4
    assert facts["masked_stencil_mean"] is None and facts["valid_stencil_mean"] == 13
    assert facts["valid_zero"] == 0
    assert facts["all_pairs"] == 100_000_000_000 and facts["bounded_pairs"] == 8_000_000
    assert facts["cache_key"] == facts["same_key"]
    assert all(facts[name] != facts["cache_key"] for name in ("changed_input", "changed_grid", "changed_code"))
