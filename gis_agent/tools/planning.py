from functools import partial
from pathlib import Path
from typing import Any

from gis_agent.core.planning import Plan, STEP_STATUSES
from gis_agent.runtime.runner import snapshot_files
from gis_agent.tools.base import Tool


FINISH_STATUSES = ("completed", "partial", "needs_input", "blocked", "cancelled", "answer")
CHECKPOINT_KINDS = ("clarification", "plan_approval", "cartography_review", "parameter_tuning")


def _validate_options(options: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]] | None, str | None]:
    if options is None:
        return None, None
    if not isinstance(options, list) or not options:
        return None, "options 必须是非空对象列表。"
    cleaned: list[dict[str, Any]] = []
    for item in options:
        if not isinstance(item, dict):
            return None, "options 中每项必须是对象。"
        opt_id = item.get("id")
        label = item.get("label")
        if not isinstance(opt_id, str) or not opt_id.strip() or not isinstance(label, str) or not label.strip():
            return None, "options 每项必须提供非空字符串 id 与 label。"
        entry: dict[str, Any] = {"id": opt_id.strip(), "label": label.strip()}
        desc = item.get("description")
        if isinstance(desc, str) and desc.strip():
            entry["description"] = desc.strip()
        if item.get("recommended") is True:
            entry["recommended"] = True
        cleaned.append(entry)
    return cleaned, None


def finish_task(
    status: str,
    summary: str,
    artifacts: list[str] | None = None,
    unresolved: list[str] | None = None,
    question: str | None = None,
    reason: str | None = None,
    acknowledged_anomalies: list[str] | None = None,
    evidence: list[str] | None = None,
    checkpoint_kind: str | None = None,
    options: list[dict[str, Any]] | None = None,
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if status not in FINISH_STATUSES:
        return {"ok": False, "error": "结束状态无效。"}
    if not isinstance(summary, str) or not summary.strip():
        return {"ok": False, "error": "必须提供交付说明或停止原因。"}
    if artifacts is not None and (not isinstance(artifacts, list) or any(not isinstance(path, str) for path in artifacts)):
        return {"ok": False, "error": "artifacts 需要填写实际文件或数据集目录的绝对路径。"}
    if unresolved is not None and (not isinstance(unresolved, list) or any(not isinstance(item, str) for item in unresolved)):
        return {"ok": False, "error": "unresolved 需要填写未完成或无法确认的事项列表。"}
    if acknowledged_anomalies is not None and (
        not isinstance(acknowledged_anomalies, list) or any(not isinstance(item, str) for item in acknowledged_anomalies)
    ):
        return {"ok": False, "error": "acknowledged_anomalies 需要填写已核实确认的异常编码字符串列表。"}
    if evidence is not None and (not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence)):
        return {"ok": False, "error": "evidence 需要填写关键取证结论字符串列表。"}
    missing = [path for path in artifacts or [] if not Path(path).is_absolute() or not Path(path).exists()]
    if missing:
        return {"ok": False, "error": "成果路径不存在或未使用绝对路径。", "paths": missing}
    empty_files = [
        path for path in artifacts or []
        if Path(path).is_file() and Path(path).stat().st_size == 0
    ]
    if empty_files and status == "completed":
        return {"ok": False, "error": "成果文件为空（0字节），请检查写出逻辑。", "paths": empty_files}
    if status == "completed" and unresolved:
        return {
            "ok": False,
            "error": "unresolved非空，不能completed。请处理尚未满足的要求，或用partial/blocked/needs_input结束；正常近似和格式说明写summary。",
            "unresolved": unresolved,
        }
    reasons = {"missing_input", "business_decision", "data_quality", "unsupported", "capability_limit"}
    if reason is not None and reason not in reasons:
        return {"ok": False, "error": "reason类型无效。"}
    if question is not None and (status != "needs_input" or not isinstance(question, str) or not question.strip()):
        return {"ok": False, "error": "question仅用于needs_input，且必须为明确的非空问题。"}
    if status == "needs_input" and not question:
        return {"ok": False, "error": "需要question说明缺少的必要信息、为什么需要及用户可以提供什么。"}
    if status == "partial" and not unresolved:
        return {"ok": False, "error": "partial需列尚未完成的unresolved；summary说明已完成部分，有文件成果时列artifacts。"}
    if checkpoint_kind is not None:
        if status != "needs_input" or checkpoint_kind not in CHECKPOINT_KINDS:
            return {"ok": False, "error": "checkpoint_kind 仅用于 needs_input，且须为有效的检查点类型。"}
    if options is not None and status != "needs_input":
        return {"ok": False, "error": "options 仅用于 needs_input 检查点。"}
    cleaned_options, opt_err = _validate_options(options)
    if opt_err is not None:
        return {"ok": False, "error": opt_err}

    result: dict[str, Any] = {
        "ok": True,
        "status": status,
        "summary": summary.strip(),
        "artifacts": list(dict.fromkeys(artifacts or [])),
        "unresolved": unresolved or [],
    }
    if question:
        result["question"] = question.strip()
    if reason:
        result["reason"] = reason
    if checkpoint_kind:
        result["checkpoint_kind"] = checkpoint_kind
    if cleaned_options:
        result["options"] = cleaned_options
    if acknowledged_anomalies:
        result["acknowledged_anomalies"] = list(dict.fromkeys(item.strip() for item in acknowledged_anomalies if item.strip()))
    if evidence:
        result["evidence"] = list(dict.fromkeys(item.strip() for item in evidence if item.strip()))
    if output_dir is not None and output_dir.is_dir():
        files = snapshot_files((output_dir,), max_entries=200)
        result["workspace_files"] = [
            {"path": path, "bytes": size}
            for path, (_, size) in sorted(files.items())[:50]
        ]
    return result


def make_planning_tools(plan: Plan, output_dir: Path | None = None) -> list[Tool]:
    return [
        Tool(
            name="update_plan",
            description=(
                "设置或更新当前任务的完整计划。goal 记录用户目标，steps 整表替换。"
                "继续任务时保留已完成项，新任务应更换目标和清单。"
                "简单单项操作直接执行；多个独立目标或较长分析链再列计划，包含复核与交付。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {"type": "string", "enum": list(STEP_STATUSES)},
                            },
                            "required": ["content", "status"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["goal", "steps"],
                "additionalProperties": False,
            },
            function=plan.update,
        ),
        Tool(
            name="finish_task",
            description=(
                "报告本轮结束状态和面向用户的说明，必须单独调用。"
                "completed 表示所需工作已完成，artifacts 列出实际非空文件或数据集目录；核心分析数据完整而仅缺次要辅助底图或需标准单位折算时，应直接完成并披露限制，避免误拒。"
                "若交付产物触发空间告警信号，需先修复或经核实后在 acknowledged_anomalies 中确认。"
                "unresolved只列影响用户要求成立的未完成或未知事项，存在时使用partial/blocked/needs_input。"
                "正常数值近似、图层命名和格式说明写summary；实际执行失败需解决或如实停止。"
                "needs_input是任务前/中期的联合决策与澄清检查点（而非失败收尾）：当首轮数据探测发现局部代理、粒度错配或关键业务口径分歧时，优先在编写重型脚本前调用needs_input，以question给出本地数据现状、核心缺口与供用户选择的选项，等待原Session无缝续跑；reason说明数据缺失/业务选择/质量/不支持/能力限制。"
                "partial保留已有成果并列unresolved；blocked用于核心主体彻底缺失且无有效替代切入点（可在仅完成只读探查确认缺失前提后零写入直接诚实上报）；用户取消由客户端处理。普通代码错误先自主修复。"
                "answer 用于普通问答，可先读取资料；本轮已写入或计算成果时报告任务状态。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": [s for s in FINISH_STATUSES if s != "cancelled"]},
                    "summary": {"type": "string", "description": "简短成果、实际核查范围和正常限制。"},
                    "question": {"type": "string", "description": "needs_input必填：本地已核对事实、核心缺口/潜在偏差及供用户拍板的明确选项（如补充数据或确认局部替代口径）。"},
                    "reason": {"type": "string", "enum": ["missing_input", "business_decision", "data_quality", "unsupported", "capability_limit"]},
                    "artifacts": {"type": "array", "items": {"type": "string"}},
                    "unresolved": {"type": "array", "items": {"type": "string"}, "description": "尚未满足或无法确认的用户要求。非空时不能completed。"},
                    "acknowledged_anomalies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "当交付文件带有预期内的空间告警信号（如 ZERO_FEATURES、MISSING_CRS）时，填入已核实确认的异常编码。",
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选：简短客观取证结论或数据诊断摘要（如守恒差值、缺失图层名）。",
                    },
                    "checkpoint_kind": {
                        "type": "string",
                        "enum": list(CHECKPOINT_KINDS),
                        "description": "needs_input可选类型：clarification / plan_approval / cartography_review / parameter_tuning。",
                    },
                    "options": {
                        "type": "array",
                        "description": "needs_input可选结构化选项卡片（每项含id、label，可选description、recommended）。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "label": {"type": "string"},
                                "description": {"type": "string"},
                                "recommended": {"type": "boolean"},
                            },
                            "required": ["id", "label"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["status", "summary"],
                "additionalProperties": False,
            },
            function=partial(finish_task, output_dir=output_dir),
        ),
    ]
