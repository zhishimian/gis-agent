import json
from pathlib import Path

import pytest

from gis_agent.agents.delivery import delivery_ready
from gis_agent.persistence.evidence import tool_result
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.files import read_file, write_file
from gis_agent.tools.verification import available_evidence, make_verifier_finish


@pytest.fixture
def review_record(tmp_path: Path):
    store = SessionStore(tmp_path, "review")
    data = tmp_path / "measurement.txt"
    data.write_text("实际观测值满足要求。", encoding="utf-8")
    messages = [{"role": "user", "origin": "user", "content": "检查实际成果。"}]
    for call_id, name, arguments, result, state in (
        ("good-read", "read_file", {"path": str(data)}, read_file(str(data)), "finished"),
        ("failed-read", "read_file", {"path": str(tmp_path / "missing")}, read_file(str(tmp_path / "missing")), "finished"),
        ("write", "write_file", {"path": str(tmp_path / "note"), "content": "记录"}, write_file(str(tmp_path / "note"), "记录"), "finished"),
        ("unfinished-read", "read_file", {"path": str(data)}, read_file(str(data)), "started"),
    ):
        messages.extend([
            {"role": "assistant", "content": None, "executions": {call_id: state}, "tool_calls": [{
                "id": call_id, "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }]},
            store.tool_message(call_id, name, result, 8000),
        ])
    store.save(messages)
    definitions = [{
        "check_id": "measure", "requirement": "检查实际成果", "source_indices": [0],
        "criterion": "实际观测值满足要求", "method": "读取测量结果", "coverage": "本次成果",
    }]
    finish = make_verifier_finish(messages, {0}, tmp_path / "output", store=store, initial_checks=definitions)
    return store, messages, definitions, finish


@pytest.mark.parametrize("references", [{"evidence_ids": ["good-read"]}, {"evidence_indices": [2]}])
def test_verification_accepts_ids_and_legacy_indices(review_record, references) -> None:
    store, messages, definitions, finish = review_record
    result = finish.run({
        "status": "completed", "summary": "重点检查通过。",
        "checks": [{"check_id": "measure", "status": "PASS", "finding": "实际值满足要求。", **references}],
    })
    assert result["ok"], result
    assert result["checks"][0]["evidence_indices"] == [2]
    assert delivery_ready(result, definitions)
    assert available_evidence(messages)[0]["evidence_id"] == "good-read"
    assert store.read_record() == messages


@pytest.mark.parametrize(("evidence_id", "error"), [
    ("missing", "证据 ID"),
    ("failed-read", "失败"),
    ("write", "数据读取"),
    ("unfinished-read", "尚未确认"),
])
def test_invalid_evidence_keeps_completion_blocked(review_record, evidence_id: str, error: str) -> None:
    _, _, _, finish = review_record
    result = finish.run({
        "status": "completed", "summary": "申请完成。",
        "checks": [{"check_id": "measure", "status": "PASS", "finding": "申请通过。", "evidence_ids": [evidence_id]}],
    })
    assert not result["ok"] and error in result["error"]
    assert any(item["evidence_id"] == "good-read" and item["ok"] for item in result["available_evidence"])
    assert not any(item["evidence_id"] in {"write", "unfinished-read"} for item in result["available_evidence"])


@pytest.mark.parametrize("status", ["PASS", "FAIL", "UNKNOWN"])
def test_review_projection_keeps_verdict_and_original(tmp_path: Path, status: str) -> None:
    store = SessionStore(tmp_path, "projection")
    result = {
        "ok": True, "candidate_id": "first", "ready": status == "PASS", "review_scope": "selected_risks",
        "verification": {
            "status": "completed", "task_id": "dv_first", "summary": "已核验重点。",
            "checks": [{"check_id": "measure", "status": status, "finding": "实际观察。", "coverage": "本次成果", "method": "重复说明" * 2000}],
            "evidence_files": ["日志路径" * 2000],
        },
        "definitions": [{"method": "重复定义" * 2000}],
        "issues": [] if status == "PASS" else [{"check_id": "measure", "status": status, "criterion": "原有标准", "finding": "实际问题。"}],
    }
    message = store.tool_message("review", "review_delivery", result, 8000)
    store.save([message])
    original = store.path.read_bytes()
    projected = json.loads(store.project([message], 2000)[0]["content"])
    assert projected["ready"] == result["ready"]
    assert projected["verification"]["checks"][0]["status"] == status
    assert projected["issues"] == result["issues"]
    assert "definitions" not in projected and "source" in projected
    assert len(json.dumps(projected, ensure_ascii=False)) < 2000
    assert tool_result(store, message) == result
    assert store.path.read_bytes() == original
    store.asset_path(message["asset"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="校验失败"):
        store.project([message], 2000)
