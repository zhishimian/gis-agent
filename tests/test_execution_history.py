import json
from pathlib import Path

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
