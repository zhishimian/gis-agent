"""核心循环、90%高水位压缩、预算控制、检查点恢复与中止重连测试。"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from functools import partial
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any

from dotenv import dotenv_values
import httpx
from openai import DefaultHttpxClient, OpenAI
import pytest

from gis_agent import application, config as configuration
from gis_agent.agent import Agent
from gis_agent.config import AppConfig, QGISConfig, configured_model
from gis_agent.core.auxiliary import AuxiliaryCalls
from gis_agent.core.context import SUMMARY_SECTIONS, ContextConfig, ContextManager
from gis_agent.core.memory import MemoryConfig, MemoryStore, MemoryTurn, extract_memories
from gis_agent.core.model import DEEPSEEK_MAX_OUTPUT_TOKENS, ModelConfig, ModelReply, TokenCounter
from gis_agent.core.planning import Plan
from gis_agent.integrations.llm import chat, make_token_counter
from gis_agent.integrations.qgis.adapter import load_qgis_tool, tool_name
from gis_agent.integrations.qgis.catalog import load_catalog, make_search_tool
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.persistence.checkpoints import MemoryCheckpointer as InMemorySaver
from gis_agent.persistence.checkpoints import SqliteCheckpointer
from gis_agent.persistence.checkpoints import SqliteCheckpointer as SqliteSaver
from gis_agent.persistence.evidence import file_digest, tool_result
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.json import json_text
from gis_agent.persistence.sessions import SessionStore, message_units
from gis_agent.prompts import render_prompt
from gis_agent.tools.base import Tool
from gis_agent.tools.files import file_tools, read_file, write_file
from gis_agent.tools.memory import make_memory_tools
from gis_agent.tools.planning import finish_task, make_planning_tools
from gis_agent.tools.qgis_python import inspect_data, make_qgis_python_tools, run_python_script
from gis_agent.tools.registry import ToolRegistry
from gis_agent.tools.session import make_session_tool
from conftest import ask, build, geojson, make_context, make_graph_agent, reply, response, unexpected_model_call
from v83_budget import Budget, BudgetStop

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def verified_price_date(monkeypatch: pytest.MonkeyPatch) -> None:
    import v83_budget
    from datetime import datetime

    class CampaignDate(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 2, 23, 0, tzinfo=tz)

    monkeypatch.setattr(v83_budget, "datetime", CampaignDate)


def test_plan_blocks_unfinished_work_and_restores_session(tmp_path: Path, count_tokens) -> None:
    store = SessionStore(tmp_path, "planning")
    plan = Plan()
    registry = ToolRegistry()
    tools = make_planning_tools(plan)
    for tool in tools:
        registry.register(tool)
    replies = iter([
        reply("plan", "update_plan", {"goal": "检查交付", "steps": [{"content": "复核结果", "status": "pending"}]}),
        reply("review", "finish_task", {"status": "completed", "summary": "检查计划状态"}),
        reply("checked", "update_plan", {"goal": "检查交付", "steps": [{"content": "复核结果", "status": "completed"}]}),
        reply("finish", "finish_task", {"status": "completed", "summary": "已完成"}),
    ])
    agent = Agent(
        registry, tools, unexpected_model_call, plan, "按要求复核。", lambda *_: next(replies),
        store, make_context(store, ContextConfig(), {tool.name for tool in tools}, count_tokens),
    )
    messages = [{"role": "user", "origin": "user", "content": "检查交付。"}]
    assert agent.run(messages)["status"] == "completed"
    saved = store.load()
    results = [json.loads(item["content"]) for item in saved if item.get("tool_name") == "finish_task"]
    assert not results[0]["ok"] and "未完成" in results[0]["error"]
    assert results[1]["status"] == "completed"
    assert not Plan.from_messages(saved).unfinished()
    with pytest.raises(ValueError, match="未完成"):
        message_units(saved[:2])


def test_v6_result_archive_and_schema_budget(tmp_path: Path, count_tokens) -> None:
    store = SessionStore(tmp_path, "archive")
    result = {"ok": True, "nodata": float("nan"), "log": "结果日志" * 10000}
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "large", "function": {"name": "analysis", "arguments": "{}"}}]},
        store.tool_message("large", "analysis", result, 2000),
        {"role": "user", "origin": "user", "content": "继续检查。"},
    ]
    store.save(messages)
    original = store.path.read_bytes()
    stored = json.loads(store.asset_path(messages[1]["asset"]).read_text(encoding="utf-8"))
    assert stored["log"] == result["log"] and math.isnan(stored["nodata"])
    tools = [Tool("base", "常驻工具", {"type": "object"}, lambda: None)]
    tools += [Tool(f"candidate_{i}", "x" * 3500, {"type": "object"}, lambda: None) for i in range(3)]
    context = make_context(store, ContextConfig(request_token_limit=1800, tool_limit=2000), {"base"}, count_tokens)
    for _ in range(2):
        request = context.prepare("系统", messages, {}, tools)
        assert request.estimated_tokens <= 1800
        assert request.callable_names == {schema["function"]["name"] for schema in request.schemas}
        assert "base" in request.callable_names and "candidate_2" in request.callable_names
        assert "candidate_0" not in request.callable_names
    assert store.path.read_bytes() == original
    assert len(list(store.asset_dir.glob("*.json"))) == 1


def test_v6_summary_cache_and_original_message_readback(tmp_path: Path, count_tokens) -> None:
    store = SessionStore(tmp_path, "summary")
    messages = [
        {"role": "user", "origin": "user", "content": "结果必须保存为 GeoPackage。"},
        {"role": "assistant", "content": "已记录要求。"},
        {"role": "user", "origin": "user", "content": "继续。"},
    ]
    store.save(messages)
    summary = {key: [] for key in SUMMARY_SECTIONS}
    summary["requirements"] = [{"text": "保存为 GeoPackage", "sources": [0]}]
    config = ContextConfig(recent_users=1)
    fixed = lambda *_: ModelReply({"role": "assistant", "content": json.dumps(summary)}, "fixed", None, "stop")
    context = make_context(store, config, set(), count_tokens, fixed)
    context.compact(messages, 1)
    restored = make_context(store, config, set(), count_tokens)
    restored.load_state(messages)
    assert restored.covered == 1 and restored.summary == summary
    assert not any(item.get("content") == messages[0]["content"] for item in restored.history(messages, 2000))
    assert json.loads(store.read_messages(0)["text"])["content"] == messages[0]["content"]
    messages[0]["content"] = "改用 GeoJSON。"
    store.save(messages)
    invalidated = make_context(store, config, set(), count_tokens)
    invalidated.load_state(messages)
    assert invalidated.covered == 0


def test_v6_memory_update_delete_and_no_relearning(tmp_path: Path, count_tokens) -> None:
    session = SessionStore(tmp_path / "sessions", "memory")
    messages = [{"role": "user", "origin": "user", "content": "长期默认输出 GeoPackage。"}]
    session.save(messages)
    memory = MemoryStore(MemoryConfig(tmp_path))
    turn = MemoryTurn()
    tools = {tool.name: tool for tool in make_memory_tools(memory, session, messages, turn)}
    arguments = {"title": "交付格式", "body": "默认 GeoPackage", "category": "preference", "tags": ["格式"], "source_indices": [0]}
    created = tools["remember_memory"].run(arguments)
    assert created["ok"], created
    assert MemoryStore(memory.config).recall("交付格式")[0]["id"] == created["id"]
    messages.append({"role": "user", "origin": "user", "content": "将长期默认格式改为 GeoJSON。"})
    session.save(messages)
    arguments.update(record_id=created["id"], body="默认 GeoJSON", source_indices=[1])
    assert tools["remember_memory"].run(arguments)["action"] == "updated"
    assert tools["search_memory"].run({"query": created["id"]})[0]["body"] == "默认 GeoJSON"
    assert tools["forget_memory"].run({"record_id": created["id"]})["ok"]
    assert not MemoryStore(memory.config).records
    auxiliary = AuxiliaryCalls(unexpected_model_call, session.record_model_call, count_tokens)
    assert extract_memories(memory, session, messages, turn, auxiliary)["status"] == "no_new_evidence"


def test_v6_context_continues_below_token_limit(tmp_path: Path, count_tokens) -> None:
    store = SessionStore(tmp_path, "soft_limit")
    messages = [{"role": "user", "origin": "user", "content": "旧要求"}]
    for i in range(2):
        messages.extend([
            {"role": "assistant", "tool_calls": [{"id": str(i), "function": {"name": "analysis", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": str(i), "content": "{}"},
        ])
    messages.append({"role": "user", "origin": "user", "content": "x" * 4500})
    store.save(messages)
    context = make_context(store, ContextConfig(request_token_limit=2000, recent_users=1), set(), count_tokens)
    context.auxiliary.used = 100
    request = context.prepare("系统", messages, {}, [])
    assert request.estimated_tokens <= context.config.request_token_limit
    assert context.covered == 0


def test_v71_graph_continues_beyond_thirty_responses(tmp_path: Path, count_tokens) -> None:
    output = tmp_path / "progress.txt"

    def record_progress() -> dict[str, Any]:
        with output.open("a", encoding="utf-8") as file:
            file.write("完成一次\n")
        return {"ok": True}

    tool = Tool("record_progress", "记录执行结果", {"type": "object"}, record_progress)
    pending = {"goal": "执行记录", "steps": [{"content": "执行并复核", "status": "pending"}]}
    completed = {"goal": "执行记录", "steps": [{"content": "执行并复核", "status": "completed"}]}
    replies = iter([
        reply("plan", "update_plan", pending),
        *(reply(f"record_{index}", tool.name, {}) for index in range(35)),
        reply("review", "finish_task", {"status": "completed", "summary": "检查计划状态"}),
        reply("checked", "update_plan", completed),
        reply("finish", "finish_task", {"status": "completed", "summary": "完成"}),
    ])
    store = SessionStore(tmp_path / "sessions", "long_run")
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        agent = make_graph_agent(store, lambda *_: next(replies), count_tokens, saver, (tool,))
        assert agent.run([{"role": "user", "origin": "user", "content": "执行记录。"}])["status"] == "completed"
        snapshot = agent.graph.get_state(agent.options())
        assert not snapshot.next
        assert snapshot.values["responses_used"] == 39
        assert "messages" not in snapshot.values
    assert len(output.read_text(encoding="utf-8").splitlines()) == 35
    message_units(store.load())


def test_sqlite_resume_protects_version_and_tool_results(tmp_path: Path, count_tokens) -> None:
    output = tmp_path / "result.txt"

    def save_result() -> dict[str, Any]:
        with output.open("a", encoding="utf-8") as file:
            file.write("成果\n")
        return {"ok": True}

    tool = Tool("save_result", "保存成果", {"type": "object"}, save_result)
    replies = iter([
        reply("save", tool.name, {}),
    ])

    def disconnected_chat(*args: Any) -> ModelReply:
        response = next(replies, None)
        if response is None:
            raise ConnectionError("模拟模型连接中断。")
        return response

    store = SessionStore(tmp_path / "sessions", "resume")
    checkpoint = str(tmp_path / "checkpoints.sqlite")
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        agent = make_graph_agent(store, disconnected_chat, count_tokens, saver, (tool,))
        with pytest.raises(ConnectionError):
            agent.run([{"role": "user", "origin": "user", "content": "保存成果并复核。"}])
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        agent = make_graph_agent(
            store, lambda *_: reply("finish", "finish_task", {"status": "completed", "summary": "已完成"}),
            count_tokens, saver, (tool,),
        )
        agent.graph.update_state(agent.options(), {"version": 79}, as_node="tools")
        with pytest.raises(ValueError, match="旧版执行流程"):
            agent.resume(store.read_record())
        agent.graph.update_state(agent.options(), {"version": 790}, as_node="tools")
        assert agent.resume(store.read_record())["status"] == "completed"
        assert agent.graph.get_state(agent.options()).values["responses_used"] == 2
    assert output.read_text(encoding="utf-8") == "成果\n"
    results = [json.loads(item["content"]) for item in store.load() if item.get("tool_name") == "finish_task"]
    assert [item["status"] for item in results] == ["completed"]


def test_v71_uncertain_tool_execution_is_not_replayed(tmp_path: Path, count_tokens) -> None:
    output = tmp_path / "partial.txt"

    def interrupted_write() -> dict[str, Any]:
        with output.open("a", encoding="utf-8") as file:
            file.write("已经写入\n")
        raise OSError("模拟工具写入成果后中断。")

    tool = Tool("interrupted_write", "写入成果", {"type": "object"}, interrupted_write)
    store = SessionStore(tmp_path / "sessions", "uncertain")
    checkpoint = str(tmp_path / "checkpoints.sqlite")
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        agent = make_graph_agent(store, lambda *_: reply("write", tool.name, {}), count_tokens, saver, (tool,))
        with pytest.raises(OSError):
            agent.run([{"role": "user", "origin": "user", "content": "写入成果。"}])
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        agent = make_graph_agent(store, unexpected_model_call, count_tokens, saver, (tool,))
        with pytest.raises(ValueError, match="检查点"):
            agent.resume(store.read_record())
    assert output.read_text(encoding="utf-8") == "已经写入\n"
    assert store.read_record()[1]["executions"]["write"] == "started"


def test_v71_invalid_memory_arguments_cannot_complete_task(tmp_path: Path, count_tokens) -> None:
    store = SessionStore(tmp_path / "sessions", "memory_error")
    messages = [{"role": "user", "origin": "user", "content": "请记住默认使用 GeoPackage。"}]
    plan = Plan()
    memory = MemoryStore(MemoryConfig(tmp_path, auto_extract=False))
    turn = MemoryTurn()
    tools = [*make_planning_tools(plan), *make_memory_tools(memory, store, messages, turn)]
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    invalid = reply("remember", "remember_memory", {})
    invalid.message["tool_calls"][0]["function"]["arguments"] = "{"
    replies = iter([
        invalid,
        reply("answer", "finish_task", {"status": "answer", "summary": "已记住"}),
        reply("blocked", "finish_task", {"status": "blocked", "summary": "记忆写入未完成"}),
    ])
    call = lambda *_: next(replies)
    agent = Agent(
        registry, tools, unexpected_model_call, plan, "按要求保存记忆。", call, store,
        make_context(store, ContextConfig(), {tool.name for tool in tools}, count_tokens, call),
        memory=memory, memory_turn=turn,
    )
    assert agent.run(messages)["status"] == "blocked"
    assert not memory.records


def test_live_api_qgis_buffer_and_memory(tmp_path: Path, qgis_dir: Path, points: Path, count_tokens) -> None:
    key = os.environ.get("DEEPSEEK_API_KEY") or dotenv_values(ROOT / ".env").get("DEEPSEEK_API_KEY")
    if not key:
        pytest.skip("缺少 DEEPSEEK_API_KEY，真实 API 验收未执行。")
    model = ModelConfig()
    client = OpenAI(
        api_key=key, base_url=model.base_url, max_retries=3, timeout=90,
        http_client=DefaultHttpxClient(trust_env=False),
    )
    qgis = QGISClient(qgis_dir / "bin" / "qgis_process-qgis-ltr.bat")
    registry = ToolRegistry()
    catalog = load_catalog(qgis)

    def checked_write(path: str, content: str, overwrite: bool = False) -> dict[str, Any]:
        assert Path(path).resolve().is_relative_to(tmp_path.resolve()), "测试只允许写入临时目录。"
        return write_file(path, content, overwrite)

    base_tools = [
        make_search_tool(catalog),
        *[Tool(tool.name, tool.description, tool.parameters, checked_write if tool.name == "write_file" else tool.function) for tool in file_tools],
        *make_qgis_python_tools(qgis_dir / "bin" / "python-qgis-ltr.bat", tmp_path / "python_logs"),
    ]
    for tool in base_tools:
        registry.register(tool)
    sizes = []

    def real_chat(messages, schemas):
        sizes.append(count_tokens(messages, schemas))
        assert sizes[-1] <= ContextConfig().request_token_limit
        return chat(client, model, messages, schemas)

    output = tmp_path / "buffer.gpkg"
    report = tmp_path / "report.json"
    prompt = f"""
这是一个小型实际 GIS 任务。所有读写限制在 {tmp_path}，不要修改项目或其他数据。
先检查输入 {points} 的 CRS 和要素数。
先搜索再调用具体 native:buffer 工具，为每个点做 100 米缓冲，每象限 16 段，不融合。
缓冲这一步必须调用具体 QGIS 工具，不能用脚本替代。保存到 {output}。
检查输出，再写 {report}，字段为 feature_count、crs、buffer_distance_m、output_path。
规划、执行并按原始要求复核，最后报告 completed。不要只口头声称完成。
另请记住长期偏好：以后的 GIS 交付默认使用 GeoPackage。
""".strip()
    session_store = SessionStore(tmp_path / "sessions", "acceptance")
    plan = Plan()
    memory = MemoryStore(MemoryConfig(tmp_path))
    turn = MemoryTurn()
    messages = [{"role": "user", "origin": "user", "content": prompt}]
    extra = [*make_planning_tools(plan), make_session_tool(session_store)]
    extra.extend(make_memory_tools(memory, session_store, messages, turn))
    for tool in extra:
        registry.register(tool)
    active = [*base_tools, *extra]
    try:
        agent = Agent(
            registry, active, partial(load_qgis_tool, qgis, catalog, registry), plan,
            render_prompt("system.j2", output_dir=tmp_path / "outputs", supports_images=False,
                          supports_memory=True, skills=application.skill_index()), real_chat,
            session_store, make_context(session_store, ContextConfig(), {tool.name for tool in active}, count_tokens, real_chat),
            memory=memory, memory_turn=turn,
        )
        assert agent.run(messages)["status"] == "completed"
    finally:
        client.close()

    session = SessionStore(tmp_path / "sessions", "acceptance")
    messages = session.load()
    finish_results = [json.loads(item["content"]) for item in messages if item.get("tool_name") == "finish_task"]
    assert finish_results and finish_results[-1].get("status") == "completed", finish_results
    assert all(item.get("status") != "review_required" for item in finish_results)
    assert Plan.from_messages(messages).steps and not Plan.from_messages(messages).unfinished()
    assert any(item.get("tool_name") == "search_qgis_tools" for item in messages)
    assert any(item.get("tool_name") == tool_name("native:buffer") and json.loads(item["content"]).get("ok") for item in messages)
    assert output.is_file() and report.is_file()

    verify = tmp_path / "verify_output.py"
    verify.write_text(
        "import json, sys\n"
        "from qgis.core import QgsApplication, QgsVectorLayer\n"
        "app = QgsApplication([], False)\napp.initQgis()\n"
        "layer = QgsVectorLayer(sys.argv[1], 'buffer', 'ogr')\n"
        "assert layer.isValid()\n"
        "features = list(layer.getFeatures())\n"
        "print(json.dumps({'count':len(features), 'crs':layer.crs().authid(),\n"
        "'valid':all(f.geometry().isGeosValid() for f in features),\n"
        "'areas':[f.geometry().area() for f in features]}))\n"
        "del features, layer\napp.exitQgis()\n",
        encoding="utf-8",
    )
    actual = run_python_script(qgis_dir / "bin" / "python-qgis-ltr.bat", tmp_path / "verification_logs", str(verify), [str(output)])
    assert actual["ok"], actual
    geometry = json.loads(Path(actual["stdout_path"]).read_text(encoding="utf-8"))
    assert geometry["count"] == 2 and geometry["crs"] == "EPSG:3857" and geometry["valid"]
    expected_area = 64 * 100 ** 2 * math.sin(2 * math.pi / 64) / 2
    assert geometry["areas"] == pytest.approx([expected_area, expected_area], rel=1e-6)
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["feature_count"] == 2 and data["crs"] == geometry["crs"]
    assert data["buffer_distance_m"] == 100 and Path(data["output_path"]).resolve() == output.resolve()
    remembered = MemoryStore(MemoryConfig(tmp_path)).recall("交付格式")
    assert any(item.get("category") == "preference" and any(word in item["body"].lower() for word in ("geopackage", "gpkg")) for item in remembered), remembered
    calls = [json.loads(line) for line in (session.root / "acceptance.calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert not any(item.get("purpose") == "memory_maintenance" and item.get("status") == "failed" for item in calls), calls[-1]
    print(f"验收通过：2 个 100 米缓冲面、CRS、面积、报告、计划复核与跨 Session 记忆；调用 {len(sizes)} 次，目录：{tmp_path}")


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


def test_context_keeps_history_prefix_and_stable_schemas(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, "prefix")
    counter = make_token_counter(ModelConfig(tokenizer="bytes"))
    context = ContextManager(store, ContextConfig(), AuxiliaryCalls(None, store.record_model_call, counter), {"a", "b"})
    tools = [Tool(name, name, {"type": "object"}, lambda: None) for name in ["b", "a"]]
    messages = [{"role": "user", "origin": "user", "content": "读取资料回答问题。"}]
    first = context.prepare("固定系统", messages, {"latest_user_message": 0}, tools)
    messages.extend([response(1, "a", {}).message, store.tool_message("call-1", "a", {"ok": True}, 8000)])
    second = context.prepare("固定系统", messages, {"latest_user_message": 0, "recent": 2}, list(reversed(tools)))
    assert first.messages[:-1] == second.messages[:len(first.messages) - 1]
    assert first.schemas == second.schemas
    assert second.messages[-1]["origin"] == "program"
    assert not any("当前运行数据" in str(item) for item in second.messages[:-1])
    assert store.read_record() == []


def test_result_archive_is_immutable_and_checks_hash(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, "archive")
    original = {"ok": True, "result": "测量" * 10000}
    message = store.tool_message("check", "measurement", original, 2000)
    store.save([message])
    before = store.path.read_bytes()
    assert tool_result(store, message) == original
    assert len(store.project([message], 2000)[0]["content"]) < 2100
    assert store.path.read_bytes() == before
    store.asset_path(message["asset"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="校验失败"):
        store.project([message], 2000)


def test_finish_paths_and_unknown_work_are_checked(tmp_path: Path) -> None:
    assert finish_task("completed", "已完成", [str(tmp_path)])["ok"]
    assert not finish_task("completed", "已完成", [str(tmp_path / "missing")])["ok"]
    assert not finish_task("completed", "已完成", unresolved=["结果单位尚不明确"])["ok"]
    assert finish_task("blocked", "需要确认单位", unresolved=["单位未确认"])["ok"]
    assert not finish_task("completed", "完成", artifacts={})["ok"]
    assert not finish_task("completed", "完成", unresolved={})["ok"]


def test_sdk_request_trace_contains_hashes_and_preserves_deepseek_protocol() -> None:
    seen = []
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0,
            "model": "offline", "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "完成"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}})
    messages = [{"role": "assistant", "content": "已有结果", "reasoning_content": "测试协议内容"}, {"role": "user", "content": "用户私有正文"}]
    with OpenAI(api_key="offline-test", http_client=httpx.Client(transport=httpx.MockTransport(handle))) as client:
        result = chat(client, ModelConfig(), messages, [])
    assert seen[0]["messages"][0]["reasoning_content"] == "测试协议内容"
    assert "用户私有正文" not in json.dumps(result.request, ensure_ascii=False)
    assert "测试协议内容" not in json.dumps(result.request, ensure_ascii=False)
    assert len(result.request["messages"]) == 2


def test_single_agent_buffer_can_finish_and_read_only_question_can_answer(qgis_dir: Path, tmp_path: Path, monkeypatch) -> None:
    source = geojson(tmp_path / "point.geojson", [({"id": 1}, {"type": "Point", "coordinates": [0, 0]})])
    config = AppConfig(tmp_path, tmp_path / "sessions", tmp_path / "outputs",
                       QGISConfig(qgis_dir / "bin/qgis_process-qgis-ltr.bat", qgis_dir / "bin/python-qgis-ltr.bat"),
                       ModelConfig(tokenizer="bytes"), ContextConfig(), None, api_key_env="GIS_AGENT_TEST_KEY")
    monkeypatch.setenv(config.api_key_env, "offline")
    output = config.output_root / "single" / "buffer.gpkg"
    steps = iter([
        ("search_qgis_tools", {"query": "native:buffer", "limit": 1}),
        ("run_qgis_algorithm", {"algorithm_id": "native:buffer", "parameters": {"INPUT": str(source), "DISTANCE": 500, "SEGMENTS": 32, "OUTPUT": str(output)}}),
        ("summarize_fields", {"source": str(output), "fields": ["id"], "check_geometry": True}),
        ("finish_task", {"status": "completed", "summary": "成果可读，已检查几何。", "artifacts": [str(output)]}),
    ])
    calls = []
    seen_schemas = []
    def fixed(client, model, view, schemas):
        seen_schemas.append(json.dumps(schemas, sort_keys=True, ensure_ascii=False))
        names = {item["function"]["name"] for item in schemas}
        assert not {"verify_task", "review_delivery", "cartograph_task", "render_map", "local_replay"} & names
        assert "gis-verification/SKILL.md" in view[0]["content"]
        name, arguments = next(steps)
        assert name in names
        calls.append(name)
        return response(len(calls), name, arguments)
    monkeypatch.setattr(application, "chat", fixed)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    with application.open_conversation(config, "single") as conversation:
        outcome = conversation.send("做500米缓冲，SEGMENTS=32，核对字段和几何后交付。")
        assert outcome["status"] == "completed" and outcome["artifacts"] == [str(output)]
        assert len(set(seen_schemas)) == 1  # 跨轮次顶层工具 Schema 字节恒定，不破 KV 缓存
        saved = conversation.agent.store.load()
        check = next(tool_result(conversation.agent.store, item) for item in saved if item.get("tool_name") == "summarize_fields")
        assert check["ok"] and check["result"]["geometry"] == {"empty": 0, "invalid": 0}
        assert conversation.agent.graph.get_state(conversation.agent.options()).values["responses_used"] == 4
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    steps = iter([("read_file", {"path": str(ROOT / "gis_agent/skills/gis-verification/SKILL.md")}),
                  ("finish_task", {"status": "answer", "summary": "已读取核查方法。"})])
    with application.open_conversation(config, "single") as conversation:
        assert conversation.send("解释一下核查方法。 ")["status"] == "answer"


def test_budget_reserves_before_sending_and_disables_retries(tmp_path):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200,json={'id':'m','object':'chat.completion','model':'deepseek-flash',
          'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'done'}}],
          'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15,
                   'prompt_cache_hit_tokens':2,'prompt_cache_miss_tokens':8}})
    model = replace(ModelConfig(),supports_images=False,image_tokens=0,max_tokens=512)
    with OpenAI(api_key='offline',base_url='https://api.deepseek.com',max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
        blocked = Budget(client,model,tmp_path/'blocked.json',threshold=.00001)
        with pytest.raises(BudgetStop): blocked([{'role':'user','content':'x'}],[])
        assert len(requests)==0
        budget=Budget(client,model,tmp_path/'ok.json')
        budget([{'role':'user','content':'x'}],[])
        assert len(requests)==1 and budget.spent==pytest.approx((2*.04+8*2+5*8)/1e6)
        budget.spent=1.69
        with pytest.raises(BudgetStop): budget([{'role':'user','content':'x'}],[])
        assert len(requests)==1


def test_api_error_keeps_reservation_and_stops(tmp_path):
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(500,json={'error':{'message':'offline failure'}})
    model=replace(ModelConfig(),supports_images=False,image_tokens=0,max_tokens=512)
    with OpenAI(api_key='offline',base_url='https://api.deepseek.com',max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
        budget=Budget(client,model,tmp_path/'error.json')
        with pytest.raises(Exception): budget([{'role':'user','content':'x'}],[])
        assert budget.stopped and budget.spent>0 and len(requests)==1


def test_status_contracts_and_partial_artifacts(tmp_path):
    assert not finish_task('needs_input','missing input')['ok']
    assert finish_task('needs_input','missing input',question='Which CRS is documented?',reason='missing_input')['ok']
    assert not finish_task('partial','some work')['ok']
    assert finish_task('partial','Known metadata found; one layer is unavailable',unresolved=['missing layer'])['ok']
    path=tmp_path/'done.txt';path.write_text('four completed outputs')
    assert finish_task('partial','four completed',[str(path)],['fifth missing'])['ok']
    assert not finish_task('completed','all',[str(path)],['still missing'])['ok']
    assert not finish_task('blocked','x',reason='SyntaxError')['ok']


def test_real_gis_wait_save_reopen_answer_complete(qgis_dir,tmp_path):
    store=SessionStore(tmp_path/'sessions','gis_handoff');output=tmp_path/'output';output.mkdir()
    script=output/'prefix.py'
    script.write_text("import geopandas as gpd,sys\nfrom shapely.geometry import Point\n"
        "gpd.GeoDataFrame({'id':[1]},geometry=[Point(500000,4400000).buffer(500,quad_segs=32)],crs=32650).to_file(sys.argv[1],layer='buffer',index=False)\n")
    path=output/'buffer.gpkg';starts=[]
    def compute():
        starts.append(1)
        return run_python_script(qgis_dir/'bin/python-qgis-ltr.bat',output/'python_logs',str(script),[str(path)])
    tool=Tool('buffer_stage','GIS prefix',{'type':'object'},compute)
    with SqliteSaver.from_conn_string(str(tmp_path/'checkpoint.sqlite')) as saver:
        conv,calls=build(store,[reply('compute','buffer_stage',{}),ask()],saver,(tool,))
        assert conv.send('Buffer the point and calculate population-weighted access.')['status']=='needs_input'
        request=conv.waiting['request_id'];frozen=path.read_bytes()
        prefix=store.path.read_bytes()
        assert len(calls)==2 and len(starts)==1 and not conv.pending
    with SqliteSaver.from_conn_string(str(tmp_path/'checkpoint.sqlite')) as saver:
        conv,calls=build(store,[reply('done','finish_task',{'status':'completed','summary':'Approved unweighted geometry delivered.',
                                  'artifacts':[str(path)]})],saver,(tool,))
        assert conv.waiting['request_id']==request
        assert store.path.read_bytes()==prefix
        assert conv.reply('Use unweighted analysis for this task.',request_id=request,reply_id='answer1')['status']=='completed'
        assert not conv.waiting and len(calls)==1 and len(starts)==1 and path.read_bytes()==frozen
        assert any(m.get('in_reply_to')==request for m in store.read_record())
        with pytest.raises(ValueError): conv.reply('again',request_id=request,reply_id='answer1')
        assert any(row['tool']=='buffer_stage' and row['status']=='succeeded' for row in conv.agent.history.rows())
    check=output/'check.py';check.write_text("import geopandas as gpd,json,os,sys,math\nfrom pathlib import Path\n"
        "d=gpd.read_file(sys.argv[1]);assert d.crs.to_epsg()==32650 and len(d)==1 and d.geometry.is_valid.all()\n"
        "assert abs(d.geometry.area.iloc[0]-785082.7892387)<.001\n"
        "Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'area':float(d.geometry.area.iloc[0])}))")
    assert run_python_script(qgis_dir/'bin/python-qgis-ltr.bat',output/'checks',str(check),[str(path)])['ok']


def test_multiple_answers_invalid_duplicate_cancel_and_reload(tmp_path):
    store=SessionStore(tmp_path,'answers');saver=InMemorySaver()
    conv,calls=build(store,[ask(),ask('ask2')],saver)
    conv.send('Weighted task with missing data')
    first=conv.waiting['request_id']
    with pytest.raises(ValueError): conv.reply(' ',request_id=first)
    with pytest.raises(ValueError): conv.reply('x',request_id='stale')
    conv.reply('I have no table yet',request_id=first,reply_id='one')
    assert conv.waiting['request_id']!=first
    with pytest.raises(ValueError): conv.reply('retry',reply_id='one')
    conv.cancel();assert not conv.waiting and len(calls)==2
    reopened,_=build(store,[],saver)
    assert not reopened.waiting
    from gis_agent.persistence.interaction import latest_outcome
    assert latest_outcome(store,store.read_record())['status']=='cancelled'


def test_reply_saved_before_first_model_can_restart_safely(tmp_path):
    store=SessionStore(tmp_path,'saved_reply');saver=InMemorySaver()
    conv,_=build(store,[ask()],saver);conv.send('Need weights')
    request=conv.waiting['request_id']
    messages=store.read_record()+[{'role':'user','origin':'user','content':'Approved unweighted',
                                 'in_reply_to':request,'reply_id':'durable'}]
    store.save(messages)
    conv,calls=build(store,[reply('done','finish_task',{'status':'answer','summary':'Approval recorded'})],saver)
    assert conv.pending_answer and conv.continue_answer()['status']=='answer' and len(calls)==1


def test_answer_preserves_known_dynamic_algorithms(tmp_path):
    store=SessionStore(tmp_path,'known_tools');saver=InMemorySaver()
    conv,_=build(store,[ask(),reply('done','finish_task',{'status':'answer','summary':'Updated scope accepted'})],saver)
    conv.send('Task awaiting a business choice')
    conv.agent.graph.update_state(conv.agent.options(),{'algorithms':['native:buffer']},as_node='finish')
    conv.agent.load_qgis_tool=lambda _: Tool('qgis_native_buffer','known',{'type':'object'},lambda: {'ok':True})
    original=conv.agent.chat
    def checked(messages,schemas):
        assert any(s['function']['name']=='qgis_native_buffer' for s in schemas)
        return original(messages,schemas)
    conv.agent.chat=checked
    assert conv.reply('Use the existing buffer result')['status']=='answer'


def test_cancellation_checkpoint_write_window_and_tampered_answer(tmp_path,monkeypatch):
    store=SessionStore(tmp_path,'cancel_window');saver=InMemorySaver()
    conv,_=build(store,[ask()],saver);conv.send('Missing factor')
    original=conv.agent.graph.update_state
    def fail(*a,**k): raise OSError('simulated checkpoint write failure')
    monkeypatch.setattr(conv.agent.graph,'update_state',fail)
    with pytest.raises(OSError): conv.cancel()
    monkeypatch.setattr(conv.agent.graph,'update_state',original)
    reopened,calls=build(store,[reply('done','finish_task',{'status':'answer','summary':'New request answered'})],saver)
    assert reopened.send('A new independent question')['status']=='answer' and len(calls)==1
    # Arbitrary historical edits must never obtain this narrow recovery.
    records=store.read_record();records[0]['content']='tampered';store.save(records)
    broken,_=build(store,[],saver)
    with pytest.raises(ValueError): broken.send('continue')


@pytest.mark.parametrize('mode',['normal','discover','repair','unsupported','partial','topology'])
def test_outcome_routes_keep_original_success_free_of_confirmation(tmp_path,mode):
    store=SessionStore(tmp_path,mode);saver=InMemorySaver();runs=[]
    path=tmp_path/'four.txt'
    def work():
        runs.append(1)
        if mode=='repair' and len(runs)==1: return {'ok':False,'error':'recoverable field typo'}
        path.write_text('trusted work')
        return {'ok':True,'actual_layer':'known','crs':'EPSG:32650','outputs':{'data':str(path)}}
    tool=Tool('operation','work',{'type':'object'},work)
    responses=[reply('work','operation',{})]
    if mode=='repair': responses.append(reply('fixed','operation',{}))
    if mode in {'normal','discover','repair'}:
        final={'status':'completed','summary':'Data found or code repaired','artifacts':[str(path)]}
    elif mode=='unsupported':
        final={'status':'blocked','summary':'Available formats cannot encode this requirement','unresolved':['Unsupported format'],'reason':'unsupported'}
    else:
        final={'status':'partial','summary':'Reliable independent work retained','artifacts':[str(path)],
               'unresolved':['No population' if mode=='partial' else 'Unverified road connections'],'reason':'missing_input' if mode=='partial' else 'data_quality'}
    responses.append(reply('finish','finish_task',final))
    conv,calls=build(store,responses,saver,(tool,))
    result=conv.send('Complete feasible independent work')
    assert result['status']==final['status'] and not conv.waiting
    assert len(calls)==(3 if mode=='repair' else 2)
    assert path.exists()


@pytest.mark.slow
def test_agent_runs_with_langgraph_and_tokenizers_blocked(tmp_path: Path) -> None:
    """强制屏蔽 langgraph 与 tokenizers 模块，验证纯标准库状态机与 SQLite 检查点独立运行。"""
    probe = tmp_path / "no_heavy_deps.py"
    root = Path(__file__).resolve().parents[1]
    probe.write_text(
        f"""import json, sys
from pathlib import Path
sys.path.insert(0, {str(root)!r})
sys.modules['langgraph'] = None
sys.modules['tokenizers'] = None

from gis_agent.agent import Agent
from gis_agent.core.auxiliary import AuxiliaryCalls
from gis_agent.core.context import ContextConfig, ContextManager
from gis_agent.core.model import ModelConfig, ModelReply
from gis_agent.core.planning import Plan
from gis_agent.integrations.llm import make_token_counter
from gis_agent.persistence.checkpoints import SqliteCheckpointer
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.planning import make_planning_tools
from gis_agent.tools.registry import ToolRegistry

work_dir = Path({str(tmp_path / 'run')!r})
store = SessionStore(work_dir / 'sessions', 'pure')
plan = Plan()
tools = make_planning_tools(plan)
reg = ToolRegistry()
for t in tools:
    reg.register(t)
counter = make_token_counter(ModelConfig())
ctx = ContextManager(store, ContextConfig(), AuxiliaryCalls(None, store.record_model_call, counter), {{t.name for t in tools}})
events = []
reply = ModelReply({{'role': 'assistant', 'content': None, 'tool_calls': [{{'id': 'f1', 'type': 'function', 'function': {{'name': 'finish_task', 'arguments': json.dumps({{'status': 'answer', 'summary': 'ok'}})}}}}]}}, 'offline', None, 'tool_calls')

with SqliteCheckpointer.from_conn_string(work_dir / 'ckpt.sqlite') as saver:
    agent = Agent(reg, tools, None, plan, 'test', lambda *_: reply, store, ctx, checkpointer=saver, on_event=lambda e: events.append(e.type))
    out = agent.run([{{'role': 'user', 'origin': 'user', 'content': 'hello'}}])
assert out['status'] == 'answer'
assert events == ['turn_started', 'model_replied', 'tool_started', 'tool_finished', 'turn_finished']
print('PURE_OK')
""",
        encoding="utf-8",
    )
    proc = subprocess.run([sys.executable, "-B", str(probe)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0 and "PURE_OK" in proc.stdout, proc.stderr


def test_crash_window_reconciles_finished_batch_without_reexecuting_tool(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions", "window")
    db_path = tmp_path / "ckpt.sqlite"
    runs = []

    def side_effect() -> dict[str, Any]:
        runs.append(1)
        return {"ok": True, "val": 99}

    plan = Plan()
    work_tool = Tool("compute", "计算", {"type": "object"}, side_effect)
    tools = [*make_planning_tools(plan), work_tool]
    registry = ToolRegistry()
    for t in tools:
        registry.register(t)
    counter = make_token_counter(ModelConfig(tokenizer="bytes"))

    # 模拟：model 节点写完检查点 ("tools",)，tools 节点实际跑完并写入 Session JSON ("finished")，但 SQLite 尚未推进即进程退出
    user_msg = {"role": "user", "origin": "user", "content": "执行计算"}
    assistant_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "compute", "arguments": "{}"}}],
        "response": {"model": "offline", "usage": None, "finish_reason": "tool_calls"},
    }
    store.save([user_msg, assistant_call])
    import hashlib
    model_hash = hashlib.sha256(json_text([user_msg, assistant_call]).encode("utf-8")).hexdigest()

    with SqliteCheckpointer.from_conn_string(db_path) as saver:
        saver.put(
            "window",
            {
                "version": 900,
                "turn_start": 0,
                "model_index": 1,
                "responses_used": 1,
                "execution_started": True,
                "algorithms": [],
                "callable_names": sorted(t.name for t in tools),
                "memory_errors": [],
                "handled_sources": [],
                "handled_bodies": [],
                "background": "",
                "record_hash": model_hash,
                "auxiliary_used": 0,
                "outcome": None,
            },
            ("tools",),
        )

    # Session JSON 已经完成了该工具批次落盘
    finished_assistant = {**assistant_call, "executions": {"c1": "finished"}}
    tool_msg = store.tool_message("c1", "compute", {"ok": True, "val": 99}, 8000)
    store.save([user_msg, finished_assistant, tool_msg])

    with SqliteCheckpointer.from_conn_string(db_path) as saver:
        ctx = ContextManager(store, ContextConfig(), AuxiliaryCalls(None, store.record_model_call, counter), {t.name for t in tools})
        agent = Agent(
            registry, tools, None, plan, "继续",
            lambda *_: reply("c2", "finish_task", {"status": "completed", "summary": "对账恢复成功"}),
            store, ctx, checkpointer=saver,
        )
        outcome = agent.resume(store.read_record())
        assert outcome["status"] == "completed"
        assert len(runs) == 0  # 未重复执行已完成副作用工具


def test_ninety_percent_compaction_triggers_before_hard_limit(tmp_path: Path) -> None:
    """超过可用输入预算 90% 时主动压缩旧工具批次，低于 90% 保持原前缀不变。"""
    store = SessionStore(tmp_path, "compact90")
    messages: list[dict[str, Any]] = [{"role": "user", "origin": "user", "content": "开始分析任务。"}]
    for idx in range(3):
        messages.extend(
            [
                {
                    "role": "assistant",
                    "tool_calls": [{"id": f"c{idx}", "function": {"name": "analysis", "arguments": "{}"}}],
                },
                {
                    "role": "tool",
                    "tool_call_id": f"c{idx}",
                    "tool_name": "analysis",
                    "content": json.dumps({"ok": True, "detail": f"step {idx}: " + ("alpha beta " * 140)}),
                },
            ]
        )
    store.save(messages)

    count_tokens = make_token_counter(ModelConfig())
    # 先测量完整视图实际 token 数，构造刚好处于 90%～99% 区间的预算上限
    probe_ctx = ContextManager(
        store,
        ContextConfig(request_token_limit=50000, compact_ratio=0.9, recent_batches=2, recent_users=1),
        AuxiliaryCalls(lambda *_: pytest.fail("未达阈值不应总结"), store.record_model_call, count_tokens),
        set(),
    )
    full_tokens = probe_ctx.prepare("系统", messages, {}, []).estimated_tokens
    # 使 full_tokens 约占 request_token_limit 的 94%（> 90%，但 <= 100%）
    tight_limit = max(600, int(full_tokens / 0.94))
    assert int(tight_limit * 0.9) < full_tokens <= tight_limit

    summary = {key: [] for key in SUMMARY_SECTIONS}
    summary["goal"] = [{"text": "完成三阶段分析", "sources": [0]}]
    summary["work"] = [{"text": "已完成第 0 批", "sources": [1, 2]}]
    compact_calls = 0

    def fake_summary(*_args: Any) -> ModelReply:
        nonlocal compact_calls
        compact_calls += 1
        return ModelReply({"role": "assistant", "content": json.dumps(summary, ensure_ascii=False)}, "offline", None, "stop")

    active_ctx = ContextManager(
        store,
        ContextConfig(request_token_limit=tight_limit, compact_ratio=0.9, recent_batches=2, recent_users=1),
        AuxiliaryCalls(fake_summary, store.record_model_call, count_tokens),
        set(),
    )
    prepared = active_ctx.prepare("系统", messages, {}, [])
    assert compact_calls == 1
    assert active_ctx.covered > 0
    assert prepared.estimated_tokens < full_tokens


def test_compact_ratio_validation_and_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="compact_ratio"):
        ContextConfig(compact_ratio=0.05)
    with pytest.raises(ValueError, match="compact_ratio"):
        ContextConfig(compact_ratio=1.2)

    monkeypatch.setattr(configuration, "load_dotenv", lambda _: None)
    monkeypatch.delenv("GIS_AGENT_QGIS_DIR", raising=False)
    monkeypatch.setenv("GIS_AGENT_COMPACT_RATIO", "0.85")
    cfg = AppConfig.from_env(tmp_path)
    assert cfg.context.compact_ratio == 0.85
    assert cfg.context.compact_token_limit == int(cfg.context.request_token_limit * 0.85)

def test_runtime_capabilities_injected_in_dynamic_business_tail_preserving_prefix(tmp_path: Path) -> None:
    """runtime_capabilities 仅进入末尾动态 business 状态，不破坏前序消息前缀缓存一致性。"""
    store = SessionStore(tmp_path, "caps_tail")
    counter = make_token_counter(ModelConfig())
    registry = ToolRegistry()
    plan = Plan()
    tools = make_planning_tools(plan)
    for t in tools:
        registry.register(t)

    seen_requests: list[list[dict[str, Any]]] = []
    replies = iter([
        reply("c1", "update_plan", {"goal": "核对能力", "steps": [{"content": "执行", "status": "completed"}]}),
        reply("c2", "finish_task", {"status": "answer", "summary": "已完成"}),
    ])

    def fake_chat(messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> ModelReply:
        seen_requests.append(messages)
        return next(replies)

    agent = Agent(
        registry,
        tools,
        unexpected_model_call,
        plan,
        "系统提示词。",
        fake_chat,
        store,
        make_context(store, ContextConfig(), {t.name for t in tools}, counter),
        runtime_capabilities={"mode": "tier_b", "has_qgis": False, "tier_b_available": ["esda", "pykrige"]},
    )
    out = agent.run([{"role": "user", "origin": "user", "content": "查看当前运行环境。"}])
    assert out["status"] == "answer"
    assert len(seen_requests) == 2
    assert "runtime_capabilities" in seen_requests[0][-1]["content"]
    assert "tier_b_available" in seen_requests[0][-1]["content"]
    # 第2轮的前 N-1 条系统+用户+助手历史严格等于第1轮前缀（去掉旧末尾 business 后的所有稳定前缀消息）。
    assert seen_requests[1][: len(seen_requests[0]) - 1] == seen_requests[0][:-1]


def test_asymmetric_finish_gate_acknowledge_once_and_honest_abstention(tmp_path: Path) -> None:
    """非对称门控：L2 异常提示一次后经 acknowledged_anomalies 放行；fatal 硬拦截；只读查证后允许零写入 blocked。"""
    import importlib.util

    if importlib.util.find_spec("geopandas") is None:
        pytest.skip("当前解释器未安装 geopandas。")

    empty_gpkg = tmp_path / "filtered_empty.gpkg"
    corrupt_tif = tmp_path / "corrupt.tif"
    corrupt_tif.write_bytes(b"corrupt_raster_bytes")

    # 构造带 ZERO_FEATURES 告警的工具，验证首次 completed 被温和拦截，传入 acknowledged_anomalies 后一次放行。
    def make_empty_vec() -> dict[str, Any]:
        import geopandas as gpd

        gpd.GeoDataFrame({"id": pd.Series(dtype="int64")}, geometry=gpd.GeoSeries([], crs="EPSG:32650")).to_file(empty_gpkg)
        return {
            "ok": True,
            "outputs": [
                {
                    "path": str(empty_gpkg),
                    "exists": True,
                    "empty": False,
                    "spatial": {"kind": "vector", "crs": "EPSG:32650", "feature_count": 0, "invalid_sample_count": 0, "empty_sample_count": 0},
                    "anomalies": [{"level": "warning", "code": "ZERO_FEATURES", "message": "要素数为0"}],
                }
            ],
        }

    import pandas as pd

    plan = Plan()
    tools1 = [*make_planning_tools(plan), Tool("make_vec", "生成要素", {"type": "object"}, make_empty_vec)]
    reg1 = ToolRegistry()
    for t in tools1:
        reg1.register(t)
    store1 = SessionStore(tmp_path / "s1", "ack_gate")
    counter = make_token_counter(ModelConfig())
    replies1 = iter([
        reply("t1", "make_vec", {}),
        reply("f1", "finish_task", {"status": "completed", "summary": "已完成筛选", "artifacts": [str(empty_gpkg)]}),
        reply(
            "f2",
            "finish_task",
            {
                "status": "completed",
                "summary": "经核实该空间过滤条件确无命中要素，属正常空结果。",
                "artifacts": [str(empty_gpkg)],
                "acknowledged_anomalies": ["ZERO_FEATURES"],
                "evidence": ["filter_matched=0"],
            },
        ),
    ])
    agent1 = Agent(reg1, tools1, unexpected_model_call, plan, "测试", lambda *_: next(replies1), store1, make_context(store1, ContextConfig(), {t.name for t in tools1}, counter))
    out1 = agent1.run([{"role": "user", "origin": "user", "content": "筛选满足条件的点。"}])
    assert out1["status"] == "completed"
    saved1 = store1.load()
    finishes = [json.loads(m["content"]) for m in saved1 if m.get("tool_name") == "finish_task"]
    assert not finishes[0]["ok"] and finishes[0]["anomalies"][0]["code"] == "ZERO_FEATURES"
    assert finishes[1]["ok"] and finishes[1]["acknowledged_anomalies"] == ["ZERO_FEATURES"]

    # fatal 异常即使传 acknowledged_anomalies=["ALL"] 也禁止 completed，逼迫转 partial/blocked。
    def make_corrupt() -> dict[str, Any]:
        return {
            "ok": True,
            "outputs": [
                {
                    "path": str(corrupt_tif),
                    "exists": True,
                    "empty": False,
                    "spatial": {"kind": "corrupt", "error": "bad header"},
                    "anomalies": [{"level": "fatal", "code": "CORRUPT_OR_UNREADABLE", "message": "头损坏"}],
                }
            ],
        }

    plan2 = Plan()
    tools2 = [*make_planning_tools(plan2), Tool("make_bad", "生成坏文件", {"type": "object"}, make_corrupt)]
    reg2 = ToolRegistry()
    for t in tools2:
        reg2.register(t)
    store2 = SessionStore(tmp_path / "s2", "fatal_gate")
    replies2 = iter([
        reply("t1", "make_bad", {}),
        reply("f1", "finish_task", {"status": "completed", "summary": "强行交付", "artifacts": [str(corrupt_tif)], "acknowledged_anomalies": ["ALL"]}),
        reply("f2", "finish_task", {"status": "blocked", "summary": "输出文件损坏无法读取，已停止交付。", "reason": "data_quality"}),
    ])
    agent2 = Agent(reg2, tools2, unexpected_model_call, plan2, "测试", lambda *_: next(replies2), store2, make_context(store2, ContextConfig(), {t.name for t in tools2}, counter))
    out2 = agent2.run([{"role": "user", "origin": "user", "content": "生成栅格。"}])
    assert out2["status"] == "blocked"

    # 零阻力诚实拒答：首轮只做只读探查、未建计划也未写脚本，直接 blocked 成功放行。
    plan3 = Plan()
    inspect_stub = Tool("inspect_data", "读取元数据", {"type": "object"}, lambda source="": {"ok": True, "data": {"layers": ["country_only"]}})
    tools3 = [*make_planning_tools(plan3), inspect_stub]
    reg3 = ToolRegistry()
    for t in tools3:
        reg3.register(t)
    store3 = SessionStore(tmp_path / "s3", "fast_abstain")
    replies3 = iter([
        reply("i1", "inspect_data", {"source": "x.gpkg"}),
        reply("b1", "finish_task", {"status": "blocked", "reason": "missing_input", "summary": "缺少地级市边界层与两期建成区数据，无法计算蔓延率。", "evidence": ["only_layer=country_only"]}),
    ])
    agent3 = Agent(reg3, tools3, unexpected_model_call, plan3, "测试", lambda *_: next(replies3), store3, make_context(store3, ContextConfig(), {t.name for t in tools3}, counter))
    out3 = agent3.run([{"role": "user", "origin": "user", "content": "计算各城市蔓延率。"}])
    assert out3["status"] == "blocked" and out3["reason"] == "missing_input"


def test_stagnation_alert_warn_and_escalate_in_business_tail(tmp_path: Path) -> None:
    """连续同类失败在动态 business 中注入 warn/escalate，恢复成功后自动清零且前缀保持稳定。"""
    store = SessionStore(tmp_path, "stagnation")
    counter = make_token_counter(ModelConfig())
    plan = Plan()
    fail_count = 0

    def flaky_run(script_path: str = "calc.py") -> dict[str, Any]:
        nonlocal fail_count
        fail_count += 1
        if fail_count <= 5:
            return {"ok": False, "status": "failed", "stderr": "Traceback...\nCRSError: unknown EPSG"}
        return {"ok": True, "status": "succeeded", "outputs": []}

    tools = [*make_planning_tools(plan), Tool("run_python_script", "运行脚本", {"type": "object", "properties": {"script_path": {"type": "string"}}}, flaky_run)]
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)

    seen_business: list[str] = []
    replies = iter([
        reply("r1", "run_python_script", {"script_path": "calc.py"}),
        reply("r2", "run_python_script", {"script_path": "calc.py"}),
        reply("r3", "run_python_script", {"script_path": "calc.py"}),
        reply("r4", "run_python_script", {"script_path": "calc.py"}),
        reply("r5", "run_python_script", {"script_path": "calc.py"}),
        reply("r6", "run_python_script", {"script_path": "calc.py"}),
        reply("ok", "finish_task", {"status": "completed", "summary": "修复坐标系后执行成功"}),
    ])

    def capture_chat(messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> ModelReply:
        seen_business.append(messages[-1]["content"])
        return next(replies)

    agent = Agent(reg, tools, unexpected_model_call, plan, "测试", capture_chat, store, make_context(store, ContextConfig(), {t.name for t in tools}, counter))
    out = agent.run([{"role": "user", "origin": "user", "content": "运行计算。"}])
    assert out["status"] == "completed"
    # 前2轮正常及首败无告警；第2次失败后（第3次请求）出现 warn；第5次失败后（第6次请求）出现 escalate；第6次成功后（第7次请求）告警清除
    assert "stagnation_alert" not in seen_business[0]
    assert "stagnation_alert" not in seen_business[1]
    assert '"level":"warn"' in seen_business[2]
    assert '"level":"escalate"' in seen_business[5]
    assert "stagnation_alert" not in seen_business[6]


def test_timeout_signature_merges_across_script_names(tmp_path: Path) -> None:
    """不同脚本名连续超时应归并为统一 TIMEOUT 签名并触发采样/分块与 verification 指引。"""
    store = SessionStore(tmp_path, "timeout_merge")
    counter = make_token_counter(ModelConfig())
    plan = Plan()
    calls_made = 0

    def run_stub(script_path: str = "calc.py") -> dict[str, Any]:
        nonlocal calls_made
        calls_made += 1
        if calls_made <= 2:
            return {"ok": False, "status": "timed_out", "timed_out": True, "error": "超过 120 秒"}
        return {"ok": True, "status": "succeeded", "outputs": []}

    tools = [*make_planning_tools(plan), Tool("run_python_script", "运行脚本", {"type": "object", "properties": {"script_path": {"type": "string"}}}, run_stub)]
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)

    seen_business: list[str] = []
    replies = iter([
        reply("r1", "run_python_script", {"script_path": str(tmp_path / "02_a.py")}),
        reply("r2", "run_python_script", {"script_path": str(tmp_path / "02_b.py")}),
        reply("r3", "run_python_script", {"script_path": str(tmp_path / "03_tiled.py")}),
        reply("ok", "finish_task", {"status": "completed", "summary": "已改用分块执行完成。"}),
    ])

    def capture_chat(messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> ModelReply:
        seen_business.append(messages[-1]["content"])
        return next(replies)

    agent = Agent(reg, tools, unexpected_model_call, plan, "测试", capture_chat, store, make_context(store, ContextConfig(), {t.name for t in tools}, counter))
    out = agent.run([{"role": "user", "origin": "user", "content": "缓冲合并。"}])
    assert out["status"] == "completed"
    assert "stagnation_alert" not in seen_business[1]
    assert '"repeated_signature":"run_python_script:TIMEOUT"' in seen_business[2]
    assert "gis-verification/SKILL.md" in seen_business[2]
    assert "stagnation_alert" not in seen_business[3]


def test_spinning_alert_on_repeated_polishing_and_image_review(tmp_path: Path) -> None:
    """连续同脚本微调或高频重复看图应在动态 business 中注入 efficiency_hint，且不影响常规阶段推进与 KV 前缀。"""
    counter = make_token_counter(ModelConfig())
    script_calc = str(tmp_path / "calc.py")
    script_plot = str(tmp_path / "plot.py")
    out_gpkg = str(tmp_path / "res.gpkg")
    out_png = str(tmp_path / "map.png")

    # 1) 正常多阶段（含产出核心 .gpkg）+ 4 次同脚本纯绘图微调后才触发 repeated_script_polishing
    store1 = SessionStore(tmp_path / "s1", "spin_script")
    plan1 = Plan()
    tools1 = [
        *make_planning_tools(plan1),
        Tool("write_file", "写文件", {"type": "object", "properties": {"path": {"type": "string"}}}, lambda path="": {"ok": True}),
        Tool("edit_file", "改文件", {"type": "object", "properties": {"path": {"type": "string"}}}, lambda path="": {"ok": True}),
        Tool(
            "run_python_script",
            "跑脚本",
            {"type": "object", "properties": {"script_path": {"type": "string"}}},
            lambda script_path="": {"ok": True, "outputs": [{"path": out_gpkg if script_path == script_calc else out_png}]},
        ),
        Tool("read_image", "看图", {"type": "object", "properties": {"path": {"type": "string"}}}, lambda path="": {"ok": True, "path": path}),
    ]
    reg1 = ToolRegistry()
    for t in tools1:
        reg1.register(t)

    seen_requests: list[list[dict[str, Any]]] = []
    replies1 = iter([
        reply("w1", "write_file", {"path": script_calc}),
        reply("rc", "run_python_script", {"script_path": script_calc}),
        reply("e1", "edit_file", {"path": script_plot}),
        reply("rp1", "run_python_script", {"script_path": script_plot}),
        reply("e2", "edit_file", {"path": script_plot}),
        reply("rp2", "run_python_script", {"script_path": script_plot}),
        reply("e3", "edit_file", {"path": script_plot}),
        reply("rp3", "run_python_script", {"script_path": script_plot}),
        reply("e4", "edit_file", {"path": script_plot}),
        reply("rp4", "run_python_script", {"script_path": script_plot}),
        reply("fin", "finish_task", {"status": "completed", "summary": "成图交付"}),
    ])

    def cap1(messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> ModelReply:
        seen_requests.append(messages)
        return next(replies1)

    agent1 = Agent(reg1, tools1, unexpected_model_call, plan1, "系统提示词", cap1, store1, make_context(store1, ContextConfig(), {t.name for t in tools1}, counter))
    assert agent1.run([{"role": "user", "origin": "user", "content": "出图"}])["status"] == "completed"
    # 前 9 次模型请求中均不应误报，第 10 次完成后（第 11 次请求即 seen_requests[-1]）注入 efficiency_hint 且前序前缀不变
    assert all("efficiency_hint" not in req[-1]["content"] for req in seen_requests[:-1])
    last_tail = seen_requests[-1][-1]["content"]
    assert '"pattern":"repeated_script_polishing"' in last_tail and '"consecutive_runs":4' in last_tail
    assert seen_requests[-1][: len(seen_requests[-2]) - 1] == seen_requests[-2][:-1]

    # 2) 高频 read_image >= 5 次且最近重复看图触发 repeated_image_review
    from PIL import Image
    from gis_agent.tools.images import make_image_tool

    real_png = tmp_path / "map.png"
    Image.new("RGB", (8, 8), "red").save(real_png)
    store2 = SessionStore(tmp_path / "s2", "spin_img")
    plan2 = Plan()
    tools2 = [
        *make_planning_tools(plan2),
        make_image_tool(tmp_path / "img_cache"),
    ]
    reg2 = ToolRegistry()
    for t in tools2:
        reg2.register(t)
    tails2: list[str] = []
    replies2 = iter([
        reply("i1", "read_image", {"path": str(real_png)}),
        reply("i2", "read_image", {"path": str(real_png)}),
        reply("i3", "read_image", {"path": str(real_png)}),
        reply("i4", "read_image", {"path": str(real_png)}),
        reply("i5", "read_image", {"path": str(real_png)}),
        reply("fin", "finish_task", {"status": "completed", "summary": "看图结束"}),
    ])
    agent2 = Agent(
        reg2, tools2, unexpected_model_call, plan2, "系统提示词",
        lambda msgs, _s: (tails2.append(msgs[-1]["content"]), next(replies2))[1],
        store2, make_context(store2, ContextConfig(), {t.name for t in tools2}, counter),
    )
    assert agent2.run([{"role": "user", "origin": "user", "content": "审图"}])["status"] == "completed"
    assert all("efficiency_hint" not in t for t in tails2[:-1])
    assert '"pattern":"repeated_image_review"' in tails2[-1] and '"read_image_count":5' in tails2[-1]


def test_verification_hint_attached_only_on_anomalies_or_finish_rejection(tmp_path: Path) -> None:
    """常规成功无 verification_hint；空间异常或 finish_task 拦截时附带 gis-verification 指引。"""
    store = SessionStore(tmp_path, "verif_hint")
    counter = make_token_counter(ModelConfig())
    plan = Plan()
    clean_file = tmp_path / "clean.txt"
    clean_file.write_text("ok", encoding="utf-8")

    tools = [
        *make_planning_tools(plan),
        Tool("normal_tool", "普通工具", {"type": "object"}, lambda: {"ok": True, "outputs": [{"path": str(clean_file)}]}),
        Tool(
            "anom_tool",
            "带异常告警",
            {"type": "object"},
            lambda: {"ok": True, "outputs": [{"path": str(clean_file), "anomalies": [{"level": "notice", "code": "UNSCALED_HIGH_DN"}]}]},
        ),
    ]
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)

    replies = iter([
        reply("p1", "update_plan", {"goal": "测试提示", "steps": [{"content": "待完成步骤", "status": "pending"}]}),
        reply("n1", "normal_tool", {}),
        reply("a1", "anom_tool", {}),
        reply("f1", "finish_task", {"status": "completed", "summary": "提前交付", "artifacts": [str(clean_file)]}),
        reply("p2", "update_plan", {"goal": "测试提示", "steps": [{"content": "待完成步骤", "status": "completed"}]}),
        reply("f2", "finish_task", {"status": "completed", "summary": "确认完成", "artifacts": [str(clean_file)]}),
    ])
    agent = Agent(reg, tools, unexpected_model_call, plan, "测试", lambda *_: next(replies), store, make_context(store, ContextConfig(), {t.name for t in tools}, counter))
    assert agent.run([{"role": "user", "origin": "user", "content": "运行核查"}])["status"] == "completed"

    by_tool = {
        m.get("tool_name"): json.loads(m["content"])
        for m in store.load()
        if m.get("role") == "tool"
    }
    assert "verification_hint" not in by_tool["normal_tool"]
    assert "gis-verification/SKILL.md" in by_tool["anom_tool"]["verification_hint"]
    finish_msgs = [json.loads(m["content"]) for m in store.load() if m.get("tool_name") == "finish_task"]
    assert not finish_msgs[0]["ok"] and "gis-verification/SKILL.md" in finish_msgs[0]["verification_hint"]
    assert finish_msgs[1]["ok"] and "verification_hint" not in finish_msgs[1]
