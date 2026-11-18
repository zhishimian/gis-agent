"""CLI、App/Conversation API、Harness MCP 与独立打包配置适配测试。"""
from __future__ import annotations

from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any

import httpx
from openai import OpenAI
import pytest
from typer.testing import CliRunner

from gis_agent import config as configuration
from gis_agent.adapters.harness_mcp import MCPServer, build_harness_tools
from gis_agent.adapters.stubs import WorkspaceContext
from gis_agent.application import AgentFactory, Conversation, open_conversation
from gis_agent.config import AppConfig
from gis_agent.core.events import AgentEvent
from gis_agent.core.model import ModelConfig, ModelReply
from gis_agent.integrations.llm import make_token_counter
from gis_agent.persistence.checkpoints import MemoryCheckpointer as InMemorySaver
from gis_agent.persistence.checkpoints import SqliteCheckpointer
from gis_agent.persistence.sessions import SessionStore, message_units
from gis_agent.runtime import paths as runtime_paths
from gis_agent.tools.base import Tool
from gis_agent.tools.qgis_python import run_python_script
from conftest import ask, make_graph_agent, reply


def _tool_reply(call_id: str, name: str, arguments: dict[str, Any]) -> ModelReply:
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
        "offline",
        {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        "tool_calls",
    )


def test_package_paths_and_frozen_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert runtime_paths.package_dir().name == "gis_agent"
    assert (runtime_paths.import_root() / "gis_agent").is_dir()
    assert runtime_paths.package_resource("runtime", "inspect_fast.py").is_file()

    fake_meipass = tmp_path / "_internal"
    (fake_meipass / "gis_agent").mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    assert runtime_paths.package_dir() == (fake_meipass / "gis_agent").resolve()
    assert runtime_paths.import_root() == fake_meipass.resolve()

    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(runtime_paths, "import_root", lambda: tmp_path / "venv/Lib/site-packages")
    assert runtime_paths.default_project_dir() == Path.cwd().resolve()


@pytest.mark.slow
def test_background_request_stop_kills_subprocess_and_keeps_session_valid(tmp_path: Path) -> None:
    slow_script = tmp_path / "slow_job.py"
    pid_file = tmp_path / "grandchild.pid"
    slow_script.write_text(
        f"""import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
Path({str(pid_file)!r}).write_text(str(child.pid), encoding="utf-8")
time.sleep(60)
""",
        encoding="utf-8",
    )

    config = AppConfig(
        project=tmp_path,
        session_root=tmp_path / "sessions",
        output_root=tmp_path / "outputs",
        qgis=None,
        model=ModelConfig(supports_images=False, image_tokens=0),
        context=AppConfig.from_env(tmp_path).context,
        memory=None,
        api_key_env="DEEPSEEK_API_KEY",
        python_executable=Path(sys.executable),
    )
    store = SessionStore(config.session_root, "stop-demo")
    config.session_root.mkdir(parents=True, exist_ok=True)
    output_dir = config.output_root / "stop-demo"
    output_dir.mkdir(parents=True, exist_ok=True)
    messages: list[dict[str, Any]] = []
    events: list[AgentEvent] = []
    cancel_event = threading.Event()

    turn_counter = 0

    def fake_chat(_msgs: list[dict[str, Any]], _schemas: list[dict[str, Any]]) -> ModelReply:
        nonlocal turn_counter
        turn_counter += 1
        if turn_counter == 1:
            return _tool_reply("call_slow", "run_python_script", {"script_path": str(slow_script), "timeout_sec": 60})
        return _tool_reply("call_done", "finish_task", {"status": "answer", "summary": "恢复后正常回答。"})

    with SqliteCheckpointer.from_conn_string(str(config.session_root / "checkpoints.sqlite")) as saver:
        factory = AgentFactory(config, fake_chat, make_token_counter(config.model))
        agent = factory.create(
            store,
            messages,
            output_dir,
            saver,
            "执行测试任务。",
            on_event=events.append,
            cancel_event=cancel_event,
        )
        conversation = Conversation(agent, messages, output_dir, cancel_event=cancel_event)

        holder: dict[str, Any] = {}

        def worker() -> None:
            holder["result"] = conversation.send("启动慢计算。")

        t0 = time.perf_counter()
        thread = threading.Thread(target=worker)
        thread.start()
        deadline = time.perf_counter() + 5.0
        while not pid_file.exists() and time.perf_counter() < deadline:
            time.sleep(0.05)
        assert pid_file.exists(), "子进程尚未启动"
        conversation.request_stop()
        thread.join(timeout=8.0)
        elapsed = time.perf_counter() - t0

        assert not thread.is_alive()
        assert elapsed < 6.0
        assert holder["result"]["status"] == "cancelled"
        assert not conversation.pending

        # 验证 Session 消息闭合完整性，且同一会话后续可继续正常对话
        loaded = store.load()
        message_units(loaded)
        assert any(ev.type == "turn_finished" and ev.payload.get("status") == "cancelled" for ev in events)

        followup = conversation.send("取消后继续普通问答。")
        assert followup["status"] == "answer"
        assert followup["summary"] == "恢复后正常回答。"


def test_open_conversation_explicit_params_events_and_workspace_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("gis_agent.config.load_dotenv", lambda _: None)
    monkeypatch.delenv("GIS_AGENT_QGIS_DIR", raising=False)
    config = AppConfig.from_env(tmp_path)

    with pytest.raises(ValueError, match="api_key"):
        with open_conversation(config, "missing-key"):
            pass

    captured_requests: list[dict[str, Any]] = []
    call_idx = 0
    out_file = tmp_path / "outputs" / "ui-session" / "layer_out.geojson"

    def mock_transport(request: httpx.Request) -> httpx.Response:
        nonlocal call_idx
        call_idx += 1
        captured_requests.append(json.loads(request.content))
        if call_idx == 1:
            msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "emit_demo_layer", "arguments": "{}"},
                    }
                ],
            }
            reason = "tool_calls"
        else:
            msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {
                            "name": "finish_task",
                            "arguments": json.dumps(
                                {"status": "completed", "summary": "图层已生成。", "artifacts": [str(out_file)]},
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
            reason = "tool_calls"
        return httpx.Response(
            200,
            json={
                "id": f"r{call_idx}",
                "object": "chat.completion",
                "created": 0,
                "model": "offline",
                "choices": [{"index": 0, "finish_reason": reason, "message": msg}],
                "usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
            },
        )

    def produce_layer() -> dict[str, Any]:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
        return {"ok": True, "outputs": [{"path": str(out_file), "exists": True, "bytes": out_file.stat().st_size}]}

    demo_tool = Tool(
        name="emit_demo_layer",
        description="生成演示矢量文件。",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=produce_layer,
    )
    monkeypatch.setattr(
        "gis_agent.application.DefaultHttpxClient",
        lambda **_: httpx.Client(transport=httpx.MockTransport(mock_transport)),
    )

    events: list[AgentEvent] = []
    ws_ctx = WorkspaceContext(
        selected_layers=("parcels.gpkg",),
        drawn_bbox_wgs84=(116.3, 39.9, 116.5, 40.1),
        active_crs="EPSG:32650",
    )
    with open_conversation(
        config,
        "ui-session",
        api_key="ui-explicit-secret",
        on_event=events.append,
        extra_tools=[demo_tool],
        workspace_context=ws_ctx,
    ) as conv:
        outcome = conv.send("基于当前画布图层生成结果。")

    assert outcome["status"] == "completed"
    # 验证画布上下文注入到了末尾动态状态消息
    first_req_text = json.dumps(captured_requests[0]["messages"], ensure_ascii=False)
    assert "parcels.gpkg" in first_req_text and "EPSG:32650" in first_req_text
    # 验证 tool_finished 事件直接带出 outputs 供前端自动上屏
    tool_events = [e for e in events if e.type == "tool_finished" and e.payload.get("tool") == "emit_demo_layer"]
    assert len(tool_events) == 1
    assert tool_events[0].payload["outputs"][0]["path"] == str(out_file.resolve() if out_file.is_absolute() else out_file)


def test_stdio_mcp_server_protocol_and_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. 内存流测试行分隔与 Content-Length 双帧兼容
    monkeypatch.delenv("GIS_AGENT_QGIS_DIR", raising=False)
    monkeypatch.setattr("gis_agent.config.load_dotenv", lambda _: None)
    tools = build_harness_tools(tmp_path)
    assert {"probe_gis_environment", "list_gis_skills", "inspect_data"}.issubset(tools.keys())

    ping_body = json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"}).encode("utf-8")
    framed_input = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}).encode("utf-8")
        + b"\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
        + b"\n"
        + f"Content-Length: {len(ping_body)}\r\n\r\n".encode("ascii")
        + ping_body
    )
    out_buf = io.BytesIO()
    MCPServer(tools).serve_stdio(io.BytesIO(framed_input), out_buf)
    raw_out = out_buf.getvalue().decode("utf-8")
    assert '"gis-agent-mcp"' in raw_out
    assert "Content-Length:" in raw_out

    # 2. 真实独立子进程 STDIO 往返（无任何大模型 API Key）
    env = {k: v for k, v in os.environ.items() if "API_KEY" not in k and k != "GIS_AGENT_QGIS_DIR"}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    proc = subprocess.Popen(
        [sys.executable, "-m", "gis_agent.adapters.harness_mcp", "--project", str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_gis_skills", "arguments": {}}},
        ]
        for req in requests:
            proc.stdin.write((json.dumps(req) + "\n").encode("utf-8"))
        proc.stdin.flush()
        proc.stdin.close()

        lines = [json.loads(line.decode("utf-8")) for line in proc.stdout.read().splitlines() if line.strip()]
        proc.wait(timeout=15)
        assert proc.returncode == 0
        assert [item["id"] for item in lines] == [1, 2, 3]
        tool_names = {t["name"] for t in lines[1]["result"]["tools"]}
        assert {"list_gis_skills", "probe_gis_environment", "inspect_data"}.issubset(tool_names)
        skills_payload = json.loads(lines[2]["result"]["content"][0]["text"])
        assert skills_payload["ok"] and len(skills_payload["skills"]) == 7
    finally:
        if proc.poll() is None:
            proc.kill()


def test_script_timeout_bounds_tightened_to_600s(tmp_path: Path) -> None:
    script = tmp_path / "noop.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    rejected = run_python_script(Path(sys.executable), tmp_path / "logs", str(script), timeout_sec=900)
    assert not rejected["ok"]
    assert "600" in rejected["error"]


def test_standalone_config_without_qgis_dir_and_harness_adapter(tmp_path: Path, monkeypatch, qgis_dir: Path) -> None:
    for key in list(configuration.os.environ):
        if key.startswith("GIS_AGENT_"):
            monkeypatch.delenv(key)
    monkeypatch.setattr(configuration, "load_dotenv", lambda _: None)
    cfg = AppConfig.from_env(tmp_path)
    assert cfg.qgis is None
    assert cfg.python_launcher.is_file()

    store = SessionStore(tmp_path / "sessions", "no_qgis")
    messages = [{"role": "user", "origin": "user", "content": "只用纯 Python 运行"}]
    counter = make_token_counter(cfg.model)
    with SqliteCheckpointer.from_conn_string(":memory:") as saver:
        agent = AgentFactory(
            cfg,
            lambda *_: reply("done", "finish_task", {"status": "answer", "summary": "无需QGIS已启动"}),
            counter,
        ).create(store, messages, tmp_path / "out", saver, "无QGIS测试")
        assert "search_qgis_tools" not in agent.registry.tools
        assert "run_python_script" in agent.registry.tools
        assert agent.run(messages)["status"] == "answer"

    monkeypatch.setenv("GIS_AGENT_QGIS_DIR", str(qgis_dir))
    harness_tools = build_harness_tools(tmp_path)
    assert {"inspect_data", "summarize_fields", "check_spatial_relation", "probe_gis_environment", "search_qgis_tools", "run_qgis_algorithm"} <= set(harness_tools)


def test_cli_history_is_offline_and_chat_syntax_is_compatible(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner
    from gis_agent import cli
    store = SessionStore(tmp_path / "records", "offline")
    call_dict = {"id": "repeated", "type": "function", "function": {"name": "operation", "arguments": json.dumps({"value": 5})}}
    store.save([{"role": "assistant", "content": None, "tool_calls": [call_dict]}, store.tool_message("repeated", "operation", {"ok": True}, 8000)])
    (tmp_path / ".env").write_text("GIS_AGENT_SESSIONS_DIR=records\nGIS_AGENT_QGIS_DIR=missing\n", encoding="utf-8")
    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "GIS_AGENT_SESSIONS_DIR"):
        monkeypatch.delenv(key, raising=False)
    runner = CliRunner()
    calls = []
    monkeypatch.setattr(cli, "chat", lambda project, session: calls.append((project, session)))
    result = runner.invoke(cli.app, ["history", "--project", str(tmp_path), "--session", "offline"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["items"][0]["status"] == "succeeded" and not calls
    for arguments in (["--project", str(tmp_path), "--session", "offline"],
                      ["chat", "--project", str(tmp_path), "--session", "offline"],
                      ["--project", str(tmp_path), "--session", "offline", "chat"]):
        assert runner.invoke(cli.app, arguments).exit_code == 0
    assert calls == [(tmp_path, "offline")] * 3
    assert runner.invoke(cli.app, ["--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["chat", "--help"]).exit_code == 0


def test_cli_question_exit_restart_answer_and_offline_waiting(tmp_path,monkeypatch):
    from gis_agent.cli import app
    import gis_agent.application as application
    store=SessionStore(tmp_path/'sessions','cli');saver=InMemorySaver()
    replies=iter([ask(),reply('done','finish_task',{'status':'answer','summary':'Unweighted choice accepted'})])
    def model(*_): return next(replies)
    @contextmanager
    def opened(config,session):
        agent=make_graph_agent(store,model,make_token_counter(ModelConfig(tokenizer='bytes')),saver)
        yield Conversation(agent,store.read_record(),tmp_path/'output')
    monkeypatch.setattr(application,'open_conversation',opened)
    from gis_agent.config import AppConfig
    monkeypatch.setattr(AppConfig,'from_env',classmethod(lambda cls,project:None))
    monkeypatch.delenv('GIS_AGENT_SESSIONS_DIR',raising=False)
    runner=CliRunner()
    first=runner.invoke(app,['--project',str(tmp_path),'--session','cli','chat'],input='Weighted task\nexit\n')
    assert first.exit_code==0,first.output
    assert 'needs_input' in first.output
    before=store.path.read_bytes()
    status=runner.invoke(app,['--project',str(tmp_path),'--session','cli','waiting'])
    assert status.exit_code==0 and '"waiting": true' in status.output and store.path.read_bytes()==before
    leave=runner.invoke(app,['--project',str(tmp_path),'--session','cli','chat'],input='')
    assert leave.exit_code==0 and store.path.read_bytes()==before,leave.output
    second=runner.invoke(app,['--project',str(tmp_path),'--session','cli','chat'],input='Approved unweighted\nexit\n')
    assert second.exit_code==0 and 'answer' in second.output,second.output


@pytest.mark.slow
def test_independent_process_shutdown_and_same_session_continue(tmp_path):
    import subprocess,sys
    worker=Path(__file__).with_name('handoff_worker.py')
    for phase in ['wait','answer']:
        run=subprocess.run([sys.executable,str(worker),str(tmp_path),phase],capture_output=True,timeout=60)
        assert run.returncode==0,run.stderr.decode(errors='replace')
    assert json.loads((tmp_path/'wait.json').read_text())['outcome']['status']=='needs_input'
    assert json.loads((tmp_path/'answer.json').read_text())['outcome']['status']=='completed'
    assert json.loads((tmp_path/'result.json').read_text())=={'value':42}
    assert json.loads((tmp_path/'prefix.json').read_text())=={'value':6}
