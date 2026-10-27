import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver

from gis_agent.agent import Agent
from gis_agent.persistence.json import json_text, write_json
from gis_agent.persistence.sessions import SessionStore


CreateAgent = Callable[[SessionStore, list[dict[str, Any]], Path, BaseCheckpointSaver, dict[str, Any]], Agent]


def file_versions(paths: list[str]) -> list[dict[str, str]]:
    versions = []
    for path in sorted({Path(value).expanduser().resolve() for value in paths}):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        versions.append({"path": str(path), "sha256": digest.hexdigest()})
    return versions


@dataclass
class SubtaskRunner:
    parent: SessionStore
    messages: list[dict[str, Any]]
    output_dir: Path
    create: CreateAgent
    signature: str
    role: str = "verifier"

    def directory(self, task_id: str) -> Path | None:
        if not isinstance(task_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,40}", task_id) is None:
            return None
        return self.parent.root / f"{self.parent.session_id}.subtasks" / self.role / task_id

    def run(
        self, task_id: str, goal: str, source_indices: list[int], artifacts: list[str],
    ) -> dict[str, Any]:
        directory = self.directory(task_id)
        if directory is None:
            return {"ok": False, "error": "task_id 只允许 1 到 40 个英文字母、数字、下划线或横线。"}
        if not isinstance(goal, str) or not goal.strip():
            return {"ok": False, "error": "请填写子任务目标。"}
        if not isinstance(source_indices, list) or not source_indices:
            return {"ok": False, "error": "请提供相关用户原话的消息序号。"}
        for index in source_indices:
            if type(index) is not int or not 0 <= index < len(self.messages):
                return {"ok": False, "error": "用户原话来源序号无效。"}
            item = self.messages[index]
            if item["role"] != "user" or item.get("origin") != "user":
                return {"ok": False, "error": "来源必须指向真实用户消息。"}
        latest = max(
            (i for i, item in enumerate(self.messages) if item["role"] == "user" and item.get("origin") == "user"),
            default=-1,
        )
        if latest not in source_indices:
            return {"ok": False, "error": "来源需要包含本轮最新用户输入。"}
        if not isinstance(artifacts, list) or any(not isinstance(path, str) for path in artifacts):
            return {"ok": False, "error": "artifacts 必须是实际文件路径列表。"}
        for path in artifacts:
            if not Path(path).expanduser().is_file():
                return {"ok": False, "error": f"输入文件不存在：{path}"}
        output_dir = self.output_dir / "subtasks" / self.role / task_id
        request = {
            "version": 1, "role": self.role, "task_id": task_id,
            "parent_session": self.parent.session_id, "signature": self.signature,
            "goal": goal.strip(),
            "requirements": [{"index": i, "text": self.messages[i]["content"]} for i in sorted(set(source_indices))],
            "artifacts": file_versions(artifacts), "output_dir": str(output_dir.resolve()),
        }
        request_path = directory / "request.json"
        result_path = directory / "result.json"
        store = SessionStore(directory, "run")
        if request_path.exists():
            if json.loads(request_path.read_text(encoding="utf-8")) != request:
                return {"ok": False, "error": "此 task_id 的输入或配置已变化，请使用新的 task_id。"}
        else:
            write_json(request_path, request)
        if result_path.exists():
            saved = json.loads(result_path.read_text(encoding="utf-8"))
            if hashlib.sha256(store.path.read_bytes()).hexdigest() != saved["record_hash"]:
                return {"ok": False, "error": "已完成子任务的记录发生变化，请检查记录。"}
            outputs = [item["path"] for item in saved["outputs"]]
            if any(not Path(path).is_file() for path in outputs) or file_versions(outputs) != saved["outputs"]:
                return {"ok": False, "error": "子任务产物发生变化，请重新检查。"}
            return {**saved["result"], "reused": True}
        output_dir.mkdir(parents=True, exist_ok=True)
        messages = store.read_record()
        delegated = {"role": "user", "origin": "delegation", "content": json_text(request)}
        with SqliteSaver.from_conn_string(str(directory / "checkpoints.sqlite")) as saver:
            agent = self.create(store, messages, output_dir, saver, request)
            snapshot = agent.graph.get_state(agent.options())
            if snapshot.next:
                outcome = agent.resume(messages)
            elif snapshot.values:
                agent.verify_record(snapshot.values)
                outcome = snapshot.values.get("outcome")
                if outcome is None:
                    raise ValueError("子任务检查点缺少结束状态。")
            else:
                if messages and messages != [delegated]:
                    raise ValueError("子任务已有执行记录但缺少检查点，不能自动重放。")
                if not messages:
                    messages.append(delegated)
                outcome = agent.run(messages)
        stable = all(Path(item["path"]).is_file() for item in request["artifacts"])
        stable = stable and file_versions(artifacts) == request["artifacts"]
        result = {
            **outcome, "task_id": task_id, "role": self.role,
            "session_path": str(store.path), "output_dir": str(output_dir.resolve()),
            "stale": not stable, "reused": False,
        }
        if not stable:
            result.update(ok=False, status="blocked", summary="检查期间输入发生变化，当前结论需要重新核对。")
        write_json(result_path, {
            "record_hash": hashlib.sha256(store.path.read_bytes()).hexdigest(),
            "outputs": file_versions(outcome.get("artifacts", [])), "result": result,
        })
        return result

    def read(self, task_id: str, start: int, offset: int = 0, limit: int = 4000) -> dict[str, Any]:
        directory = self.directory(task_id)
        if directory is None:
            return {"ok": False, "error": "task_id 格式无效。"}
        store = SessionStore(directory, "run")
        if not store.path.is_file():
            return {"ok": False, "error": "子任务会话记录尚未生成。"}
        return store.read_messages(start, offset, limit)
