import json
import sqlite3
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


def test_real_qgis_metadata_and_enabled_disabled_equivalence(tmp_path: Path, qgis_dir: Path) -> None:
    from dataclasses import replace
    from test_acceptance import make_graph_agent, reply
    from gis_agent.integrations.qgis.adapter import make_tool
    from gis_agent.integrations.qgis.client import QGISClient
    from gis_agent.tools.qgis_python import inspect_data
    source = tmp_path / "point.geojson"
    source.write_text(json.dumps({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
        "features": [{"type": "Feature", "properties": {"id": 7}, "geometry": {"type": "Point", "coordinates": [0, 0]}}]}), encoding="utf-8")
    client = QGISClient(qgis_dir / "bin/qgis_process-qgis-ltr.bat")
    documentation = client.query("help", "native:buffer")
    tool = make_tool("native:buffer", {"name": "buffer"}, documentation, client)
    assert tool.schema() == replace(tool, execution_metadata=None).schema()
    measurements, counts = [], []
    for enabled in (False, True):
        output = tmp_path / str(enabled) / "result.gpkg"
        store = SessionStore(tmp_path / "sessions", f"qgis_{enabled}")
        history = ExecutionHistory(store, output.parent)
        calls = []
        original = tool.function
        def execute(**kwargs):
            calls.append(1)
            return original(**kwargs)
        active = replace(tool, function=execute)
        arguments = {"INPUT": str(source), "DISTANCE": 500, "SEGMENTS": 32, "OUTPUT": str(output)}
        replies = iter([reply("buffer", active.name, arguments), reply("finish", "finish_task", {"status": "completed", "summary": "完成"})])
        agent = make_graph_agent(store, lambda *_: next(replies), make_token_counter(ModelConfig(tokenizer="bytes")), InMemorySaver(), (active,))
        agent.history = history if enabled else None
        assert agent.run([{"role": "user", "origin": "user", "content": "缓冲"}])["status"] == "completed"
        counts.append((len(calls), agent.graph.get_state(agent.options()).values["responses_used"]))
        measured = inspect_data(qgis_dir / "bin/python-qgis-ltr.bat", tmp_path / "measurement_logs", str(output))["data"]
        with sqlite3.connect(f"file:{output.as_posix()}?mode=ro", uri=True) as database:
            table = database.execute("SELECT table_name FROM gpkg_geometry_columns").fetchone()[0]
            features = database.execute('SELECT * FROM "' + table.replace('"', '""') + '"').fetchall()
        measurements.append(({key: measured[key] for key in ("crs", "extent", "feature_count", "fields")}, features))
        if enabled:
            row = history.rows()[0]
            facts = row["facts"]
            assert facts["algorithm_id"] == "native:buffer" and facts["definition_sha256"]
            assert facts["inputs"][0]["source"] == str(source)
            assert facts["outputs"][0]["exists"] and "sha256" not in facts["outputs"][0]
            assert row["arguments"]["DISTANCE"] == 500
    assert counts == [(1, 2), (1, 2)] and measurements[0] == measurements[1]


def test_real_python_snapshot_request_raster_and_resource_scope(tmp_path: Path, qgis_dir: Path) -> None:
    from gis_agent.tools.qgis_python import run_python_script
    output = tmp_path / "outputs" / "python"
    output.mkdir(parents=True)
    script = tmp_path / "make.py"
    script.write_text(
        "import os,json,sys\nfrom osgeo import gdal\n"
        "d=gdal.GetDriverByName('GTiff').Create(sys.argv[1],2,2,1,gdal.GDT_Byte)\n"
        "d.GetRasterBand(1).Fill(7)\nd=None\n"
        "print('actual log')\n"
        "from pathlib import Path\n"
        "Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'outputs':{'raster':sys.argv[1],'missing':sys.argv[2]}}),encoding='utf-8')\n",
        encoding="utf-8")
    arguments = {"script_path": str(script), "arguments": [str(output / "small.tif"), str(output / "missing.tif")]}
    source = call("run_python_script", arguments)
    store = SessionStore(tmp_path / "sessions", "python")
    store.save([assistant(source)])
    history = ExecutionHistory(store, output)
    history.begin(0, 0, source)
    result = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", output / "python_logs", **arguments)
    assert result["ok"], result
    message = store.tool_message("repeated", "run_python_script", result, 8000)
    history.complete("e000000_00", message, 1, 1, arguments)
    store.save([assistant(source), message])
    row = history.rows()[0]
    assert row["facts"]["script"]["actual_code_identity"] == "not_proven"
    assert [item["exists"] for item in row["facts"]["outputs"]] == [True, False]
    assert json.loads(history.read_resource(row, "request")["text"])["arguments"] == arguments["arguments"]
    original = history.read_resource(row, "script")["text"]
    script.write_text("changed", encoding="utf-8")
    assert history.read_resource(history.rows()[0], "script")["text"] == original
    assert "actual log" in history.read_resource(row, "stdout")["text"]
    secret = tmp_path / "secret.env"
    secret.write_text("secret content", encoding="utf-8")
    row["links"]["script_snapshot"] = str(secret)
    assert not history.read_resource(row, "script")["ok"]
    row["links"]["script_snapshot"] = result["script_snapshot"]
    Path(result["script_snapshot"]).write_text("tampered", encoding="utf-8")
    assert not history.read_resource(row, "script")["ok"]


def test_history_tool_after_compaction_reads_fifth_step(tmp_path: Path) -> None:
    from gis_agent.core.auxiliary import AuxiliaryCalls
    from gis_agent.core.context import ContextConfig, ContextManager, SUMMARY_SECTIONS, prefix_digest
    from gis_agent.persistence.evidence import file_digest
    from gis_agent.persistence.json import write_json
    from gis_agent.tools.history import make_history_tool
    from test_acceptance import make_graph_agent, reply
    store = SessionStore(tmp_path / "sessions", "recovery")
    output = tmp_path / "outputs" / "recovery"
    log = output / "python_logs" / "old"
    log.mkdir(parents=True)
    snapshot = log / "script.py"
    snapshot.write_text("area = population / height\n", encoding="utf-8")
    stderr = log / "stderr.txt"
    stderr.write_text("KeyError: original diagnostic\n", encoding="utf-8")
    value = {"ok": False, "stderr": stderr.read_text(), "script_snapshot": str(snapshot),
             "script_sha256": file_digest(snapshot), "stderr_path": str(stderr), "stderr_sha256": file_digest(stderr)}
    old = [{"role": "user", "origin": "user", "content": "计算"},
           assistant(call("run_python_script", {"script_path": "fifth.py", "arguments": ["input.gpkg"]})),
           store.tool_message("repeated", "run_python_script", value, 8000)]
    messages = [*old, {"role": "user", "origin": "user", "content": "继续定位早期问题"}]
    store.save(messages)
    summary = {key: [] for key in SUMMARY_SECTIONS}
    summary["goal"] = [{"text": "继续计算", "sources": [0]}]
    write_json(store.context_path, {"version": 1, "covered": 3, "prefix_digest": prefix_digest(messages, 3), "summary": summary})
    history = ExecutionHistory(store, output)
    tool = make_history_tool(history)
    counter = make_token_counter(ModelConfig(tokenizer="bytes"))
    context = ContextManager(store, ContextConfig(recent_users=1), AuxiliaryCalls(None, store.record_model_call, counter), {tool.name})
    view = context.prepare("系统", messages, {}, [tool])
    assert "original diagnostic" not in str(view.messages)
    result = tool.run({"query": "fifth.py", "section": "detail", "max_characters": 8000})
    detail = json.loads(result["text"])
    assert detail["arguments"]["arguments"] == ["input.gpkg"]
    assert "population / height" in detail["script"]["text"]
    assert "original diagnostic" in detail["stderr"]["text"]
    assert detail["result"]["ok"] is False
    assert not tool.run({"path": str(tmp_path / "secret")})["ok"]
    replies = iter([reply("history", "execution_history", {"query": "fifth.py", "section": "arguments"}),
                    reply("finish", "finish_task", {"status": "answer", "summary": "已定位"})])
    agent = make_graph_agent(store, lambda *_: next(replies), counter, InMemorySaver(), (tool,))
    agent.history = history
    assert agent.run(messages)["status"] == "answer"


def test_cli_history_is_offline_and_chat_syntax_is_compatible(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner
    from gis_agent import cli
    store = SessionStore(tmp_path / "records", "offline")
    store.save([assistant(call("operation", {"value": 5})), store.tool_message("repeated", "operation", {"ok": True}, 8000)])
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


def test_lazy_query_checks_selected_receipt_and_status_filter_checks_all(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, "conflict")
    source = call("a", {})
    message = store.tool_message("repeated", "a", {"ok": True}, 8000)
    store.save([assistant(source), message])
    history = ExecutionHistory(store)
    history.begin(0, 0, source)
    history.complete("e000000_00", message, 1, 1)
    before = history.record_path("e000000_00").read_bytes()
    with pytest.raises(ValueError, match="已完成回执"):
        history.raised("e000000_00", RuntimeError("late"), 2)
    assert history.record_path("e000000_00").read_bytes() == before
    record = json.loads(before)
    record["state"] = "failed"
    history.record_path("e000000_00").write_text(json.dumps(record), encoding="utf-8")
    assert history.query()["items"][0]["status"] == "unknown"
    assert history.query(status="unknown")["matches"] == 1
    assert history.query(status="succeeded")["matches"] == 0
