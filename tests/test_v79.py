import hashlib
import json
from pathlib import Path

import httpx
import pytest
from openai import OpenAI

from gis_agent import application
from gis_agent.config import AppConfig, QGISConfig
from gis_agent.core.auxiliary import AuxiliaryCalls
from gis_agent.core.context import ContextConfig, ContextManager
from gis_agent.core.model import ModelConfig, ModelReply
from gis_agent.integrations.llm import chat, make_token_counter
from gis_agent.integrations.qgis.adapter import load_qgis_tool
from gis_agent.integrations.qgis.catalog import load_catalog, search_catalog
from gis_agent.integrations.qgis.client import QGISClient
from gis_agent.persistence.evidence import tool_result
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.base import Tool
from gis_agent.tools.files import edit_file, list_files, read_file, search_text
from gis_agent.tools.planning import finish_task
from gis_agent.tools.qgis_python import inspect_data, run_data_check, run_python_script
from gis_agent.tools.registry import ToolRegistry


ROOT = Path(__file__).resolve().parents[1]


def response(number: int, name: str, arguments: dict) -> ModelReply:
    return ModelReply({"role": "assistant", "content": None, "tool_calls": [{
        "id": f"call-{number}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }]}, "offline", None, "tool_calls")


def geojson(path: Path, features: list[tuple[dict, dict]]) -> Path:
    path.write_text(json.dumps({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
        "features": [{"type": "Feature", "properties": properties, "geometry": geometry} for properties, geometry in features]}), encoding="utf-8")
    return path


def polygon(x: int) -> dict:
    return {"type": "Polygon", "coordinates": [[[x, 0], [x + 10, 0], [x + 10, 10], [x, 10], [x, 0]]]}


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


def test_finish_paths_and_unknown_work_are_checked(tmp_path: Path) -> None:
    assert finish_task("completed", "已完成", [str(tmp_path)])["ok"]
    assert not finish_task("completed", "已完成", [str(tmp_path / "missing")])["ok"]
    assert not finish_task("completed", "已完成", unresolved=["结果单位尚不明确"])["ok"]
    assert finish_task("blocked", "需要确认单位", unresolved=["单位未确认"])["ok"]
    assert not finish_task("completed", "完成", artifacts={})["ok"]
    assert not finish_task("completed", "完成", unresolved={})["ok"]


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


def test_single_agent_buffer_can_finish_and_read_only_question_can_answer(qgis_dir: Path, tmp_path: Path, monkeypatch) -> None:
    source = geojson(tmp_path / "point.geojson", [({"id": 1}, {"type": "Point", "coordinates": [0, 0]})])
    config = AppConfig(tmp_path, tmp_path / "sessions", tmp_path / "outputs",
                       QGISConfig(qgis_dir / "bin/qgis_process-qgis-ltr.bat", qgis_dir / "bin/python-qgis-ltr.bat"),
                       ModelConfig(tokenizer="bytes"), ContextConfig(), None, api_key_env="GIS_AGENT_TEST_KEY")
    monkeypatch.setenv(config.api_key_env, "offline")
    output = config.output_root / "single" / "buffer.gpkg"
    steps = iter([
        ("search_qgis_tools", {"query": "native:buffer", "limit": 1}),
        ("qgis_native_buffer", {"INPUT": str(source), "DISTANCE": 500, "SEGMENTS": 32, "OUTPUT": str(output)}),
        ("summarize_fields", {"source": str(output), "fields": ["id"], "check_geometry": True}),
        ("finish_task", {"status": "completed", "summary": "成果可读，已检查几何。", "artifacts": [str(output)]}),
    ])
    calls = []
    def fixed(client, model, view, schemas):
        names = {item["function"]["name"] for item in schemas}
        assert not {"verify_task", "review_delivery", "cartograph_task", "render_map"} & names
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
        saved = conversation.agent.store.load()
        check = next(tool_result(conversation.agent.store, item) for item in saved if item.get("tool_name") == "summarize_fields")
        assert check["ok"] and check["result"]["geometry"] == {"empty": 0, "invalid": 0}
        assert conversation.agent.graph.get_state(conversation.agent.options()).values["responses_used"] == 4
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    steps = iter([("read_file", {"path": str(ROOT / "gis_agent/skills/gis-verification/SKILL.md")}),
                  ("finish_task", {"status": "answer", "summary": "已读取核查方法。"})])
    with application.open_conversation(config, "single") as conversation:
        assert conversation.send("解释一下核查方法。 ")["status"] == "answer"


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
