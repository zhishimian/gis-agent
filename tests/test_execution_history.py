import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from gis_agent.core.model import ModelConfig
from gis_agent.integrations.llm import make_token_counter
from gis_agent.tools.base import Tool

from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.sessions import SessionStore


def call(name: str, arguments: dict, call_id: str = "repeated") -> dict:
    return {"id": call_id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments),
    }}


def assistant(*calls: dict) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


def test_legacy_batches_and_repeated_ids_are_read_only(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, "legacy")
    messages = [
        assistant(call("run_python_script", {"script_path": "five.py"}), call("other", {}, "b")),
        store.tool_message("b", "other", [1, 2], 8000),
        store.tool_message("repeated", "run_python_script", {"ok": False, "stderr": "KeyError: height", "script_snapshot": "snapshot.py"}, 8000),
        assistant(call("run_python_script", {"script_path": "five.py"})),
        store.tool_message("repeated", "run_python_script", {"ok": True}, 8000),
    ]
    store.save(messages)
    original = store.path.read_bytes()
    history = ExecutionHistory(store)
    rows = history.rows()
    assert [row["execution_id"] for row in rows] == ["e000000_00", "e000000_01", "e000003_00"]
    assert rows[0]["status"] == "failed" and rows[0]["sources"]["tool_message_index"] == 2
    assert rows[1]["result"] == [1, 2]
    assert rows[2]["previous_same_script"] == rows[0]["execution_id"]
    assert history.query(query="height", status="failed")["items"][0]["execution_id"] == rows[0]["execution_id"]
    assert json.loads(history.query(execution_id=rows[0]["execution_id"], section="arguments")["text"]) == {"script_path": "five.py"}
    assert store.path.read_bytes() == original
    assert not (tmp_path / "legacy.assets/executions").exists()


def test_incomplete_and_conflicting_batches_remain_unknown(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, "partial")
    store.save([assistant(call("a", {})), assistant(call("b", {}), call("b", {})),
                store.tool_message("repeated", "b", {"ok": True}, 8000)])
    rows = ExecutionHistory(store).rows()
    assert [row["status"] for row in rows] == ["unknown"] * 3
    assert rows[1]["integrity"] == "conflict"


def test_assets_are_verified_without_blocking_other_rows(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, "assets")
    result = {"ok": True, "value": "x" * 5000}
    saved = store.tool_message("repeated", "a", result, 1000)
    store.save([assistant(call("a", {})), saved, assistant(call("b", {})), store.tool_message("repeated", "b", [3], 1000)])
    history = ExecutionHistory(store)
    assert history.rows()[0]["result"] == result
    store.asset_path(saved["asset"]).write_text("{}", encoding="utf-8")
    rows = history.rows()
    assert rows[0]["status"] == "unknown" and rows[0]["integrity"] == "corrupt"
    assert rows[1]["result"] == [3]
    store.asset_path(saved["asset"]).unlink()
    assert history.rows()[0]["status"] == "unknown"
    saved["asset"]["path"] = "../outside.json"
    store.save([assistant(call("a", {})), saved])
    assert history.rows()[0]["integrity"] == "corrupt"


def test_detail_paging_and_bad_arguments(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, "pages")
    bad = call("a", {})
    bad["function"]["arguments"] = "{"
    store.save([assistant(bad), store.tool_message("repeated", "a", {"ok": False, "error": "bad json"}, 8000),
                assistant(call("b", {})), store.tool_message("repeated", "b", {"ok": True, "text": "y" * 2000}, 8000)])
    history = ExecutionHistory(store)
    assert history.rows()[0]["status"] == "rejected"
    page = history.query(execution_id="e000002_00", section="result", max_characters=512)
    rest = history.query(execution_id="e000002_00", section="result", cursor=page["next_cursor"], max_characters=8000)
    assert json.loads(page["text"] + rest["text"])["text"] == "y" * 2000
    assert not history.query(execution_id="../outside", section="result")["ok"]


@pytest.mark.parametrize("value", [[1, 2], {"data": 2}, {"ok": False, "error": "actual failure"}])
def test_automatic_receipts_preserve_results_and_response_count(tmp_path: Path, value) -> None:
    from test_acceptance import make_graph_agent, reply
    counts = []
    for enabled in (False, True):
        store = SessionStore(tmp_path / str(enabled), "run")
        calls = []
        tool = Tool("operation", "操作", {"type": "object"}, lambda: calls.append(1) or value)
        replies = iter([reply("operation", "operation", {}),
                        reply("finish", "finish_task", {"status": "completed", "summary": "完成"})])
        agent = make_graph_agent(store, lambda *_: next(replies), make_token_counter(ModelConfig(tokenizer="bytes")), InMemorySaver(), (tool,))
        agent.history = ExecutionHistory(store) if enabled else None
        assert agent.run([{"role": "user", "origin": "user", "content": "执行"}])["status"] == "completed"
        assert json.loads(store.load()[2]["content"]) == value
        counts.append((agent.graph.get_state(agent.options()).values["responses_used"], len(calls)))
        if enabled:
            row = agent.history.rows()[0]
            assert row["elapsed_ms"] >= 0 and row["started_at"] and row["finished_at"]
            assert row["integrity"] == "ok" and row["pairing"] == "paired"
    assert counts == [(2, 1), (2, 1)]


@pytest.mark.parametrize("boundary", ["begin", "complete"])
def test_auxiliary_write_failure_does_not_stop_tools(tmp_path: Path, monkeypatch, caplog, boundary: str) -> None:
    from test_acceptance import make_graph_agent, reply
    store = SessionStore(tmp_path, "auxiliary")
    count = []
    tool = Tool("write", "写入", {"type": "object"}, lambda: count.append(1) or {"ok": True})
    replies = iter([reply("write", "write", {}), reply("done", "finish_task", {"status": "completed", "summary": "完成"})])
    agent = make_graph_agent(store, lambda *_: next(replies), make_token_counter(ModelConfig(tokenizer="bytes")), InMemorySaver(), (tool,))
    agent.history = ExecutionHistory(store)
    def fail(*args):
        raise OSError("模拟历史磁盘故障")
    monkeypatch.setattr(agent.history, boundary, fail)
    assert agent.run([{"role": "user", "origin": "user", "content": "执行"}])["status"] == "completed"
    assert count == [1] and "历史回执写入失败" in caplog.text
    store.load()


def test_exception_receipt_and_source_conflict(tmp_path: Path) -> None:
    from test_acceptance import make_graph_agent, reply
    store = SessionStore(tmp_path, "exception")
    def fail():
        raise RuntimeError("real tool error")
    agent = make_graph_agent(store, lambda *_: reply("fail", "operation", {}),
                             make_token_counter(ModelConfig(tokenizer="bytes")), InMemorySaver(),
                             (Tool("operation", "异常", {"type": "object"}, fail),))
    agent.history = ExecutionHistory(store)
    with pytest.raises(RuntimeError, match="real tool error"):
        agent.run([{"role": "user", "origin": "user", "content": "执行"}])
    row = agent.history.rows()[0]
    assert row["status"] == "raised" and "traceback_path" in row["links"]
    with pytest.raises(ValueError, match="检查点"):
        agent.resume(store.read_record())
    messages = store.read_record()
    messages[1]["tool_calls"][0]["function"]["arguments"] = '{"changed":true}'
    store.save(messages)
    assert agent.history.rows()[0]["integrity"] == "conflict"


def test_orphan_completion_does_not_repair_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, "orphan")
    source = call("a", {})
    store.save([assistant(source)])
    history = ExecutionHistory(store)
    history.begin(0, 0, source)
    history.complete("e000000_00", store.tool_message("repeated", "a", {"ok": True}, 8000), 1, 2.0)
    before = store.path.read_bytes()
    row = history.rows()[0]
    assert row["pairing"] == "orphan" and row["status"] == "unknown" and row["result"]["ok"]
    assert store.path.read_bytes() == before


def test_critical_session_failure_stops_execution(tmp_path: Path, monkeypatch) -> None:
    from test_acceptance import make_graph_agent, reply
    store = SessionStore(tmp_path, "critical")
    count = []
    agent = make_graph_agent(store, lambda *_: reply("write", "write", {}),
                             make_token_counter(ModelConfig(tokenizer="bytes")), InMemorySaver(),
                             (Tool("write", "写入", {"type": "object"}, lambda: count.append(1)),))
    agent.history = ExecutionHistory(store)
    save = store.save
    def fail_started(messages):
        if any(item.get("executions") for item in messages):
            raise OSError("关键Session写入失败")
        save(messages)
    monkeypatch.setattr(store, "save", fail_started)
    with pytest.raises(OSError, match="关键Session"):
        agent.run([{"role": "user", "origin": "user", "content": "执行"}])
    assert not count and not agent.history.record_dir.exists()


def test_truncated_calls_never_produce_receipts(tmp_path: Path) -> None:
    from test_acceptance import make_graph_agent, reply
    from gis_agent.core.model import ModelReply
    store = SessionStore(tmp_path, "truncated")
    count = []
    message = reply("first", "write", {}).message
    message["tool_calls"].append(call("write", {}, "second"))
    agent = make_graph_agent(store, lambda *_: ModelReply(message, "offline", None, "length"),
                             make_token_counter(ModelConfig(tokenizer="bytes")), InMemorySaver(),
                             (Tool("write", "写入", {"type": "object"}, lambda: count.append(1)),))
    agent.history = ExecutionHistory(store)
    assert agent.run([{"role": "user", "origin": "user", "content": "执行"}])["status"] == "blocked"
    assert not count and not agent.history.record_dir.exists()
