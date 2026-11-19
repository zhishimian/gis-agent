"""运行时探针、空间体征注入、文件/数据工具、脚本隔离与执行历史测试。"""
from __future__ import annotations

from dataclasses import replace
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from dotenv import dotenv_values
import httpx
from openai import OpenAI
import pytest

from gis_agent import config as configuration
from gis_agent.core.context import recent_execution_refs
from gis_agent.core.model import ModelConfig, ModelReply
from gis_agent.integrations.llm import chat, make_token_counter
from gis_agent.integrations.qgis.adapter import execute_algorithm, load_qgis_tool, parameter_schema
from gis_agent.integrations.qgis.catalog import load_catalog, make_search_tool, search_catalog
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.persistence.checkpoints import MemoryCheckpointer as InMemorySaver
from gis_agent.persistence.evidence import file_digest
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.json import truncate_log, write_json
from gis_agent.persistence.sessions import SessionStore
from gis_agent.runtime.probe import probe_launcher, runtime_capabilities
from gis_agent.tools.base import Tool
from gis_agent.tools.files import edit_file, list_files, make_file_tools, read_file, search_text, write_file
from gis_agent.tools.planning import finish_task
from gis_agent.tools.qgis_alg import make_run_qgis_tool
from gis_agent.tools.qgis_python import inspect_data, run_data_check, run_python_script
from gis_agent.tools.registry import ToolRegistry
from conftest import geojson, make_graph_agent, polygon, reply, response

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "gis_agent/skills"


def call(name: str, arguments: dict, call_id: str = "repeated") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def assistant(*calls: dict) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


def execute(qgis_dir: Path, folder: Path, code: str, arguments: list[str] | None = None) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "probe.py"
    script.write_text(code, encoding="utf-8")
    return run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", folder / "logs", str(script), arguments)


def _write_script(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


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


def test_write_refuses_overwrite(tmp_path: Path) -> None:
    path = str(tmp_path / "说明.txt")

    assert write_file(path, "道路数据")["ok"]
    assert not write_file(path, "被覆盖的内容")["ok"]
    assert read_file(path)["content"] == "道路数据"


@pytest.mark.slow
def test_inspect_vector(tmp_path: Path) -> None:
    source = tmp_path / "point.geojson"
    source.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "测试点"},
                "geometry": {
                    "type": "Point",
                    "coordinates": [118.8, 32.0],
                },
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    directory = os.environ.get("GIS_AGENT_QGIS_DIR") or dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("GIS_AGENT_QGIS_DIR")
    if not directory:
        pytest.skip("请设置 GIS_AGENT_QGIS_DIR。")
    result = inspect_data(
        Path(directory) / "bin" / "python-qgis-ltr.bat",
        tmp_path / "logs",
        str(source),
    )

    assert result["ok"], result
    assert result["data"]["feature_count"] == 1
    assert result["data"]["crs"] == "EPSG:4326"
    assert result["data"]["samples"][0]["name"] == "测试点"


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
    from conftest import make_graph_agent, reply
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
    from conftest import make_graph_agent, reply
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
    from conftest import make_graph_agent, reply
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
    from conftest import make_graph_agent, reply
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
    from conftest import make_graph_agent, reply
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
    from conftest import make_graph_agent, reply
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
    from conftest import make_graph_agent, reply
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


def test_edit_preserves_bytes_and_rejects_ambiguity_or_stale_version(tmp_path: Path) -> None:
    path = tmp_path / "script.py"
    path.write_bytes(b"a = 1\r\nb = 2\r\n")
    original = path.read_bytes()
    assert not edit_file(str(path), "missing", "3")["ok"]
    assert not edit_file(str(path), "", "3")["ok"]
    assert not edit_file(str(path), " = ", "3")["ok"]
    assert not edit_file(str(path), "a = 1", "a = 3", "old")["ok"]
    assert path.read_bytes() == original
    result = edit_file(str(path), "a = 1", "a = 3", read_file(str(path))["sha256"])
    assert result["ok"] and "a = 3" in result["diff"]
    assert path.read_bytes() == b"a = 3\r\nb = 2\r\n"
    assert search_text(str(path), "a = 3")["results"][0]["line"] == 1
    assert not list_files(str(path))["ok"]
    assert edit_file(str(path), "a = 3\nb = 2", "a = 4\nb = 2")["ok"]
    assert path.read_bytes() == b"a = 4\r\nb = 2\r\n"
    path.write_bytes(b"\xff\xfe")
    assert not edit_file(str(path), "x", "y")["ok"]
    assert not read_file(str(path))["ok"]


def test_tool_argument_errors_do_not_hide_internal_failures() -> None:
    tool = Tool("read", "read", {}, lambda path: path)
    assert not tool.run({})["ok"]
    def failure():
        raise TypeError("执行实现错误")
    with pytest.raises(TypeError, match="实现错误"):
        Tool("broken", "broken", {}, failure).run({})


def test_exact_catalog_id_does_not_load_unrelated_algorithms() -> None:
    catalog = {"native:buffer": {"name": "Buffer"}, "gdal:buffervectors": {"name": "Buffer vectors"},
               "native:joinbynearest": {"name": "Join attributes by nearest"}}
    result = search_catalog(catalog, "native:buffer", limit=1)
    assert [row["algorithm_id"] for row in result] == ["native:buffer"]
    assert not search_catalog(catalog, "")
    assert not search_catalog(catalog, "缓冲")


def test_script_result_file_and_failure_state(qgis_dir: Path, tmp_path: Path) -> None:
    script = tmp_path / "result.py"
    script.write_text('import json, os\nfrom pathlib import Path\nPath(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(json.dumps({"value": 42}))\nprint("RESULT is just a log")\n', encoding="utf-8")
    launcher = qgis_dir / "bin/python-qgis-ltr.bat"
    good = run_python_script(launcher, tmp_path / "logs", str(script))
    assert good["ok"] and good["result"]["value"] == 42, good
    script.write_text(script.read_text(encoding="utf-8") + 'raise ValueError("失败状态保留")\n', encoding="utf-8")
    failed = run_python_script(launcher, tmp_path / "logs", str(script))
    assert not failed["ok"] and failed["result"]["value"] == 42
    assert "失败状态保留" in failed["stderr"]
    script.write_text('import os\nfrom pathlib import Path\nPath(os.environ["GIS_AGENT_RESULT_PATH"]).write_text("invalid")\n', encoding="utf-8")
    malformed = run_python_script(launcher, tmp_path / "logs", str(script))
    assert not malformed["ok"] and "有效JSON" in malformed["error"]


def test_batch_intake_statistics_and_spatial_identity(qgis_dir: Path, tmp_path: Path) -> None:
    source = geojson(tmp_path / "buildings.geojson", [({"row": 8, "owner": 1, "area": 100, "people": 2}, polygon(0)),
        ({"row": 8, "owner": 2, "area": 60, "people": None}, polygon(0)),
        ({"row": 10, "owner": 99, "area": 30, "people": 0}, polygon(20))])
    reference = geojson(tmp_path / "owners.geojson", [({"key": 1}, polygon(0)), ({"key": 2}, polygon(20))])
    launcher = qgis_dir / "bin/python-qgis-ltr.bat"
    batch = inspect_data(launcher, tmp_path / "logs", sources=[str(source), str(reference), str(tmp_path / "missing.gpkg")])
    assert batch["ok"], batch
    assert [item["ok"] for item in batch["data"]["datasets"]] == [True, True, False]
    facts = run_data_check(launcher, tmp_path / "logs", "fields", source=str(source), fields=["area", "people"], key="row", check_geometry=True)
    assert facts["ok"], facts
    data = facts["result"]
    assert data["fields"]["area"]["sum"] == 190
    assert data["fields"]["people"]["null"] == 1
    assert data["samples"][0]["area"] / data["samples"][0]["people"] == 50
    assert data["key"]["duplicate_rows"] == 1 and data["geometry"]["invalid"] == 0
    relation = run_data_check(launcher, tmp_path / "logs", "relations", source=str(source), reference=str(reference), foreign_key="owner", reference_key="key")
    assert relation["ok"], relation
    assert relation["result"]["violations"] == 1 and relation["result"]["missing_key"] == 1
    duplicate = run_data_check(launcher, tmp_path / "logs", "relations", source=str(source), reference=str(source), foreign_key="owner", reference_key="row")
    assert not duplicate["ok"] and "重复" in duplicate["stderr"]
    table = tmp_path / "values.csv"
    table.write_text("id,name\n1,a\n2,b\n", encoding="utf-8")
    attributes = run_data_check(launcher, tmp_path / "logs", "fields", source=str(table), fields=["name"], key="id")
    assert attributes["ok"] and attributes["result"]["count"] == 2, attributes


def test_qgis_algorithm_warning_and_fixed_precision(qgis_dir: Path, tmp_path: Path) -> None:
    client = QGISClient(qgis_dir / "bin/qgis_process-qgis-ltr.bat")
    catalog = load_catalog(client)
    registry = ToolRegistry()
    join = load_qgis_tool(client, catalog, registry, "native:joinattributesbylocation")
    assert "稳定ID" in join.description and "FID" in join.description
    source = geojson(tmp_path / "input.geojson", [({"id": 1}, {"type": "Point", "coordinates": [0, 0]})])
    buffer = load_qgis_tool(client, catalog, registry, "native:buffer")
    output = tmp_path / "buffer.gpkg"
    assert buffer.run({"INPUT": str(source), "DISTANCE": 500, "SEGMENTS": 32, "OUTPUT": str(output)})["ok"]
    script = tmp_path / "measure.py"
    script.write_text(f'''import json, math, os
from pathlib import Path
from qgis.core import QgsApplication, QgsVectorLayer
def measure():
    layer = QgsVectorLayer({str(output)!r}, "result", "ogr")
    feature = next(layer.getFeatures())
    geometry = feature.geometry()
    return {{"area_error": abs(geometry.area() - math.pi * 500 ** 2) / (math.pi * 500 ** 2), "valid": geometry.isGeosValid(), "id": feature["id"]}}
app = QgsApplication([], False)
app.initQgis()
try:
    Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(json.dumps(measure()))
finally:
    app.exitQgis()
''', encoding="utf-8")
    measured = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", tmp_path / "logs", str(script))
    assert measured["ok"] and measured["result"]["valid"] and measured["result"]["id"] == 1, measured
    assert measured["result"]["area_error"] < 0.0005


def test_windows_arguments_roundtrip_and_project_import(qgis_dir: Path, tmp_path: Path) -> None:
    arguments = ['中文 空格.gpkg|layername=点', 'a&b>c<d^e%PATH%!', '"双引号"', "", "两行\n内容"]
    result = execute(qgis_dir, tmp_path / "中文 & 目录", '''import json, os, sys
from pathlib import Path
import gis_agent
Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(json.dumps({"arguments": sys.argv[1:], "cwd": str(Path.cwd())}), encoding="utf-8")
''', arguments)
    assert result["ok"] and result["result"]["arguments"] == arguments, result
    assert Path(result["result"]["cwd"]) == tmp_path / "中文 & 目录"


def test_exact_algorithm_excludes_similarly_named_candidates() -> None:
    catalog = {key: {"name": name} for key, name in (
        ("native:buffer", "Buffer"), ("gdal:buffervectors", "Buffer vectors"),
        ("native:singlesidedbuffer", "Single sided buffer"),
    )}
    assert [item["algorithm_id"] for item in search_catalog(catalog, " NATIVE:BUFFER ")] == ["native:buffer"]
    assert len(search_catalog(catalog, "buffer")) == 3


def test_real_help_schema_and_parameter_case(qgis_dir: Path, tmp_path: Path) -> None:
    client = QGISClient(qgis_dir / "bin/qgis_process-qgis-ltr.bat")
    parameters = client.query("help", "native:buffer")["parameters"]
    for name in ("DISTANCE", "SEGMENTS", "DISSOLVE", "END_CAP_STYLE"):
        schema = parameter_schema(parameters[name])
        assert not any(text in schema["description"] for text in ("field:", "expression:"))
    assert parameter_schema(parameters["DISTANCE"])["type"] == "number"
    assert parameter_schema(parameters["DISSOLVE"])["type"] == "boolean"
    output = tmp_path / "should_not_exist.gpkg"
    result = execute_algorithm(client, "native:buffer", parameters, input="missing", OUTPUT=str(output))
    assert not result["ok"] and "INPUT" in result["allowed_parameters"]
    assert "input" in result["error"] and not output.exists()


def test_processing_lifecycle_and_failure(qgis_dir: Path, tmp_path: Path) -> None:
    source = tmp_path / "points.geojson"
    source.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": 17}, "geometry": {"type": "Point", "coordinates": [117, 32]}}
    ]}), encoding="utf-8")
    script = tmp_path / "analysis.py"
    script.write_text('''import sys
from qgis.core import QgsVectorLayer
from gis_agent.integrations.qgis.python_runtime import run_processing

def job():
    import processing
    layer = QgsVectorLayer(sys.argv[1], 'input', 'ogr')
    if sys.argv[2] == 'fail':
        raise ValueError('expected_field_failure')
    if sys.argv[2] == 'serialize':
        return {'layer': layer}
    result = processing.run('native:reprojectlayer', {
        'INPUT': layer, 'TARGET_CRS': 'EPSG:32650', 'OUTPUT': sys.argv[2],
    })
    output = QgsVectorLayer(result['OUTPUT'], 'output', 'ogr')
    return {'count': output.featureCount(), 'crs': output.crs().authid(),
            'id': next(output.getFeatures())['id']}

run_processing(job)
''', encoding="utf-8")
    launcher = qgis_dir / "bin/python-qgis-ltr.bat"
    for number in range(2):
        output = tmp_path / f"projected{number}.gpkg"
        result = run_python_script(launcher, tmp_path / "logs", str(script), [str(source), str(output)])
        assert result["ok"] and result["returncode"] == 0, result
        assert result["result"] == {"count": 1, "crs": "EPSG:32650", "id": 17}
        output.rename(tmp_path / f"released{number}.gpkg")
    for mode, error in (("fail", "expected_field_failure"), ("serialize", "not JSON serializable")):
        result = run_python_script(launcher, tmp_path / "logs", str(script), [str(source), mode])
        assert not result["ok"] and result["returncode"] == 1, result
        assert error in result["stderr"] and "result" not in result


def test_processing_import_error_has_actionable_hint(qgis_dir: Path, tmp_path: Path) -> None:
    script = tmp_path / "missing_import.py"
    script.write_text("import processing\n", encoding="utf-8")
    result = run_python_script(qgis_dir / "bin/python-qgis-ltr.bat", tmp_path / "logs", str(script))
    assert not result["ok"] and "ModuleNotFoundError" in result["stderr"]
    assert Path(result["hint"].split("：", 1)[1]).is_file()


def test_finish_exposes_unmet_requirements() -> None:
    result = finish_task("completed", "done", unresolved=["missing required output"])
    assert not result["ok"] and result["unresolved"] == ["missing required output"]
    assert finish_task("completed", "层名为result，已完成要求。")["ok"]


def test_staged_persist_failure_and_continue(qgis_dir, tmp_path):
    code = f'''import sys, json, os, hashlib
from pathlib import Path
sys.path.insert(0,{str(SKILLS / 'gis-data-io-and-staging/scripts')!r})
import numpy as np
from staged_compute import main
folder=Path.cwd();prepared=folder/'prefix.npy';output=folder/'stats.json'
main({{'inputs':{{}},'parameters':{{'mode':'prepare','size':10000,'rounds':20}},'outputs':{{'prepared':str(prepared)}}}})
digest=hashlib.sha256(prepared.read_bytes()).hexdigest()
try: main({{'inputs':{{'prepared':str(prepared)}},'parameters':{{'mode':'wrong'}},'outputs':{{'statistics':str(output)}}}})
except ValueError: pass
else: raise AssertionError('Expected downstream failure')
result=main({{'inputs':{{'prepared':str(prepared)}},'parameters':{{'mode':'summarize'}},'outputs':{{'statistics':str(output)}}}})
values=np.load(prepared,allow_pickle=False)
assert json.loads(output.read_text())['sum']==float(values.sum())
assert hashlib.sha256(prepared.read_bytes()).hexdigest()==digest
result['prefix_runs']=1
Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps(result))
'''
    run = execute(qgis_dir, tmp_path, code)
    assert run['ok'], run


def test_recent_refs_and_directory_history_preserve_raw_record(tmp_path):
    store = SessionStore(tmp_path / 'sessions', 'history')
    output = tmp_path / 'output'
    gdb = output / 'data.gdb'
    gdb.mkdir(parents=True)
    history = ExecutionHistory(store, output)
    args = {'script_path': 'derive.py'}
    call = {'id': 'c', 'type': 'function', 'function': {'name': 'run_python_script', 'arguments': json.dumps(args)}}
    result = {'ok': True, 'result': {'outputs': {'features': str(gdb)}}}
    message = store.tool_message('c', 'run_python_script', result, 8000)
    message['execution_id'] = 'e000000_00'
    records = [{'role': 'assistant', 'content': None, 'tool_calls': [call]}, message]
    store.save(records)
    before = store.path.read_bytes()
    refs = recent_execution_refs(records)
    assert refs == [{'id': 'e000000_00', 'tool': 'run_python_script'}]
    assert len(json.dumps(refs)) <= 512
    facts = history.rows()[0]['facts']['outputs'][0]
    assert facts['path_exists'] and facts['kind'] == 'directory' and facts['layer_verified'] is None
    item = history.query()['items'][0]
    assert item['output_refs'][0]['source'] == str(gdb)
    assert store.path.read_bytes() == before
    assert recent_execution_refs([{'role':'tool','tool_name':'read_file','execution_id':'e1'}]) == []


def test_staged_example_history_and_tail_repair_reuse_prefix(qgis_dir, tmp_path):
    """Actual prefix persisted on disk; Agent inspects execution_history and repairs tail without recomputing prefix."""
    import httpx
    from openai import OpenAI
    from dataclasses import replace
    from functools import partial
    from gis_agent.persistence.checkpoints import MemoryCheckpointer as InMemorySaver
    from gis_agent.application import AgentFactory
    from gis_agent.config import AppConfig
    from gis_agent.core.model import ModelConfig
    from gis_agent.integrations.llm import chat, make_token_counter
    from gis_agent.integrations.qgis.client import QGISClient
    from gis_agent.persistence.evidence import file_digest
    from gis_agent.persistence.executions import execution_id, record_history
    from gis_agent.tools.base import Tool

    def recorded(history, tool, arguments):
        messages = history.store.read_record()
        idx = len(messages)
        call = {'id': f'c{idx}', 'type': 'function', 'function': {'name': tool.name, 'arguments': json.dumps(arguments)}}
        messages.append({'role': 'assistant', 'content': None, 'tool_calls': [call], 'executions': {call['id']: 'started'}})
        history.store.save(messages)
        identifier = execution_id(idx, 0)
        record_history(history.begin, idx, 0, call, tool.execution_metadata)
        result = tool.run(arguments)
        messages[-1]['executions'][call['id']] = 'finished'
        stored = history.store.tool_message(call['id'], tool.name, result, 8000)
        stored['execution_id'] = identifier
        record_history(history.complete, identifier, stored, len(messages), 1.0, arguments)
        messages.append(stored)
        history.store.save(messages)
        return identifier, result

    output = tmp_path / 'output'
    output.mkdir()
    history = ExecutionHistory(SessionStore(tmp_path / 'sessions', 'staged'), output)
    history.store.save([{'role': 'user', 'origin': 'user', 'content': 'Compute and summarize saved observations.'}])
    script = SKILLS / 'gis-data-io-and-staging/scripts/staged_compute.py'
    prepared = output / 'prepared.npy'
    prefix_job = output / 'prefix.json'
    prefix_job.write_text(json.dumps({'inputs': {}, 'parameters': {'mode': 'prepare', 'size': 20000, 'rounds': 25},
                                      'outputs': {'prepared': str(prepared)}}))
    tool = Tool('run_python_script', 'Python', {}, partial(run_python_script,
                 qgis_dir / 'bin/python-qgis-ltr.bat', output / 'python_logs'))
    _, prefix = recorded(history, tool, {'script_path': str(script), 'arguments': [str(prefix_job)]})
    assert prefix['ok'], prefix
    before = file_digest(prepared)
    tail_job = output / 'tail.json'
    stats_path = output / 'stats.json'
    tail_job.write_text(json.dumps({'inputs': {'prepared': str(prepared)}, 'parameters': {'mode': 'broken'},
                                    'outputs': {'statistics': str(stats_path)}}))
    source_id, failed = recorded(history, tool, {'script_path': str(script), 'arguments': [str(tail_job)]})
    assert not failed['ok']
    fixed_job = json.dumps({'inputs': {'prepared': str(prepared)}, 'parameters': {'mode': 'summarize'},
                            'outputs': {'statistics': str(stats_path)}})
    replies = [
        ('execution_history', {'execution_id': source_id, 'section': 'detail'}),
        ('write_file', {'path': str(tail_job), 'content': fixed_job, 'overwrite': True}),
        ('run_python_script', {'script_path': str(script), 'arguments': [str(tail_job)]}),
        ('finish_task', {'status': 'completed', 'summary': 'Tail repaired with saved observations.', 'artifacts': [str(stats_path)]}),
    ]
    requests = []
    def response(request):
        requests.append(json.loads(request.content))
        name, args = replies[len(requests) - 1]
        return httpx.Response(200, json={'id': str(len(requests)), 'model': 'offline', 'object': 'chat.completion',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': f'c{len(requests)}', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})
    config = replace(AppConfig.from_env(ROOT), memory=None, model=ModelConfig(tokenizer='bytes', supports_images=False, image_tokens=0))
    messages = history.store.load() + [{'role': 'user', 'origin': 'user', 'content': 'Fix the tail preserving the valid prefix.'}]
    with OpenAI(api_key='offline', max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(response))) as client:
        agent = AgentFactory(config, partial(chat, client, config.model), make_token_counter(config.model),
                             QGISClient(config.qgis.process_launcher), {}).create(
                                 history.store, messages, output, InMemorySaver(), 'Repair from current evidence.')
        assert agent.run(messages)['status'] == 'completed'
    assert file_digest(prepared) == before
    assert json.loads(stats_path.read_text())['count'] == 20000
    assert len(requests) == 4


def test_recent_hints_do_not_add_rounds_to_ordinary_python(qgis_dir, tmp_path, monkeypatch):
    from gis_agent.persistence.checkpoints import MemoryCheckpointer as InMemorySaver
    from functools import partial
    from conftest import make_graph_agent, reply
    from gis_agent.core import context
    from gis_agent.core.model import ModelConfig
    from gis_agent.integrations.llm import make_token_counter
    from gis_agent.tools.base import Tool
    real_hints = context.recent_execution_refs
    outcomes = []
    for enabled in (False, True):
        folder = tmp_path / str(enabled)
        folder.mkdir()
        script = folder / 'sum.py'
        script.write_text("import os,json\nfrom pathlib import Path\nPath(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps({'sum':sum(range(10))}))")
        store = SessionStore(folder/'sessions','ordinary')
        calls = []
        def execute(script_path):
            calls.append(script_path)
            return run_python_script(qgis_dir/'bin/python-qgis-ltr.bat',folder/'logs',script_path)
        tool = Tool('run_python_script','Python',{'type':'object','properties':{'script_path':{'type':'string'}}},execute)
        replies = iter([reply('calc','run_python_script',{'script_path':str(script)}),
                        reply('done','finish_task',{'status':'completed','summary':'sum computed'})])
        count = []
        def model(*args):
            count.append(1)
            return next(replies)
        monkeypatch.setattr(context,'recent_execution_refs',real_hints if enabled else lambda _: [])
        agent = make_graph_agent(store,model,make_token_counter(ModelConfig(tokenizer='bytes')),InMemorySaver(),(tool,))
        agent.history = ExecutionHistory(store,folder)
        assert agent.run([{'role':'user','origin':'user','content':'Compute a sum.'}])['status']=='completed'
        facts = agent.history.rows()[0]['result']['result']
        outcomes.append((len(count),len(calls),facts))
    assert outcomes == [(2,1,{'sum':45})]*2


def test_write_json_retries_transient_permission_error(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "session.json"
    attempts = []
    original_replace = Path.replace

    def flaky_replace(self: Path, dst: Path) -> Path:
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("模拟 Windows 瞬时句柄占用")
        return original_replace(self, dst)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    write_json(target, {"ok": True, "turn": 3})
    assert len(attempts) == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True, "turn": 3}


def test_truncate_log_preserves_head_and_tail_traceback() -> None:
    lines = ["Header: starting job\n"] + [f"progress {i}\n" for i in range(200)] + ["ValueError: invalid CRS\n"]
    text = "".join(lines)
    shortened = truncate_log(text, limit=1200, head_lines=5, tail_lines=5)
    assert len(shortened) <= 1200
    assert "Header: starting job" in shortened
    assert "ValueError: invalid CRS" in shortened
    assert "省略" in shortened


@pytest.mark.slow
def test_script_timeout_kills_process_tree_and_keeps_partial_logs(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    script = tmp_path / "hang.py"
    script.write_text(
        f"import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        f"print('spawned grandchild', flush=True)\n"
        f"time.sleep(120)\n",
        encoding="utf-8",
    )
    result = run_python_script(Path(sys.executable), tmp_path / "logs", str(script), timeout_sec=5)
    assert not result["ok"]
    assert result["timed_out"] and result["status"] == "timed_out"
    assert "spawned grandchild" in result["stdout"]
    if pid_file.is_file():
        grandchild_pid = int(pid_file.read_text().strip())
        # 验证孙进程也已被进程树清理终止
        check = run_python_script(
            Path(sys.executable),
            tmp_path / "logs",
            str(
                _write_script(
                    tmp_path / "check_pid.py",
                    f"import os, json\n"
                    f"alive = False\n"
                    f"try:\n"
                    f"    os.kill({grandchild_pid}, 0)\n"
                    f"    alive = True\n"
                    f"except OSError:\n"
                    f"    alive = False\n"
                    f"open(os.environ['GIS_AGENT_RESULT_PATH'], 'w').write(json.dumps({{'alive': alive}}))\n",
                )
            ),
        )
        assert check["ok"] and not check["result"]["alive"]


def test_recursive_output_discovery_and_protected_input_detection(tmp_path: Path) -> None:
    raw_input = tmp_path / "input" / "roads.geojson"
    raw_input.parent.mkdir()
    raw_input.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    out_root = tmp_path / "outputs"
    script = tmp_path / "nested_out.py"
    script.write_text(
        f"from pathlib import Path\n"
        f"target = Path({str(out_root / 'stage1' / 'sub' / 'clean.geojson')!r})\n"
        f"target.parent.mkdir(parents=True, exist_ok=True)\n"
        f"target.write_text('ok', encoding='utf-8')\n",
        encoding="utf-8",
    )
    good = run_python_script(
        Path(sys.executable),
        tmp_path / "logs",
        str(script),
        watch_roots=(out_root,),
        protected_paths=(raw_input.parent,),
    )
    assert good["ok"] and good["status"] == "succeeded"
    assert any(item["path"].endswith("clean.geojson") and item["bytes"] == 2 and not item["empty"] for item in good["outputs"])

    tamper = tmp_path / "tamper.py"
    tamper.write_text(f"open({str(raw_input)!r}, 'w').write('corrupted')\n", encoding="utf-8")
    bad = run_python_script(
        Path(sys.executable),
        tmp_path / "logs",
        str(tamper),
        protected_paths=(raw_input.parent,),
    )
    assert not bad["ok"] and "受保护输入" in bad["error"]


def test_file_tools_write_boundaries_and_finish_nonempty_check(tmp_path: Path) -> None:
    protected = tmp_path / "dataset"
    protected.mkdir()
    raw = protected / "source.csv"
    raw.write_text("a,b\n1,2\n", encoding="utf-8")
    workspace = tmp_path / "work"
    tools = {t.name: t for t in make_file_tools(allowed_roots=(workspace,), protected_paths=(protected,))}

    assert not tools["write_file"].run({"path": str(protected / "hack.txt"), "content": "x"})["ok"]
    assert not tools["edit_file"].run({"path": str(raw), "old_text": "1,2", "new_text": "9,9"})["ok"]
    assert not tools["write_file"].run({"path": str(tmp_path / "outside.txt"), "content": "x"})["ok"]
    ok_write = tools["write_file"].run({"path": str(workspace / "script.py"), "content": "print(1)"})
    assert ok_write["ok"]

    empty_artifact = workspace / "empty.gpkg"
    empty_artifact.write_bytes(b"")
    rejected = finish_task("completed", "交付空文件", artifacts=[str(empty_artifact)])
    assert not rejected["ok"] and "0字节" in rejected["error"]
    assert finish_task("completed", "交付正常脚本", artifacts=[str(workspace / "script.py")], output_dir=workspace)["ok"]


def test_static_qgis_search_and_run_validation(qgis_dir: Path, tmp_path: Path) -> None:
    client = QGISClient(qgis_dir / "bin/qgis_process-qgis-ltr.bat")
    catalog = load_catalog(client)
    cache: dict = {}
    protected = tmp_path / "protected"
    protected.mkdir()
    source = protected / "pt.geojson"
    source.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": [{"type": "Feature", "properties": {"id": 1}, "geometry": {"type": "Point", "coordinates": [0, 0]}}],
        }),
        encoding="utf-8",
    )
    search_tool = make_search_tool(catalog, client, cache)
    run_tool = make_run_qgis_tool(client, catalog, cache, protected_paths=(protected,))

    found = search_tool.run({"query": "native:buffer", "limit": 1})
    assert len(found) == 1 and "DISTANCE" in found[0]["parameters"]
    assert "native:buffer" in cache

    # 大小写错误参数被拦截
    bad_key = run_tool.run({"algorithm_id": "native:buffer", "parameters": {"input": str(source), "OUTPUT": str(tmp_path / "a.gpkg")}})
    assert not bad_key["ok"] and "INPUT" in bad_key["allowed_parameters"]

    # 禁止写入受保护目录
    bad_dest = run_tool.run({"algorithm_id": "native:buffer", "parameters": {"INPUT": str(source), "DISTANCE": 100, "OUTPUT": str(protected / "out.gpkg")}})
    assert not bad_dest["ok"] and "受保护" in bad_dest["error"]

    # 正常执行与禁止覆盖已有输出
    out = tmp_path / "out" / "buffered.gpkg"
    good = run_tool.run({"algorithm_id": "native:buffer", "parameters": {"INPUT": str(source), "DISTANCE": 100, "OUTPUT": str(out)}})
    assert good["ok"] and out.is_file() and out.stat().st_size > 0
    overwrite = run_tool.run({"algorithm_id": "native:buffer", "parameters": {"INPUT": str(source), "DISTANCE": 100, "OUTPUT": str(out)}})
    assert not overwrite["ok"]


def test_fast_inspect_raster_byte_rgb_and_scaled_dn(qgis_dir: Path, tmp_path: Path) -> None:
    launcher = qgis_dir / "bin/python-qgis-ltr.bat"
    setup = tmp_path / "make_rasters.py"
    rgb_path = tmp_path / "rgb_display.tif"
    dn_path = tmp_path / "scaled_dn.tif"
    gpkg_path = tmp_path / "multi.gpkg"
    setup.write_text(
        f"""import numpy as np, rasterio, geopandas as gpd
from rasterio.transform import from_origin
from rasterio.enums import ColorInterp
from shapely.geometry import Point, Polygon

rgb = np.full((20, 30), 128, dtype='uint8')
with rasterio.open({str(rgb_path)!r}, 'w', driver='GTiff', width=30, height=20, count=3,
                   dtype='uint8', crs='EPSG:32650', transform=from_origin(500000, 3500000, 10, 10)) as dst:
    dst.colorinterp = [ColorInterp.red, ColorInterp.green, ColorInterp.blue]
    for b in (1, 2, 3):
        dst.write(rgb, b)

dn = np.linspace(1000, 8000, 600, dtype='int16').reshape(20, 30)
dn[0, 1] = -9999
with rasterio.open({str(dn_path)!r}, 'w', driver='GTiff', width=30, height=20, count=1,
                   dtype='int16', crs='EPSG:32650', transform=from_origin(500000, 3500000, 30, 30), nodata=-9999) as dst:
    dst.scales = (0.0001,)
    dst.offsets = (0.0,)
    dst.units = ('reflectance',)
    dst.write(dn, 1)

gpd.GeoDataFrame({{'id': [1]}}, geometry=[Point(500010, 3499990)], crs='EPSG:32650').to_file({str(gpkg_path)!r}, layer='pts')
bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])
gpd.GeoDataFrame({{'id': [1]}}, geometry=[bowtie], crs='EPSG:32650').to_file({str(gpkg_path)!r}, layer='invalid_poly')
""",
        encoding="utf-8",
    )
    assert run_python_script(launcher, tmp_path / "logs", str(setup))["ok"]

    batch = inspect_data(launcher, tmp_path / "logs", sources=[str(rgb_path), str(dn_path), str(gpkg_path)])
    assert batch["ok"], batch
    rgb_info, dn_info, container_info = batch["data"]["datasets"]

    assert rgb_info["kind"] == "raster"
    assert [b["dtype"] for b in rgb_info["bands"]] == ["uint8", "uint8", "uint8"]
    assert [b["colorinterp"] for b in rgb_info["bands"]] == ["red", "green", "blue"]
    assert rgb_info["units"] == "metre"

    assert dn_info["kind"] == "raster"
    band = dn_info["bands"][0]
    assert band["dtype"] == "int16" and band["nodata"] == -9999
    assert band["scale"] == 0.0001 and band["unit"] == "reflectance"
    assert band["overview_sample"]["raw_min"] == 1000.0 and band["overview_sample"]["raw_max"] == 8000.0
    assert 0.99 < band["overview_sample"]["valid_ratio"] < 1.0

    assert container_info["kind"] == "container"
    assert {layer["name"] for layer in container_info["layers"]} == {"pts", "invalid_poly"}

    poly_uri = f"{gpkg_path}|layername=invalid_poly"
    poly_info = inspect_data(launcher, tmp_path / "logs", source=poly_uri)
    assert poly_info["ok"], poly_info
    assert poly_info["data"]["geometry_sample_check"]["invalid"] == 1
    assert poly_info["data"]["units"] == "metre"


def test_probe_launcher_reports_packages(qgis_dir: Path) -> None:
    info = probe_launcher(qgis_dir / "bin/python-qgis-ltr.bat")
    assert info["has_qgis"] is True
    assert "geopandas" in info["packages"] and "rasterio" in info["packages"]


def test_standalone_uv_geopython_inspect_and_plotting_without_qgis(tmp_path: Path) -> None:
    """脱离 Conda 与桌面 QGIS 时，独立 GeoPython 解释器仍可完成快速探针与成图导出。"""
    import importlib.util
    import sys

    if any(importlib.util.find_spec(mod) is None for mod in ("geopandas", "rasterio", "matplotlib", "pyogrio")):
        pytest.skip("当前解释器未安装 geo 可选依赖组。")

    import geopandas as gpd
    from matplotlib import pyplot as plt
    from shapely.geometry import Point

    from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure
    from gis_agent.runtime.probe import probe_launcher
    from gis_agent.tools.qgis_python import inspect_data

    launcher = Path(sys.executable)
    probed = probe_launcher(launcher)
    assert probed["has_qgis"] is False or "geopandas" in probed["packages"]
    assert {"geopandas", "rasterio", "pyogrio", "matplotlib"}.issubset(probed["packages"].keys())

    shp_dir = tmp_path / "data"
    shp_dir.mkdir()
    pts_path = shp_dir / "pts.gpkg"
    gpd.GeoDataFrame({"name": ["A"]}, geometry=[Point(500000, 3500000)], crs="EPSG:32650").to_file(pts_path)
    info = inspect_data(launcher, tmp_path / "logs", source=str(pts_path))
    assert info["ok"] and info["data"]["feature_count"] == 1 and info["data"]["units"] == "metre"

    configure_plotting()
    fig, ax = plt.subplots()
    gpd.read_file(pts_path).plot(ax=ax)
    map_dir = tmp_path / "map_out"
    exported = export_figure(fig, map_dir, inputs=(pts_path,), map_panels=(MapPanel("main", ax, "EPSG:32650"),))
    plt.close(fig)
    assert exported["ok"] and Path(exported["files"]["png"]).stat().st_size > 0


def test_spatial_vitals_attachment_and_runtime_capabilities(tmp_path: Path) -> None:
    """运行产物自动附带客观空间体征（vector/raster），且运行时能力可稳定缓存并注入上下文。"""
    import importlib.util
    import sys

    if any(importlib.util.find_spec(mod) is None for mod in ("geopandas", "rasterio", "numpy")):
        pytest.skip("当前解释器未安装 geo 依赖。")

    import geopandas as gpd
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import Point

    from gis_agent.runtime.probe import runtime_capabilities
    from gis_agent.tools.qgis_python import run_python_script

    caps1 = runtime_capabilities(Path(sys.executable), has_qgis_process=False)
    caps2 = runtime_capabilities(Path(sys.executable), has_qgis_process=False)
    assert caps1 == caps2
    assert caps1["mode"] in {"tier_b", "dual"}
    assert "pykrige" in caps1["tier_b_available"]
    assert "esda" in caps1["tier_b_available"]
    assert "cartography_available" in caps1 and isinstance(caps1["cartography_available"], list)
    if importlib.util.find_spec("cartopy") is not None:
        assert {"adjustText", "cartopy", "cmcrameri", "matplotlib-scalebar"}.issubset(set(caps1["cartography_available"]))

    script = tmp_path / "make_outputs.py"
    vec_out = tmp_path / "pts.gpkg"
    ras_out = tmp_path / "dem.tif"
    script.write_text(
        f'''import json, os
from pathlib import Path
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point

gpd.GeoDataFrame({{"id": ["a", "b"]}}, geometry=[Point(0, 0), Point(10, 10)], crs="EPSG:32650").to_file({str(vec_out)!r})
arr = np.array([[10.0, 20.0], [-9999.0, 30.0]], dtype=np.float32)
with rasterio.open({str(ras_out)!r}, "w", driver="GTiff", height=2, width=2, count=1, dtype="float32", crs="EPSG:32650", transform=from_origin(0, 20, 10, 10), nodata=-9999.0) as dst:
    dst.write(arr, 1)
Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(json.dumps({{"vec": {str(vec_out)!r}, "ras": {str(ras_out)!r}}}), encoding="utf-8")
''',
        encoding="utf-8",
    )
    run = run_python_script(Path(sys.executable), tmp_path / "logs", str(script))
    assert run["ok"], run
    by_path = {Path(item["path"]).name: item for item in run["outputs"]}
    vec_spatial = by_path["pts.gpkg"]["spatial"]
    ras_spatial = by_path["dem.tif"]["spatial"]
    assert vec_spatial["kind"] == "vector" and vec_spatial["crs"] == "EPSG:32650" and vec_spatial["feature_count"] == 2
    assert vec_spatial["invalid_sample_count"] == 0 and vec_spatial["empty_sample_count"] == 0
    assert ras_spatial["kind"] == "raster" and ras_spatial["crs"] == "EPSG:32650" and ras_spatial["shape"] == [2, 2]
    assert ras_spatial["nodata"] == -9999.0 and ras_spatial["valid_ratio"] == 0.75
    assert ras_spatial["raw_min"] == 10.0 and ras_spatial["raw_max"] == 30.0


def test_stratified_spatial_anomaly_detection_and_corrupt_header(tmp_path: Path) -> None:
    """空间异常分级检测：区分 L1 notice / L2 warning / L3 fatal，不误杀底层合法产出。"""
    import importlib.util

    from gis_agent.runtime.inspect_fast import attach_spatial_vitals, detect_spatial_anomalies

    # 1) 纯结构异常分类校验（零依赖路径）
    unscaled = detect_spatial_anomalies(
        {"kind": "raster", "crs": "EPSG:32650", "shape": [10, 10], "dtype": "int16", "scale": 1.0, "valid_ratio": 1.0, "raw_min": 500.0, "raw_max": 4500.0}
    )
    assert [(a["level"], a["code"]) for a in unscaled] == [("notice", "UNSCALED_HIGH_DN")]

    empty_vec = detect_spatial_anomalies({"kind": "vector", "crs": "", "feature_count": 0, "invalid_sample_count": 0, "empty_sample_count": 0})
    assert {a["code"] for a in empty_vec} == {"MISSING_CRS", "ZERO_FEATURES"}
    assert all(a["level"] == "warning" for a in empty_vec)

    partial_bad = detect_spatial_anomalies({"kind": "vector", "crs": "EPSG:4326", "feature_count": 10, "invalid_sample_count": 2, "empty_sample_count": 0})
    assert [(a["level"], a["code"]) for a in partial_bad] == [("notice", "PARTIAL_INVALID_GEOMETRY")]

    all_bad = detect_spatial_anomalies({"kind": "vector", "crs": "EPSG:4326", "feature_count": 2, "invalid_sample_count": 2, "empty_sample_count": 0})
    assert [(a["level"], a["code"]) for a in all_bad] == [("warning", "ALL_INVALID_OR_EMPTY")]

    const_dem = detect_spatial_anomalies(
        {"kind": "raster", "crs": "EPSG:32650", "shape": [5, 5], "dtype": "float32", "scale": 1.0, "valid_ratio": 1.0, "raw_min": 100.0, "raw_max": 100.0}
    )
    assert [(a["level"], a["code"]) for a in const_dem] == [("warning", "CONSTANT_RASTER_SURFACE")]

    all_nodata = detect_spatial_anomalies(
        {"kind": "raster", "crs": "EPSG:32650", "shape": [5, 5], "dtype": "float32", "scale": 1.0, "valid_ratio": 0.0, "raw_min": None, "raw_max": None}
    )
    assert [(a["level"], a["code"]) for a in all_nodata] == [("warning", "ALL_NODATA_RASTER")]

    # 2) 真实文件头损坏触发 fatal CORRUPT_OR_UNREADABLE，而非静默吞异常
    corrupt_tif = tmp_path / "broken.tif"
    corrupt_tif.write_bytes(b"NOT_A_VALID_TIFF_HEADER_1234567890")
    outputs = [{"path": str(corrupt_tif), "exists": True, "empty": False}]
    attach_spatial_vitals(outputs, Path(sys.executable))
    assert outputs[0]["spatial"]["kind"] == "corrupt"
    assert outputs[0]["anomalies"][0]["level"] == "fatal"
    assert outputs[0]["anomalies"][0]["code"] == "CORRUPT_OR_UNREADABLE"

    if importlib.util.find_spec("rasterio") is not None and importlib.util.find_spec("numpy") is not None:
        all_nan_tif = tmp_path / "empty_raster.tif"
        script = tmp_path / "make_nan_tif.py"
        script.write_text(
            f'''import numpy as np, rasterio
from rasterio.transform import from_origin
arr = np.full((4, 4), -9999.0, dtype=np.float32)
with rasterio.open({str(all_nan_tif)!r}, "w", driver="GTiff", height=4, width=4, count=1, dtype="float32", crs="EPSG:32650", transform=from_origin(0, 40, 10, 10), nodata=-9999.0) as dst:
    dst.write(arr, 1)
''',
            encoding="utf-8",
        )
        run = run_python_script(Path(sys.executable), tmp_path / "logs", str(script))
        assert run["ok"], run
        ras_item = next(item for item in run["outputs"] if Path(item["path"]).name == "empty_raster.tif")
        assert [a["code"] for a in ras_item["anomalies"]] == ["ALL_NODATA_RASTER"]


def test_run_python_script_timeout_schema_and_bounds(tmp_path: Path) -> None:
    """run_python_script 默认超时 120s、上限 600s，越界参数明确拒绝。"""
    import sys
    from gis_agent.tools.qgis_python import make_qgis_python_tools

    launcher = Path(sys.executable)
    tools = {t.name: t for t in make_qgis_python_tools(launcher, tmp_path / "logs")}
    timeout_prop = tools["run_python_script"].parameters["properties"]["timeout_sec"]
    assert timeout_prop["minimum"] == 5 and timeout_prop["maximum"] == 600
    assert "默认120" in timeout_prop["description"]
    script = tmp_path / "noop.py"
    script.write_text("print('hi')\n", encoding="utf-8")
    rejected = run_python_script(launcher, tmp_path / "logs", str(script), timeout_sec=601)
    assert not rejected["ok"] and "600" in rejected["error"]
