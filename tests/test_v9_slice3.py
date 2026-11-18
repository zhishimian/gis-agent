import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from gis_agent import config as configuration
from gis_agent.adapters.harness_mcp import build_harness_tools
from gis_agent.agent import Agent
from gis_agent.application import AgentFactory
from gis_agent.config import AppConfig
from gis_agent.core.auxiliary import AuxiliaryCalls
from gis_agent.core.context import ContextConfig, ContextManager
from gis_agent.core.model import ModelConfig, ModelReply
from gis_agent.core.planning import Plan
from gis_agent.integrations.llm import make_token_counter
from gis_agent.persistence.checkpoints import SqliteCheckpointer
from gis_agent.persistence.json import json_text
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.base import Tool
from gis_agent.tools.planning import make_planning_tools
from gis_agent.tools.registry import ToolRegistry


def _reply(call_id: str, name: str, arguments: dict[str, Any]) -> ModelReply:
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
        {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        "tool_calls",
    )


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
            lambda *_: _reply("c2", "finish_task", {"status": "completed", "summary": "对账恢复成功"}),
            store, ctx, checkpointer=saver,
        )
        outcome = agent.resume(store.read_record())
        assert outcome["status"] == "completed"
        assert len(runs) == 0  # 未重复执行已完成副作用工具


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
            lambda *_: _reply("done", "finish_task", {"status": "answer", "summary": "无需QGIS已启动"}),
            counter,
        ).create(store, messages, tmp_path / "out", saver, "无QGIS测试")
        assert "search_qgis_tools" not in agent.registry.tools
        assert "run_python_script" in agent.registry.tools
        assert agent.run(messages)["status"] == "answer"

    monkeypatch.setenv("GIS_AGENT_QGIS_DIR", str(qgis_dir))
    harness_tools = build_harness_tools(tmp_path)
    assert {"inspect_data", "summarize_fields", "check_spatial_relation", "probe_gis_environment", "search_qgis_tools", "run_qgis_algorithm"} <= set(harness_tools)
