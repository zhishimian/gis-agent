import re
from pathlib import Path
from typing import Any

from gis_agent.agents.subtasks import SubtaskRunner
from gis_agent.persistence.evidence import save_evidence, tool_evidence, tool_result
from gis_agent.persistence.sessions import SessionStore
from gis_agent.tools.base import Tool
from gis_agent.tools.planning import finish_task


DEFINITION_SCHEMA = {
    "type": "object",
    "properties": {
        "check_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,40}$"},
        "requirement": {"type": "string"},
        "source_indices": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
        "criterion": {"type": "string"}, "method": {"type": "string"}, "coverage": {"type": "string"},
    },
    "required": ["check_id", "requirement", "source_indices", "criterion", "method", "coverage"],
    "additionalProperties": False,
}
CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "check_id": {"type": "string"},
        "status": {"type": "string", "enum": ["PASS", "FAIL", "UNKNOWN"]},
        "finding": {"type": "string"},
        "evidence_indices": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["check_id", "status", "finding", "evidence_indices"],
    "additionalProperties": False,
}
MAP_NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "observation": {"type": "string"},
        "evidence_indices": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
    },
    "required": ["observation", "evidence_indices"],
    "additionalProperties": False,
}
CONTEXT_TOOLS = {"update_plan", "finish_task", "define_checks", "read_session_messages", "write_file", "search_qgis_tools", "read_image"}


def registered_checks(store: SessionStore, messages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    checks = {}
    for message in messages:
        if message["role"] == "tool" and message.get("tool_name") == "define_checks":
            result = tool_result(store, message)
            if result.get("ok"):
                checks = {item["check_id"]: item for item in result["checks"]}
    return checks


def make_check_plan_tool(store: SessionStore, messages: list[dict[str, Any]], allowed_sources: set[int]) -> Tool:
    def define(checks: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(checks, list):
            return {"ok": False, "error": "checks 必须是列表。"}
        current = registered_checks(store, messages)
        seen = set()
        for item in checks:
            if not isinstance(item, dict) or set(item) != set(DEFINITION_SCHEMA["properties"]):
                return {"ok": False, "error": "检查定义字段不完整。"}
            if any(not isinstance(item[key], str) or not item[key].strip() for key in ("check_id", "requirement", "criterion", "method", "coverage")):
                return {"ok": False, "error": "检查标识、要求、判定条件、方法和覆盖范围必须有正文。"}
            key = item["check_id"]
            if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", key) is None or key in seen:
                return {"ok": False, "error": "check_id 无效或在本批重复。"}
            sources = item["source_indices"]
            if not isinstance(sources, list) or not sources or any(type(i) is not int or i not in allowed_sources for i in sources):
                return {"ok": False, "error": "检查定义需要引用委派提供的用户来源序号。"}
            if key in current and current[key] != item:
                return {"ok": False, "error": "已有检查定义已固定，调整标准时请新建委派。"}
            current[key] = item
            seen.add(key)
        return {"ok": True, "checks": list(current.values())}

    return Tool(
        name="define_checks",
        description="登记本次检查的要求、判定条件、方法和覆盖范围。可以追加检查，已有定义保持固定；checks=[] 回读当前方案。",
        parameters={"type": "object", "properties": {"checks": {"type": "array", "items": DEFINITION_SCHEMA}}, "required": ["checks"], "additionalProperties": False},
        function=define,
    )


def make_verifier_finish(
    messages: list[dict[str, Any]], allowed_sources: set[int], output_dir: Path, *, store: SessionStore,
) -> Tool:
    def complete(
        status: str, summary: str, checks: list[dict[str, Any]], artifacts: list[str] | None = None,
        map_notes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        result = finish_task(status, summary)
        if not result["ok"]:
            return result
        if status not in {"completed", "blocked", "needs_input"}:
            return {"ok": False, "error": "验证任务请使用 completed、blocked 或 needs_input。"}
        plan = registered_checks(store, messages)
        if not isinstance(checks, list) or (status == "completed" and not plan):
            return {"ok": False, "error": "请先登记检查方案，再提交逐项结果。"}
        rows = []
        seen = set()
        records = {}
        for check in checks:
            if not isinstance(check, dict) or set(check) != set(CHECK_SCHEMA["properties"]):
                return {"ok": False, "error": "检查结果字段不完整。"}
            key = check["check_id"]
            if not isinstance(key, str) or key not in plan or key in seen:
                return {"ok": False, "error": "结果中的 check_id 未登记或重复。"}
            verdict = check["status"]
            if not isinstance(verdict, str) or verdict not in {"PASS", "FAIL", "UNKNOWN"}:
                return {"ok": False, "error": "检查状态必须是 PASS、FAIL 或 UNKNOWN。"}
            if not isinstance(check["finding"], str) or not check["finding"].strip():
                return {"ok": False, "error": "finding 需要记录观察值、比较依据或证据缺口。"}
            indices = check["evidence_indices"]
            if not isinstance(indices, list) or (verdict in {"PASS", "FAIL"} and not indices):
                return {"ok": False, "error": "PASS 和 FAIL 需要工具证据；证据不足时使用 UNKNOWN。"}
            for index in indices:
                resolved = tool_evidence(store, messages, index)
                if not resolved["ok"]:
                    return resolved
                record = resolved["record"]
                if record["tool_name"] in CONTEXT_TOOLS:
                    return {"ok": False, "error": "检查结论请引用数据读取、计算或代码检查结果。"}
                if verdict == "PASS" and isinstance(record["result"], dict) and record["result"].get("ok") is False:
                    return {"ok": False, "error": "PASS 引用了失败的工具结果，请继续取证。"}
                records[index] = record
            rows.append({**plan[key], **check})
            seen.add(key)
        remaining = sorted(set(plan) - seen)
        if status == "completed" and remaining:
            return {"ok": False, "error": "还有已登记检查未回报。", "remaining_check_ids": remaining}
        if map_notes is None:
            map_notes = []
        if not isinstance(map_notes, list):
            return {"ok": False, "error": "map_notes 必须是列表。"}
        for note in map_notes:
            if not isinstance(note, dict) or set(note) != set(MAP_NOTE_SCHEMA["properties"]):
                return {"ok": False, "error": "地图备注字段无效。"}
            if not isinstance(note["observation"], str) or not note["observation"].strip():
                return {"ok": False, "error": "地图备注需要实际观察内容。"}
            if not isinstance(note["evidence_indices"], list) or not note["evidence_indices"]:
                return {"ok": False, "error": "地图备注需要实际图片引用。"}
            for index in note["evidence_indices"]:
                resolved = tool_evidence(store, messages, index)
                if not resolved["ok"]:
                    return resolved
                record = resolved["record"]
                if record["tool_name"] != "read_image" or not isinstance(record["result"], dict) or record["result"].get("ok") is not True or not record["files"]:
                    return {"ok": False, "error": "地图备注请引用成功读取的图片。"}
                records[index] = record
        if artifacts is None:
            artifacts = []
        if not isinstance(artifacts, list) or any(not isinstance(path, str) for path in artifacts):
            return {"ok": False, "error": "artifacts 必须是文件路径列表。"}
        paths = [Path(path).expanduser().resolve() for path in artifacts]
        if any(not path.is_file() or not path.is_relative_to(output_dir.resolve()) for path in paths):
            return {"ok": False, "error": "检查产物必须位于当前子任务输出目录。"}
        refs = [save_evidence(output_dir, record) for _, record in sorted(records.items())]
        files = {ref["path"] for ref in refs}
        files.update(item["path"] for record in records.values() for item in record["files"])
        return {
            **result, "checks": rows, "remaining_check_ids": remaining, "map_notes": map_notes,
            "artifacts": [str(path) for path in paths], "evidence": refs, "evidence_files": sorted(files),
        }

    return Tool(
        name="finish_task",
        description="结束本次复核并逐项返回已登记检查。completed 表示复核结束；地图简要观察填写可选 map_notes。必须单独调用。",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["completed", "blocked", "needs_input"]},
                "summary": {"type": "string"},
                "checks": {"type": "array", "items": CHECK_SCHEMA},
                "artifacts": {"type": "array", "items": {"type": "string"}},
                "map_notes": {"type": "array", "items": MAP_NOTE_SCHEMA},
            },
            "required": ["status", "summary", "checks"], "additionalProperties": False,
        },
        function=complete,
    )


def make_verification_tools(runner: SubtaskRunner) -> list[Tool]:
    return [
        Tool(
            name="verify_task",
            description=(
                "委派独立验证 Agent，制定检查方案或复核已有成果，返回检查项与记录位置。"
                "source_indices 提供相关用户原话，包含最新输入；artifacts 提供原始数据、成果和相关分析脚本的实际文件路径，"
                "Shapefile 同时提供 shp、shx、dbf、prj 等组成文件。输入变化时使用新的 task_id。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,40}$"},
                    "goal": {"type": "string"},
                    "source_indices": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
                    "artifacts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["task_id", "goal", "source_indices", "artifacts"],
                "additionalProperties": False,
            },
            function=runner.run,
        ),
        Tool(
            name="read_verification",
            description="分段读取当前主会话所属验证子任务的原始消息，按检查结果中的证据序号回读。",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,40}$"},
                    "start": {"type": "integer", "minimum": 0},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8000},
                },
                "required": ["task_id", "start"],
                "additionalProperties": False,
            },
            function=runner.read,
        ),
    ]
