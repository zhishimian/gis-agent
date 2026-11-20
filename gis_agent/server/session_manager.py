"""Session management, worker execution queue, SSE broadcast bus, and HIL WorkspaceContext binding."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import queue
from threading import Event, RLock, Thread
import time
from typing import Any, Callable
from uuid import uuid4

from gis_agent.adapters.stubs import ExecutionPolicy, WorkspaceContext
from gis_agent.application import open_conversation
from gis_agent.config import AppConfig
from gis_agent.core.events import AgentEvent
from gis_agent.core.planning import Plan
from gis_agent.persistence.executions import ExecutionHistory
from gis_agent.persistence.interaction import latest_outcome
from gis_agent.persistence.sessions import SessionStore, folder_sessions
from gis_agent.server.figure_service import FigureService
from gis_agent.server.workspace_service import WorkspaceService

AOI_INLINE_LIMIT_BYTES = 2048


def _calls_path(store: SessionStore) -> Path:
    return store.root / f"{store.session_id}.calls.jsonl"


def _read_record_safe(store: SessionStore) -> list[dict[str, Any]]:
    """Read session messages safely across concurrent Windows atomic file replacements."""
    for delay in (0.02, 0.04, 0.08, 0.12, 0.16, 0.0):
        try:
            return store.read_record()
        except (PermissionError, FileNotFoundError, json.JSONDecodeError):
            if delay == 0.0:
                raise
            time.sleep(delay)
    return []


def _estimate_usage_from_calls(calls_path: Path) -> dict[str, Any]:
    if not calls_path.is_file():
        return {
            "calls": 0,
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "completion_tokens": 0,
            "cache_hit_ratio": 0.0,
            "estimated_cny": 0.0,
        }
    prompt_total = 0
    cached_total = 0
    completion_total = 0
    calls = 0
    for line in calls_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        calls += 1
        usage = row.get("usage") or {}
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        ch = usage.get("prompt_cache_hit_tokens")
        if ch is None:
            ch = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        prompt_total += pt
        cached_total += int(ch or 0)
        completion_total += ct
    uncached = max(0, prompt_total - cached_total)
    # Standard DeepSeek off-peak baseline estimate (0.02 hit / 1.00 miss / 4.00 out CNY per 1M)
    est_cny = (cached_total * 0.02 + uncached * 1.0 + completion_total * 4.0) / 1_000_000.0
    ratio = (cached_total / prompt_total) if prompt_total > 0 else 0.0
    return {
        "calls": calls,
        "prompt_tokens": prompt_total,
        "cached_tokens": cached_total,
        "completion_tokens": completion_total,
        "cache_hit_ratio": round(ratio, 4),
        "estimated_cny": round(est_cny, 4),
    }


@dataclass
class _SessionRuntime:
    session_id: str
    lock: RLock = field(default_factory=RLock)
    busy: bool = False
    cancel_event: Event | None = None
    subscribers: set[queue.Queue[dict[str, Any]]] = field(default_factory=set)
    event_seq: int = 0


class SessionManager:
    """Thread-safe coordinator binding Ring 2 headless Conversations to Ring 3 HTTP/SSE clients."""

    def __init__(
        self,
        workspace: WorkspaceService,
        figures: FigureService,
        *,
        conversation_factory: Callable[..., Any] = open_conversation,
    ) -> None:
        self.workspace = workspace
        self.figures = figures
        self.conversation_factory = conversation_factory
        self._lock = RLock()
        self._sessions: dict[str, _SessionRuntime] = {}

    def _runtime(self, session_id: str) -> _SessionRuntime:
        with self._lock:
            rt = self._sessions.get(session_id)
            if rt is None:
                rt = _SessionRuntime(session_id=session_id)
                self._sessions[session_id] = rt
            return rt

    def _publish_sse(self, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        rt = self._runtime(session_id)
        with rt.lock:
            rt.event_seq += 1
            msg = {"id": rt.event_seq, "type": event_type, "session_id": session_id, "payload": payload}
            dead: list[queue.Queue[dict[str, Any]]] = []
            for q in rt.subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                rt.subscribers.discard(q)

    def subscribe(self, session_id: str) -> tuple[_SessionRuntime, queue.Queue[dict[str, Any]]]:
        rt = self._runtime(session_id)
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=500)
        with rt.lock:
            rt.subscribers.add(q)
        return rt, q

    def unsubscribe(self, session_id: str, q: queue.Queue[dict[str, Any]]) -> None:
        rt = self._runtime(session_id)
        with rt.lock:
            rt.subscribers.discard(q)

    def list_sessions(self) -> list[dict[str, Any]]:
        cfg = self.workspace.load_config()
        cfg.session_root.mkdir(parents=True, exist_ok=True)
        items: list[dict[str, Any]] = []
        for sid in folder_sessions(cfg.session_root):
            store = SessionStore(cfg.session_root, sid)
            rt = self._runtime(sid)
            messages = _read_record_safe(store)
            outcome = latest_outcome(store, messages) if messages else None
            usage = _estimate_usage_from_calls(_calls_path(store))
            items.append({
                "session_id": sid,
                "busy": rt.busy,
                "waiting": bool(outcome and outcome.get("status") == "needs_input"),
                "status": outcome.get("status") if outcome else ("empty" if not messages else "idle"),
                "message_count": len(messages),
                "usage": usage,
                "mtime_ns": store.path.stat().st_mtime_ns if store.path.exists() else 0,
            })
        return items

    def create_session(self, session_id: str | None = None) -> dict[str, Any]:
        cfg = self.workspace.load_config()
        cfg.session_root.mkdir(parents=True, exist_ok=True)
        sid = (session_id or uuid4().hex[:12]).strip()
        store = SessionStore(cfg.session_root, sid)
        store.create()
        (cfg.output_root / sid).mkdir(parents=True, exist_ok=True)
        return {"session_id": sid, "output_dir": str((cfg.output_root / sid).resolve())}

    def get_session_detail(self, session_id: str) -> dict[str, Any]:
        cfg = self.workspace.load_config()
        store = SessionStore(cfg.session_root, session_id)
        messages = _read_record_safe(store)
        plan = Plan.from_messages(messages)
        waiting = latest_outcome(store, messages) if messages else None
        if waiting and waiting.get("status") != "needs_input":
            waiting = None
        output_dir = cfg.output_root / session_id
        history_rows = ExecutionHistory(store, output_dir).rows() if messages else []
        rt = self._runtime(session_id)
        usage = _estimate_usage_from_calls(_calls_path(store))
        figures = self.figures.list_figures(output_dir)

        discovered_layers: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for row in history_rows:
            for out in row.get("outputs") or []:
                p = out.get("path") if isinstance(out, dict) else None
                if isinstance(p, str) and p not in seen_paths and Path(p).exists():
                    kind = self.workspace._classify_path(Path(p))
                    if kind in {"vector", "raster"}:
                        seen_paths.add(p)
                        discovered_layers.append({"path": p, "name": Path(p).name, "kind": kind})

        return {
            "session_id": session_id,
            "busy": rt.busy,
            "output_dir": str(output_dir.resolve()),
            "plan": plan.snapshot(),
            "waiting": waiting,
            "messages": messages,
            "executions": history_rows,
            "figures": figures,
            "layers": discovered_layers,
            "usage": usage,
        }

    def get_executions(self, session_id: str, execution_id: str | None = None, section: str = "summary") -> dict[str, Any]:
        cfg = self.workspace.load_config()
        store = SessionStore(cfg.session_root, session_id)
        output_dir = cfg.output_root / session_id
        history = ExecutionHistory(store, output_dir)
        if execution_id:
            return history.query(execution_id=execution_id, section=section, max_characters=32000)
        return {"ok": True, "items": history.rows()}

    def _build_workspace_context(
        self,
        raw: dict[str, Any] | None,
        output_dir: Path,
    ) -> WorkspaceContext | None:
        if not raw:
            return None
        drawn_geom = raw.get("drawn_geometry_geojson")
        drawn_bbox = raw.get("drawn_bbox_wgs84")
        if isinstance(drawn_geom, dict):
            serialized = json.dumps(drawn_geom, ensure_ascii=False)
            if len(serialized.encode("utf-8")) > AOI_INLINE_LIMIT_BYTES:
                output_dir.mkdir(parents=True, exist_ok=True)
                aoi_path = (output_dir / "_user_aoi.geojson").resolve()
                fc = (
                    drawn_geom
                    if drawn_geom.get("type") == "FeatureCollection"
                    else {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": drawn_geom}]}
                )
                aoi_path.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
                coords = drawn_geom.get("coordinates")
                vcount = str(coords).count("[")
                drawn_geom = {
                    "aoi_file": str(aoi_path),
                    "bbox_wgs84": drawn_bbox,
                    "geometry_type": drawn_geom.get("type", "Polygon"),
                    "vertex_count_approx": vcount,
                }

        clicked = raw.get("clicked_point_wgs84")
        policy = raw.get("execution_policy", "auto")
        if policy not in {"auto", "plan_first", "step_review"}:
            policy = "auto"

        return WorkspaceContext(
            selected_layers=tuple(str(x) for x in (raw.get("selected_layers") or ())),
            drawn_bbox_wgs84=tuple(float(x) for x in drawn_bbox) if isinstance(drawn_bbox, (list, tuple)) and len(drawn_bbox) == 4 else None,
            selected_feature_ids=tuple(raw.get("selected_feature_ids") or ()),
            active_crs=str(raw["active_crs"]) if raw.get("active_crs") else None,
            project_path=str(raw.get("project_path") or self.workspace.project_dir),
            visible_layers=tuple(str(x) for x in (raw.get("visible_layers") or ())),
            clicked_point_wgs84=tuple(float(x) for x in clicked) if isinstance(clicked, (list, tuple)) and len(clicked) == 2 else None,
            drawn_geometry_geojson=drawn_geom if isinstance(drawn_geom, dict) else None,
            figure_annotations=tuple(dict(a) for a in (raw.get("figure_annotations") or ()) if isinstance(a, dict)),
            execution_policy=policy,
        )

    def _run_turn_async(
        self,
        session_id: str,
        mode: str,
        *,
        text: str = "",
        request_id: str | None = None,
        raw_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cfg = self.workspace.load_config()
        api_key = self.workspace.resolve_api_key(cfg)
        if not api_key:
            raise ValueError(f"尚未配置模型 API Key（环境变量 {cfg.api_key_env} 或系统凭据库）。请先在设置中填写。")

        rt = self._runtime(session_id)
        with rt.lock:
            if rt.busy:
                raise RuntimeError("当前会话正在执行任务，请等待完成或先点击停止。")
            rt.busy = True
            cancel_event = Event()
            rt.cancel_event = cancel_event

        output_dir = cfg.output_root / session_id
        ws_ctx = self._build_workspace_context(raw_context, output_dir)
        store = SessionStore(cfg.session_root, session_id)
        if not store.path.exists():
            store.create()

        def on_event(ev: AgentEvent) -> None:
            self._publish_sse(session_id, ev.type, ev.payload)
            if ev.type == "model_replied":
                usage = _estimate_usage_from_calls(_calls_path(store))
                self._publish_sse(session_id, "usage_updated", usage)

        def worker() -> None:
            try:
                with self.conversation_factory(
                    cfg,
                    session_id,
                    api_key=api_key,
                    on_event=on_event,
                    workspace_context=ws_ctx,
                    cancel_event=cancel_event,
                ) as conv:
                    if mode == "send":
                        outcome = conv.send(text)
                    elif mode == "reply":
                        outcome = conv.reply(text, request_id=request_id)
                    else:
                        outcome = conv.resume()
                self._publish_sse(
                    session_id,
                    "session_settled",
                    {"outcome": outcome, "usage": _estimate_usage_from_calls(_calls_path(store))},
                )
            except Exception as error:
                self._publish_sse(session_id, "error", {"error": str(error)})
            finally:
                with rt.lock:
                    rt.busy = False
                    rt.cancel_event = None

        Thread(target=worker, daemon=True, name=f"opengis-worker-{session_id}").start()
        return {"ok": True, "session_id": session_id, "accepted": True}

    def send_message(self, session_id: str, text: str, workspace_context: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("消息内容不能为空。")
        return self._run_turn_async(session_id, "send", text=text.strip(), raw_context=workspace_context)

    def reply_checkpoint(
        self,
        session_id: str,
        *,
        text: str,
        request_id: str | None = None,
        option_id: str | None = None,
        workspace_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        composed = text.strip() if text else ""
        if option_id and not composed:
            composed = f"选择方案：{option_id}"
        elif option_id:
            composed = f"[所选选项: {option_id}] {composed}"
        if not composed:
            raise ValueError("回复或所选选项不能为空。")
        return self._run_turn_async(
            session_id, "reply", text=composed, request_id=request_id, raw_context=workspace_context,
        )

    def stop_session(self, session_id: str) -> dict[str, Any]:
        rt = self._runtime(session_id)
        with rt.lock:
            if not rt.busy or rt.cancel_event is None:
                return {"ok": True, "session_id": session_id, "stopping": False}
            rt.cancel_event.set()
            return {"ok": True, "session_id": session_id, "stopping": True}

    def cancel_checkpoint(self, session_id: str) -> dict[str, Any]:
        cfg = self.workspace.load_config()
        api_key = self.workspace.resolve_api_key(cfg) or "cancel-only"
        with self.conversation_factory(cfg, session_id, api_key=api_key) as conv:
            res = conv.cancel()
        self._publish_sse(session_id, "session_settled", {"outcome": res})
        return res

    def shutdown(self) -> None:
        with self._lock:
            runtimes = list(self._sessions.values())
        for rt in runtimes:
            with rt.lock:
                if rt.cancel_event is not None:
                    rt.cancel_event.set()
