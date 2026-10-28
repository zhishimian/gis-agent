import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gis_agent.agents.subtasks import SubtaskRunner, file_versions
from gis_agent.persistence.evidence import file_digest, tool_result
from gis_agent.persistence.json import write_json
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.verification import registered_checks


def delivery_issues(result: dict[str, Any], definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = {item["check_id"]: item for item in result.get("checks", [])}
    return [
        {**item, "status": rows.get(item["check_id"], {}).get("status", "UNKNOWN"),
         "finding": rows.get(item["check_id"], {}).get("finding", "此项尚未回报。")}
        for item in definitions
        if rows.get(item["check_id"], {}).get("status") != "PASS"
    ]


def delivery_ready(result: dict[str, Any], definitions: list[dict[str, Any]]) -> bool:
    rows = result.get("checks", [])
    return (
        result.get("ok") is True and result.get("status") == "completed"
        and not result.get("stale") and bool(definitions)
        and not result.get("remaining_check_ids")
        and len(rows) == len(definitions)
        and {item["check_id"] for item in rows} == {item["check_id"] for item in definitions}
        and all(item["status"] == "PASS" and item["evidence_indices"] for item in rows)
    )


@dataclass
class DeliveryReview:
    runner: SubtaskRunner

    def directory(self, candidate_id: str) -> Path | None:
        if not isinstance(candidate_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,32}", candidate_id) is None:
            return None
        return self.runner.parent.root / f"{self.runner.parent.session_id}.deliveries" / candidate_id

    def records(self, start: int = 0) -> list[dict[str, Any]]:
        records = []
        calls = {
            call["id"]
            for message in self.runner.messages[start:] if message["role"] == "assistant"
            for call in message.get("tool_calls", [])
            if call["function"]["name"] == "review_delivery"
            and message.get("executions", {}).get(call["id"]) == "finished"
        }
        for message in self.runner.messages[start:]:
            if message["role"] == "tool" and message["tool_call_id"] in calls:
                result = tool_result(self.runner.parent, message)
                if result.get("ok") and "request_sha256" in result:
                    records.append(result)
        return records

    def review(
        self, candidate_id: str, goal: str, source_indices: list[int], inputs: list[str],
        deliverables: list[str], previous_id: str | None = None,
        repairs: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        directory = self.directory(candidate_id)
        if directory is None:
            return {"ok": False, "error": "candidate_id 只允许 1 到 32 个英文字母、数字、下划线或横线。"}
        if not isinstance(goal, str) or not goal.strip():
            return {"ok": False, "error": "请填写本次交付的复核目标。"}
        messages = self.runner.messages
        latest = max(i for i, item in enumerate(messages) if item["role"] == "user" and item.get("origin") == "user")
        if not isinstance(source_indices, list) or not source_indices or any(
            type(i) is not int or not 0 <= i < len(messages)
            or messages[i]["role"] != "user" or messages[i].get("origin") != "user" for i in source_indices
        ) or latest not in source_indices:
            return {"ok": False, "error": "source_indices 需要引用真实用户要求，并包含本轮最新输入。"}
        for paths in (inputs, deliverables):
            if not isinstance(paths, list) or any(not isinstance(path, str) or not Path(path).expanduser().is_file() for path in paths):
                return {"ok": False, "error": "inputs 和 deliverables 需要填写存在的文件路径。"}
        root = (self.runner.output_dir / "candidates" / candidate_id).resolve()
        if not deliverables or any(not Path(path).expanduser().resolve().is_relative_to(root) for path in deliverables):
            return {"ok": False, "error": f"待交付文件需要位于本候选目录：{root}"}
        if {Path(path).expanduser().resolve() for path in inputs} & {Path(path).expanduser().resolve() for path in deliverables}:
            return {"ok": False, "error": "同一文件请只在 inputs 或 deliverables 中登记一次。"}
        records = self.records(latest)
        current = records[-1] if records else None
        if current is not None and current["candidate_id"] != candidate_id and previous_id != current["candidate_id"]:
            return {"ok": False, "error": "新候选需要用 previous_id 关联本轮上一候选。"}
        if previous_id == candidate_id:
            return {"ok": False, "error": "候选不能引用自身作为上一版。"}
        previous = next((item for item in reversed(self.records()) if item["candidate_id"] == previous_id), None)
        if previous_id is not None and previous is None:
            return {"ok": False, "error": "previous_id 没有对应的已登记候选。"}
        unresolved = {item["check_id"] for item in previous["issues"]} if previous is not None else set()
        definitions = [
            item for item in previous["definitions"] if item["check_id"] in unresolved
        ] if previous is not None else []
        if any(not set(item["source_indices"]).issubset(source_indices) for item in definitions):
            return {"ok": False, "error": "修正版需要继续提供既有检查引用的用户原话。"}
        repairs = [] if repairs is None else repairs
        ids = {item["check_id"] for item in definitions}
        if not isinstance(repairs, list) or any(
            not isinstance(item, dict) or set(item) != {"check_id", "action"}
            or not isinstance(item["check_id"], str) or item["check_id"] not in ids
            or not isinstance(item["action"], str) or not item["action"].strip() for item in repairs
        ) or len({item["check_id"] for item in repairs}) != len(repairs):
            return {"ok": False, "error": "repairs 每项填写一个已有 check_id 和非空 action，ID 保持唯一。"}
        if not unresolved.issubset({item["check_id"] for item in repairs}):
            return {"ok": False, "error": "请逐项说明上一版未解决问题的修正或补充取证方式。"}
        old = None
        if previous is not None:
            old_path = self.directory(previous_id) / "request.json"
            if not old_path.is_file() or file_digest(old_path) != previous["request_sha256"]:
                return {"ok": False, "error": "上一候选的登记记录发生变化，请检查记录。"}
            old = json.loads(old_path.read_text(encoding="utf-8"))
        request = {
            "version": 1, "candidate_id": candidate_id, "turn_start": latest,
            "goal": goal.strip(), "source_indices": sorted(set(source_indices)),
            "inputs": file_versions(inputs), "deliverables": file_versions(deliverables),
            "previous_id": previous_id, "repairs": repairs, "checks": definitions,
        }
        request_path = directory / "request.json"
        if request_path.exists():
            if json.loads(request_path.read_text(encoding="utf-8")) != request:
                return {"ok": False, "error": "此 candidate_id 的内容或要求已变化，请生成新的候选版本。"}
        else:
            write_json(request_path, request)
        task_id = f"dv_{candidate_id}"
        verification = self.runner.run(
            task_id, goal, source_indices, [*inputs, *deliverables], checks=definitions, repairs=repairs,
        )
        child = SessionStore(self.runner.directory(task_id), "run")
        definitions = list(registered_checks(child, child.read_record(), definitions).values())
        changed = [item["path"] for item in request["deliverables"]]
        if old is not None:
            old_root = (self.runner.output_dir / "candidates" / previous_id).resolve()
            old_files = {str(Path(item["path"]).relative_to(old_root)): item["sha256"] for item in old["deliverables"]}
            changed = [
                item["path"] for item in request["deliverables"]
                if old_files.get(str(Path(item["path"]).relative_to(root))) != item["sha256"]
            ]
        issues = delivery_issues(verification, definitions)
        return {
            "ok": True, "candidate_id": candidate_id, "turn_start": latest,
            "review_scope": "selected_risks",
            "request_path": str(request_path.resolve()), "request_sha256": file_digest(request_path),
            "verification": verification, "definitions": definitions, "issues": issues,
            "ready": delivery_ready(verification, definitions), "changed_files": changed,
            "resolved_check_ids": sorted(unresolved - {item["check_id"] for item in issues}),
        }

    def read(self, candidate_id: str) -> dict[str, Any]:
        directory = self.directory(candidate_id)
        saved = next((item for item in reversed(self.records()) if item["candidate_id"] == candidate_id), None)
        if directory is None or saved is None:
            return {"ok": False, "error": "候选尚未完成登记，请检查原调用和恢复状态。"}
        path = directory / "request.json"
        if not path.is_file() or file_digest(path) != saved["request_sha256"]:
            return {"ok": False, "error": "候选登记记录已缺失或变化。"}
        request = json.loads(path.read_text(encoding="utf-8"))
        versions = [*request["inputs"], *request["deliverables"]]
        paths = [item["path"] for item in versions]
        if any(not Path(value).is_file() for value in paths):
            return {"ok": False, "error": "候选输入或交付文件缺失，需要重新复核。"}
        if file_versions(paths) != sorted(versions, key=lambda item: Path(item["path"])):
            return {"ok": False, "error": "候选输入或交付文件已变化，需要新版本复核。"}
        current = self.runner.read_result(f"dv_{candidate_id}")
        if not current.get("ok"):
            return current
        if {key: value for key, value in current.items() if key != "reused"} != {
            key: value for key, value in saved["verification"].items() if key != "reused"
        }:
            return {"ok": False, "error": "验证结果与父会话登记内容不一致。"}
        for ref in current.get("evidence", []):
            proof = Path(ref["path"])
            if not proof.is_file() or file_digest(proof) != ref["sha256"]:
                return {"ok": False, "error": "验证证据快照已缺失或变化。"}
            for item in json.loads(proof.read_text(encoding="utf-8"))["files"]:
                target = Path(item["path"])
                if not target.is_file() or file_digest(target) != item["sha256"]:
                    return {"ok": False, "error": f"验证证据文件已缺失或变化：{target}"}
        return {**saved, "ready": delivery_ready(current, saved["definitions"])}

    def check(self, turn_start: int) -> dict[str, Any]:
        for message in reversed(self.runner.messages[turn_start:]):
            if message["role"] != "assistant":
                continue
            call = next((
                item for item in reversed(message.get("tool_calls", []))
                if item["function"]["name"] == "review_delivery"
                and item["id"] in message.get("executions", {})
            ), None)
            if call is not None:
                stored = next((
                    item for item in reversed(self.runner.messages)
                    if item["role"] == "tool" and item["tool_call_id"] == call["id"]
                ), None)
                if message["executions"][call["id"]] != "finished" or stored is None:
                    return {"ok": False, "error": "最近一次交付复核尚未确认完成，请检查恢复状态。"}
                submitted = tool_result(self.runner.parent, stored)
                if not submitted.get("ok") or "request_sha256" not in submitted:
                    return {"ok": False, "error": "最近一次交付复核未成功登记，请先处理该调用的问题。"}
                candidate_id = json.loads(call["function"]["arguments"]).get("candidate_id")
                result = self.read(candidate_id)
                if not result.get("ok"):
                    return result
                if result["turn_start"] != turn_start:
                    return {"ok": False, "error": "此候选没有覆盖本轮用户要求，请重新提交复核。"}
                if not result["ready"]:
                    return {"ok": False, "error": "当前候选还有未解决的重点检查或复核阻碍。", "issues": result["issues"]}
                request = json.loads(Path(result["request_path"]).read_text(encoding="utf-8"))
                return {
                    "ok": True,
                    "delivery": {
                        "candidate_id": candidate_id, "request_path": result["request_path"],
                        "request_sha256": result["request_sha256"],
                        "verification_task_id": f"dv_{candidate_id}",
                        "review_scope": "selected_risks",
                        "review_summary": result["verification"]["summary"],
                        "checks": result["verification"]["checks"],
                        "map_notes": result["verification"].get("map_notes", []),
                    },
                    "artifacts": [item["path"] for item in request["deliverables"]],
                }
        return {"ok": False, "error": "请先用 review_delivery 复核本轮候选成果。"}
