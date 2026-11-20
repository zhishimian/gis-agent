"""FastAPI application factory, Bearer/query token auth, SSE stream, and parent-PID watchdog."""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import queue
import secrets
import sys
from threading import Thread
import time
from typing import Any
import webbrowser

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from gis_agent.server.figure_service import FigureService
from gis_agent.server.session_manager import SessionManager
from gis_agent.server.spatial_service import SpatialService
from gis_agent.server.workspace_service import WorkspaceService

try:
    from importlib.metadata import version as _pkg_version

    APP_VERSION = _pkg_version("gis-agent")
except Exception:
    APP_VERSION = "9.1.0"


class SelectWorkspaceReq(BaseModel):
    project_dir: str


class AttachFileReq(BaseModel):
    path: str


class CredentialsReq(BaseModel):
    api_key: str | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None


class QgisConfigReq(BaseModel):
    qgis_dir: str | None = None


class CreateSessionReq(BaseModel):
    session_id: str | None = None


class SendMessageReq(BaseModel):
    text: str
    workspace_context: dict[str, Any] | None = None


class ReplyReq(BaseModel):
    text: str = ""
    request_id: str | None = None
    option_id: str | None = None
    workspace_context: dict[str, Any] | None = None


class IdentifyReq(BaseModel):
    lon: float
    lat: float
    tolerance_m: float | None = None
    zoom: float = 10.0
    layers: list[dict[str, Any]] = Field(default_factory=list)


class RevealReq(BaseModel):
    path: str
    action: str = "reveal"


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return False
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _default_static_dir() -> Path | None:
    cand = Path(__file__).resolve().parent / "static"
    return cand if (cand / "index.html").is_file() else None


def create_app(
    workspace: WorkspaceService,
    manager: SessionManager,
    spatial: SpatialService,
    figures: FigureService,
    *,
    token: str,
    static_dir: Path | None = None,
    allow_bootstrap: bool = False,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        manager.shutdown()

    app = FastAPI(title="OpenGIS Studio Server", version=APP_VERSION, lifespan=lifespan)
    app.state.token = token
    app.state.workspace = workspace
    app.state.manager = manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://tauri.localhost",
            "https://tauri.localhost",
            "tauri://localhost",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS":
            return await call_next(request)
        if not path.startswith("/api/"):
            return await call_next(request)
        if path == "/api/health" or (allow_bootstrap and path == "/api/bootstrap"):
            return await call_next(request)
        supplied = request.headers.get("X-OpenGIS-Token") or request.query_params.get("token")
        if supplied is None:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                supplied = auth[7:].strip()
        if not supplied or not secrets.compare_digest(supplied, token):
            return JSONResponse(status_code=401, content={"detail": "未授权：缺少或无效的 X-OpenGIS-Token。"})
        return await call_next(request)

    def _guard_http(fn):
        try:
            return fn()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": APP_VERSION, "pid": os.getpid()}

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, Any]:
        if not allow_bootstrap:
            raise HTTPException(status_code=403, detail="当前服务端已关闭浏览器引导接口。")
        return {
            "token": token,
            "version": APP_VERSION,
            "project_dir": str(workspace.project_dir),
            "mode": "browser",
        }

    @app.get("/api/env")
    def env_info() -> dict[str, Any]:
        return workspace.get_env_info()

    @app.post("/api/workspace/select")
    def select_workspace(req: SelectWorkspaceReq) -> dict[str, Any]:
        return _guard_http(lambda: workspace.select_project(req.project_dir))

    @app.post("/api/workspace/attach")
    def attach_file(req: AttachFileReq) -> dict[str, Any]:
        return _guard_http(lambda: workspace.attach_file(req.path))

    @app.get("/api/workspace/files")
    def list_workspace_files(dir: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        return _guard_http(lambda: workspace.list_files(dir, session_id=session_id))

    @app.get("/api/settings/credentials")
    def get_credentials() -> dict[str, Any]:
        return workspace.credentials_status()

    @app.post("/api/settings/credentials")
    def save_credentials(req: CredentialsReq) -> dict[str, Any]:
        return _guard_http(
            lambda: workspace.save_credentials(
                api_key=req.api_key,
                provider=req.provider,
                model=req.model,
                base_url=req.base_url,
            )
        )

    @app.post("/api/settings/qgis")
    def set_qgis(req: QgisConfigReq) -> dict[str, Any]:
        return _guard_http(lambda: workspace.configure_qgis(req.qgis_dir))

    @app.get("/api/sessions")
    def get_sessions() -> dict[str, Any]:
        return {"sessions": manager.list_sessions()}

    @app.post("/api/sessions")
    def post_sessions(req: CreateSessionReq) -> dict[str, Any]:
        return _guard_http(lambda: manager.create_session(req.session_id))

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        return _guard_http(lambda: manager.get_session_detail(session_id))

    @app.get("/api/sessions/{session_id}/events")
    async def session_events(session_id: str, request: Request):
        import asyncio

        _rt, q = manager.subscribe(session_id)

        async def event_stream():
            last_hb = time.monotonic()
            try:
                yield f"event: ready\ndata: {json.dumps({'session_id': session_id})}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    drained = False
                    while True:
                        try:
                            msg = q.get_nowait()
                        except queue.Empty:
                            break
                        drained = True
                        ev_type = msg["type"]
                        ev_id = msg["id"]
                        data = json.dumps(msg, ensure_ascii=False)
                        yield f"id: {ev_id}\nevent: {ev_type}\ndata: {data}\n\n"
                        last_hb = time.monotonic()
                    if not drained:
                        now = time.monotonic()
                        if now - last_hb >= 15.0:
                            last_hb = now
                            yield f"event: heartbeat\ndata: {json.dumps({'ts': int(time.time())})}\n\n"
                        await asyncio.sleep(0.05)
            finally:
                manager.unsubscribe(session_id, q)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/sessions/{session_id}/messages")
    def post_message(session_id: str, req: SendMessageReq) -> dict[str, Any]:
        return _guard_http(
            lambda: manager.send_message(session_id, req.text, workspace_context=req.workspace_context)
        )

    @app.post("/api/sessions/{session_id}/reply")
    def post_reply(session_id: str, req: ReplyReq) -> dict[str, Any]:
        return _guard_http(
            lambda: manager.reply_checkpoint(
                session_id,
                text=req.text,
                request_id=req.request_id,
                option_id=req.option_id,
                workspace_context=req.workspace_context,
            )
        )

    @app.post("/api/sessions/{session_id}/stop")
    def post_stop(session_id: str) -> dict[str, Any]:
        return manager.stop_session(session_id)

    @app.post("/api/sessions/{session_id}/cancel")
    def post_cancel(session_id: str) -> dict[str, Any]:
        return _guard_http(lambda: manager.cancel_checkpoint(session_id))

    def _auth_uri(raw_path: str) -> str:
        resolved = workspace.authorize_path(raw_path)
        if "|layername=" in raw_path:
            layer_part = raw_path.split("|layername=", 1)[1].split("|", 1)[0]
            return f"{resolved}|layername={layer_part}"
        return str(resolved)

    @app.get("/api/spatial/layer-meta")
    def spatial_layer_meta(path: str) -> dict[str, Any]:
        return _guard_http(lambda: spatial.get_layer_meta(_auth_uri(path)))

    @app.get("/api/spatial/vector")
    def spatial_vector(
        path: str,
        bbox: str | None = None,
        zoom: float | None = None,
        max_features: int = 5000,
        simplify_tol: float | None = None,
        fields: str | None = None,
    ) -> dict[str, Any]:
        def run():
            uri = _auth_uri(path)
            parsed_bbox = None
            if bbox:
                parts = [float(x) for x in bbox.split(",")]
                if len(parts) != 4:
                    raise ValueError("bbox 必须为 4 个逗号分隔数值：west,south,east,north")
                parsed_bbox = (parts[0], parts[1], parts[2], parts[3])
            parsed_fields = [f.strip() for f in fields.split(",") if f.strip()] if fields is not None else None
            return spatial.get_vector_geojson(
                uri, bbox=parsed_bbox, zoom=zoom, max_features=max_features, simplify_tol=simplify_tol, fields=parsed_fields
            )

        return _guard_http(run)

    @app.get("/api/spatial/raster/preview")
    def spatial_raster_preview(
        path: str,
        bbox: str | None = None,
        width: int = 1024,
        height: int = 1024,
        band: int = 1,
        colormap: str = "viridis",
        p_low: float = 2.0,
        p_high: float = 98.0,
    ):
        def run():
            uri = _auth_uri(path)
            parsed_bbox = None
            if bbox:
                parts = [float(x) for x in bbox.split(",")]
                if len(parts) != 4:
                    raise ValueError("bbox 必须为 4 个逗号分隔数值。")
                parsed_bbox = (parts[0], parts[1], parts[2], parts[3])
            return spatial.get_raster_preview(
                uri, bbox=parsed_bbox, width=width, height=height, band=band, colormap=colormap, p_low=p_low, p_high=p_high
            )

        data = _guard_http(run)
        return Response(
            content=data["png_bytes"],
            media_type="image/png",
            headers={
                "X-OpenGIS-Bounds": json.dumps(data["bounds_wgs84"]),
                "X-OpenGIS-Stats": json.dumps(data["stats"]),
                "X-OpenGIS-Band-Count": str(data["band_count"]),
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/spatial/identify")
    def spatial_identify(req: IdentifyReq) -> dict[str, Any]:
        def run():
            authorized_layers: list[dict[str, Any]] = []
            for item in req.layers:
                raw_p = str(item.get("path") or "")
                if not raw_p:
                    continue
                authorized_layers.append({**item, "resolved_uri": _auth_uri(raw_p)})
            return spatial.identify(
                lon=req.lon,
                lat=req.lat,
                layers=authorized_layers,
                tolerance_m=req.tolerance_m,
                zoom=req.zoom,
            )

        return _guard_http(run)

    @app.get("/api/spatial/attributes")
    def spatial_attributes(
        path: str,
        page: int = 1,
        page_size: int = 100,
        sort_by: str | None = None,
        order: str = "asc",
        query: str | None = None,
        stats_field: str | None = None,
    ) -> dict[str, Any]:
        return _guard_http(
            lambda: spatial.get_attributes(
                _auth_uri(path),
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                order=order,
                query=query,
                stats_field=stats_field,
            )
        )

    @app.get("/api/figures/file")
    def read_figure_file(path: str):
        target = _guard_http(lambda: workspace.authorize_path(path))
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"图件不存在：{target}")
        media = "image/svg+xml" if target.suffix.lower() == ".svg" else ("image/png" if target.suffix.lower() == ".png" else None)
        return FileResponse(target, media_type=media, headers={"Cache-Control": "no-store"})

    @app.get("/api/figures/svg-layers")
    def figure_svg_layers(path: str) -> dict[str, Any]:
        from gis_agent.server.figure_service import list_svg_layers

        target = _guard_http(lambda: workspace.authorize_path(path))
        return {"path": str(target), "layers": list_svg_layers(target)}

    @app.get("/api/figures/{session_id}")
    def list_session_figures(session_id: str) -> dict[str, Any]:
        cfg = workspace.load_config()
        output_dir = cfg.output_root / session_id
        return {"session_id": session_id, "figures": figures.list_figures(output_dir)}

    @app.get("/api/executions/{session_id}")
    def list_executions(session_id: str, execution_id: str | None = None, section: str = "summary") -> dict[str, Any]:
        return _guard_http(lambda: manager.get_executions(session_id, execution_id=execution_id, section=section))

    @app.post("/api/os/reveal")
    def os_reveal(req: RevealReq) -> dict[str, Any]:
        return _guard_http(lambda: workspace.reveal_or_open(req.path, action=req.action))

    resolved_static = static_dir or _default_static_dir()
    if resolved_static is not None and resolved_static.is_dir():
        app.mount("/", StaticFiles(directory=str(resolved_static), html=True), name="studio-static")

    return app


def run_server(
    *,
    project: Path,
    host: str = "127.0.0.1",
    port: int = 0,
    token: str | None = None,
    parent_pid: int | None = None,
    open_browser: bool = False,
    allow_bootstrap: bool = False,
) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("OpenGIS Studio 服务仅允许绑定本机回环地址（127.0.0.1 / localhost）。")
    import socket

    resolved_token = token or secrets.token_urlsafe(32)
    workspace = WorkspaceService(project)
    figures = FigureService()
    manager = SessionManager(workspace, figures)
    spatial = SpatialService()
    app = create_app(
        workspace,
        manager,
        spatial,
        figures,
        token=resolved_token,
        allow_bootstrap=allow_bootstrap,
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, port))
    sock.listen(128)
    actual_port = sock.getsockname()[1]

    config = uvicorn.Config(app, host=host, port=actual_port, log_level="warning")
    server = uvicorn.Server(config)

    def notify_when_ready() -> None:
        deadline = time.monotonic() + 15.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        handshake = {
            "ready": True,
            "host": host,
            "port": actual_port,
            "token": resolved_token,
            "pid": os.getpid(),
            "url": f"http://{host}:{actual_port}",
        }
        print(json.dumps(handshake, ensure_ascii=False), flush=True)
        if open_browser:
            webbrowser.open(f"http://{host}:{actual_port}")

    Thread(target=notify_when_ready, daemon=True, name="opengis-ready-beacon").start()

    if parent_pid is not None and parent_pid > 0:
        def watch_parent() -> None:
            while not server.should_exit:
                if not _is_pid_alive(parent_pid):
                    manager.shutdown()
                    server.should_exit = True
                    break
                time.sleep(1.0)

        Thread(target=watch_parent, daemon=True, name="opengis-parent-watchdog").start()

    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
        manager.shutdown()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="OpenGIS Studio Local Spatial Engine Server")
    parser.add_argument("--project", default=".", help="Workspace folder")
    parser.add_argument("--host", default="127.0.0.1", help="Loopback host bind address")
    parser.add_argument("--port", type=int, default=0, help="Port (0 for auto-assign)")
    parser.add_argument("--token", default=None, help="Shared bearer/query token")
    parser.add_argument("--parent-pid", type=int, default=None, help="Terminate automatically when parent PID exits")
    parser.add_argument("--open-browser", action="store_true", help="Open system browser with bootstrap endpoint")
    parser.add_argument("--allow-bootstrap", action="store_true", help="Expose /api/bootstrap for same-origin browser mode")
    args = parser.parse_args(argv)
    run_server(
        project=Path(args.project),
        host=args.host,
        port=args.port,
        token=args.token,
        parent_pid=args.parent_pid,
        open_browser=args.open_browser,
        allow_bootstrap=args.allow_bootstrap or args.open_browser,
    )


if __name__ == "__main__":
    main()
