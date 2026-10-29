"""完整运行会调用真实 API 和 QGIS；只跑本地检查时加 -k "not live"。"""

import json
import math
import os
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from dotenv import dotenv_values
from langgraph.checkpoint.sqlite import SqliteSaver
from openai import DefaultHttpxClient, OpenAI

from gis_agent import application
from gis_agent.config import AppConfig
from gis_agent.agent import Agent
from gis_agent.prompts import render_prompt
from gis_agent.tools.session import make_session_tool
from gis_agent.core.context import SUMMARY_SECTIONS, ContextConfig, ContextManager
from gis_agent.core.auxiliary import AuxiliaryCalls
from gis_agent.core.model import ModelConfig, ModelReply, TokenCounter
from gis_agent.integrations.llm import chat, make_token_counter
from gis_agent.core.memory import MemoryConfig, MemoryStore, MemoryTurn, extract_memories
from gis_agent.core.planning import Plan
from gis_agent.integrations.qgis.adapter import load_qgis_tool, tool_name
from gis_agent.integrations.qgis.catalog import load_catalog, make_search_tool
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.persistence.sessions import SessionStore, message_units
from gis_agent.tools.base import Tool
from gis_agent.tools.files import file_tools, read_file, write_file
from gis_agent.tools.memory import make_memory_tools
from gis_agent.tools.planning import make_planning_tools
from gis_agent.tools.qgis_python import inspect_data, make_qgis_python_tools, run_python_script
from gis_agent.tools.registry import ToolRegistry
from gis_agent.tools.verification import available_evidence, make_verifier_finish


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def count_tokens():
    return make_token_counter(ModelConfig())


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


@pytest.fixture
def points(tmp_path: Path) -> Path:
    path = tmp_path / "points.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
        "features": [
            {"type": "Feature", "properties": {"id": index}, "geometry": {"type": "Point", "coordinates": [x, 0]}}
            for index, x in enumerate((0, 1000), start=1)
        ],
    }), encoding="utf-8")
    return path


def unexpected_model_call(*args: Any) -> ModelReply:
    pytest.fail("这个确定性检查不应调用模型。")


def make_context(store: SessionStore, config: ContextConfig, pinned: set[str], count_tokens, call=unexpected_model_call) -> ContextManager:
    return ContextManager(
        store, config,
        AuxiliaryCalls(call, store.record_model_call, count_tokens, config.request_token_limit),
        pinned,
    )


def reply(call_id: str, name: str, arguments: dict[str, Any]) -> ModelReply:
    return ModelReply({"role": "assistant", "content": None, "tool_calls": [{
        "id": call_id, "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }]}, "fixed", None, "tool_calls")


def test_v4_files_data_and_script(tmp_path: Path, qgis_dir: Path, points: Path) -> None:
    script = tmp_path / "check_input.py"
    assert write_file(str(script), 'print("脚本执行成功")')["ok"]
    assert not write_file(str(script), "覆盖")["ok"]
    first = read_file(str(script), limit=5)
    rest = read_file(str(script), start=first["next_start"])
    assert first["content"] + rest["content"] == script.read_text(encoding="utf-8")
    launcher = qgis_dir / "bin" / "python-qgis-ltr.bat"
    result = run_python_script(launcher, tmp_path / "logs", str(script))
    assert result["ok"], result
    assert "脚本执行成功" in Path(result["stdout_path"]).read_text(encoding="utf-8")
    data = inspect_data(launcher, tmp_path / "logs", str(points))
    assert data["ok"], data
    assert data["data"]["feature_count"] == 2
    assert data["data"]["crs"] == "EPSG:3857"
    assert data["data"]["geometry_type"] == "Point"


def test_qgis_creates_output_parent(tmp_path: Path, qgis_dir: Path, points: Path) -> None:
    from gis_agent.integrations.qgis.adapter import execute_algorithm

    client = QGISClient(qgis_dir / "bin" / "qgis_process-qgis-ltr.bat")
    definitions = client.query("help", "native:buffer")["parameters"]
    output = tmp_path / "new" / "candidate" / "result.gpkg"
    arguments = {"INPUT": str(points), "DISTANCE": 500, "SEGMENTS": 16, "OUTPUT": str(output)}
    assert not output.parent.exists()
    result = execute_algorithm(client, "native:buffer", definitions, **arguments)
    assert result["ok"] and output.is_file(), result
    original = output.read_bytes()
    refused = execute_algorithm(client, "native:buffer", definitions, **arguments)
    assert not refused["ok"] and output.read_bytes() == original
    script = tmp_path / "measure.py"
    script.write_text(
        "import sys\nfrom qgis.core import QgsApplication, QgsVectorLayer, QgsProject\n"
        "def main():\n"
        "    layer = QgsVectorLayer(sys.argv[1], 'result', 'ogr')\n"
        "    assert layer.isValid() and layer.featureCount() == 2\n"
        "    assert layer.crs().authid() == 'EPSG:3857'\n"
        "    assert all(f.geometry().isGeosValid() for f in layer.getFeatures())\n"
        "    print('检查通过')\n"
        "app = QgsApplication([], False)\napp.initQgis()\nmain()\n"
        "QgsProject.instance().clear()\napp.exitQgis()\n",
        encoding="utf-8",
    )
    measured = run_python_script(qgis_dir / "bin" / "python-qgis-ltr.bat", tmp_path / "logs", str(script), [str(output)])
    assert measured["ok"] and measured["returncode"] == 0, measured


def test_verifier_receives_evidence_catalog_without_plan(tmp_path: Path, count_tokens) -> None:
    store = SessionStore(tmp_path, "verifier")
    messages = [{"role": "user", "origin": "delegation", "content": "核验实际读取。"}]
    data = tmp_path / "measurement.txt"
    data.write_text("实际测量通过。", encoding="utf-8")
    definitions = [{
        "check_id": "measure", "requirement": "核验实际读取", "source_indices": [0],
        "criterion": "实际测量满足要求", "method": "读取测量结果", "coverage": "本次结果",
    }]
    finish = make_verifier_finish(messages, {0}, tmp_path / "output", store=store, initial_checks=definitions)
    tools = [next(tool for tool in file_tools if tool.name == "read_file"), finish]
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    requests = []

    def fixed(view, schemas):
        requests.append(view)
        if len(requests) == 1:
            return reply("measurement", "read_file", {"path": str(data)})
        business = json.loads(view[1]["content"].split("：", 1)[1])
        evidence = business["available_evidence"][0]
        assert evidence["tool_name"] == "read_file" and evidence["label"] == data.name
        return reply("complete", "finish_task", {
            "status": "completed", "summary": "重点通过。",
            "checks": [{"check_id": "measure", "status": "PASS", "finding": "实际测量通过。", "evidence_ids": [evidence["evidence_id"]]}],
        })

    agent = Agent(
        registry, tools, unexpected_model_call, Plan(), "按实际证据核验。", fixed,
        store, make_context(store, ContextConfig(), {tool.name for tool in tools}, count_tokens),
        require_review=False, evidence_catalog=partial(available_evidence, messages),
    )
    result = agent.run(messages)
    assert result["ok"] and result["status"] == "completed"
    assert result["checks"][0]["evidence_indices"] == [2]
    assert len(requests) == 2 and not agent.plan.steps


def test_parent_verifier_round_trip(tmp_path: Path, qgis_dir: Path, count_tokens, monkeypatch) -> None:
    config = AppConfig.from_env(ROOT)
    config = replace(
        config, model=replace(config.model, supports_images=False), memory=None,
        api_key_env="GIS_AGENT_OFFLINE_TEST_KEY", session_root=tmp_path / "sessions", output_root=tmp_path / "outputs",
    )
    monkeypatch.setenv(config.api_key_env, "offline-test")
    candidate = config.output_root / "parent" / "candidates" / "first" / "result.txt"
    definitions = [{
        "check_id": "content", "requirement": "保存实际文本", "source_indices": [0],
        "criterion": "文本内容为结果", "method": "读取实际文件", "coverage": "完整文件",
    }]
    counts = {"parent": 0, "verifier": 0}

    def fixed(client, model, view, schemas):
        finish_schema = next(item["function"]["parameters"] for item in schemas if item["function"]["name"] == "finish_task")
        role = "verifier" if "checks" in finish_schema["properties"] else "parent"
        counts[role] += 1
        if role == "verifier":
            if counts[role] == 1:
                return reply("define", "define_checks", {"checks": definitions})
            if counts[role] == 2:
                return reply("read-result", "read_file", {"path": str(candidate)})
            business = json.loads(view[1]["content"].split("：", 1)[1])
            evidence_id = next(item["evidence_id"] for item in business["available_evidence"] if item["ok"])
            return reply("verified", "finish_task", {
                "status": "completed", "summary": "内容符合要求。",
                "checks": [{"check_id": "content", "status": "PASS", "finding": "读取内容为结果。", "evidence_ids": [evidence_id]}],
            })
        if counts[role] == 1:
            return reply("write-result", "write_file", {"path": str(candidate), "content": "结果"})
        if counts[role] == 2:
            return reply("review", "review_delivery", {
                "candidate_id": "first", "goal": "写入结果文本，核验实际内容。", "source_indices": [0],
                "inputs": [], "deliverables": [str(candidate)],
            })
        reviewed = next(json.loads(item["content"]) for item in view if item.get("tool_call_id") == "review")
        assert reviewed["ready"] and "definitions" not in reviewed
        return reply("finish", "finish_task", {"status": "completed", "summary": "文件已保存并通过重点复核。"})

    monkeypatch.setattr(application, "chat", fixed)
    monkeypatch.setattr(application, "make_token_counter", lambda _: count_tokens)
    with application.open_conversation(config, "parent") as conversation:
        result = conversation.send("保存内容为结果的文本文件，并核验实际内容。")
        assert result["ok"] and result["delivery"]["checks"][0]["evidence_indices"] == [4]
        assert not conversation.agent.plan.steps
    with application.open_conversation(config, "parent") as conversation:
        assert not conversation.pending
        cached = conversation.agent.registry.execute("read_delivery", {"candidate_id": "first"})
        assert cached["ready"]
        candidate.write_text("发生变化", encoding="utf-8")
        assert not conversation.agent.completion_check(0)["ok"]
    assert counts == {"parent": 3, "verifier": 3}


def test_v5_plan_review_and_session_restore(tmp_path: Path, count_tokens) -> None:
    store = SessionStore(tmp_path, "planning")
    plan = Plan()
    registry = ToolRegistry()
    tools = make_planning_tools(plan)
    for tool in tools:
        registry.register(tool)
    replies = iter([
        reply("plan", "update_plan", {"goal": "检查交付", "steps": [{"content": "复核结果", "status": "pending"}]}),
        reply("review", "finish_task", {"status": "completed", "summary": "申请复核"}),
        reply("checked", "update_plan", {"goal": "检查交付", "steps": [{"content": "复核结果", "status": "completed"}]}),
        reply("finish", "finish_task", {"status": "completed", "summary": "复核完成"}),
    ])
    agent = Agent(
        registry, tools, unexpected_model_call, plan, "按要求复核。", lambda *_: next(replies),
        store, make_context(store, ContextConfig(), {tool.name for tool in tools}, count_tokens),
    )
    messages = [{"role": "user", "origin": "user", "content": "检查交付。"}]
    assert agent.run(messages)["status"] == "completed"
    saved = store.load()
    results = [json.loads(item["content"]) for item in saved if item.get("tool_name") == "finish_task"]
    assert [item["status"] for item in results] == ["review_required", "completed"]
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


def make_graph_agent(
    store: SessionStore, call: Callable[..., ModelReply], count_tokens: TokenCounter,
    saver: SqliteSaver, extra_tools: tuple[Tool, ...] = (),
) -> Agent:
    plan = Plan.from_messages(store.read_record())
    tools = [*make_planning_tools(plan), *extra_tools]
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return Agent(
        registry, tools, unexpected_model_call, plan, "按要求执行并复核。", call, store,
        make_context(store, ContextConfig(), {tool.name for tool in tools}, count_tokens, call),
        checkpointer=saver,
    )


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
        reply("review", "finish_task", {"status": "completed", "summary": "请求复核"}),
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


def test_v71_sqlite_resume_preserves_review_and_tool_results(tmp_path: Path, count_tokens) -> None:
    output = tmp_path / "result.txt"

    def save_result() -> dict[str, Any]:
        with output.open("a", encoding="utf-8") as file:
            file.write("成果\n")
        return {"ok": True}

    tool = Tool("save_result", "保存成果", {"type": "object"}, save_result)
    replies = iter([
        reply("save", tool.name, {}),
        reply("review", "finish_task", {"status": "completed", "summary": "请求复核"}),
    ])

    def disconnected_chat(*args: Any) -> ModelReply:
        response = next(replies, None)
        if response is None:
            raise ConnectionError("模拟复核期间连接中断。")
        return response

    store = SessionStore(tmp_path / "sessions", "resume")
    checkpoint = str(tmp_path / "checkpoints.sqlite")
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        agent = make_graph_agent(store, disconnected_chat, count_tokens, saver, (tool,))
        with pytest.raises(ConnectionError):
            agent.run([{"role": "user", "origin": "user", "content": "保存成果并复核。"}])
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        agent = make_graph_agent(
            store, lambda *_: reply("finish", "finish_task", {"status": "completed", "summary": "复核完成"}),
            count_tokens, saver, (tool,),
        )
        assert agent.resume(store.read_record())["status"] == "completed"
        assert agent.graph.get_state(agent.options()).values["responses_used"] == 3
    assert output.read_text(encoding="utf-8") == "成果\n"
    results = [json.loads(item["content"]) for item in store.load() if item.get("tool_name") == "finish_task"]
    assert [item["status"] for item in results] == ["review_required", "completed"]


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
            render_prompt("system.j2", output_dir=tmp_path / "outputs"), real_chat,
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
    assert any(item.get("status") == "review_required" for item in finish_results)
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
