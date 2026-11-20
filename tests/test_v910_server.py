"""V9.1.0 Ring 2 HIL protocol + Ring 3 local spatial & SSE server tests."""
from __future__ import annotations

from contextlib import contextmanager
import io
import json
from pathlib import Path
import threading
import time
from typing import Any

import gis_agent.server  # Sanitize host PROJ/GDAL env vars before importing spatial wheels.
from fastapi.testclient import TestClient
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, Polygon
from typer.testing import CliRunner

from gis_agent import cli
from gis_agent.adapters.stubs import WorkspaceContext
from gis_agent.application import AgentFactory, Conversation
from gis_agent.config import AppConfig
from gis_agent.core.model import ModelConfig, ModelReply
from gis_agent.integrations.llm import make_token_counter
from gis_agent.integrations.plotting import MapPanel, configure_plotting, export_figure
from gis_agent.persistence.checkpoints import SqliteCheckpointer
from gis_agent.persistence.sessions import SessionStore, message_units
from gis_agent.server.app import create_app
from gis_agent.server.figure_service import FigureService
from gis_agent.server.session_manager import SessionManager
from gis_agent.server.spatial_service import SpatialService
from gis_agent.server.workspace_service import WorkspaceService
from gis_agent.tools.planning import finish_task


def _tool_reply(call_id: str, name: str, arguments: dict[str, Any]) -> ModelReply:
    return ModelReply(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
                }
            ],
        },
        "offline-test",
        {"prompt_tokens": 120, "completion_tokens": 20, "prompt_cache_hit_tokens": 80, "total_tokens": 140},
        "tool_calls",
    )


def test_v910_workspace_context_and_finish_task_checkpoint_validation() -> None:
    legacy = WorkspaceContext(selected_layers=("a.shp",))
    assert legacy.to_dict() == {"selected_layers": ["a.shp"]}

    extended = WorkspaceContext(
        selected_layers=("a.shp",),
        visible_layers=("a.shp", "dem.tif"),
        clicked_point_wgs84=(118.78, 32.04),
        figure_annotations=({"figure_path": "map.png", "norm_bbox": [0.1, 0.2, 0.4, 0.5], "note": "label overlap"},),
        execution_policy="plan_first",
    )
    payload = extended.to_dict()
    assert payload["execution_policy"] == "plan_first"
    assert payload["clicked_point_wgs84"] == [118.78, 32.04]
    assert payload["figure_annotations"][0]["note"] == "label overlap"

    bad = finish_task("completed", "done", checkpoint_kind="plan_approval")
    assert not bad["ok"]
    bad_opts = finish_task("needs_input", "ask", question="which?", options=[{"label": "missing id"}])
    assert not bad_opts["ok"]
    good = finish_task(
        "needs_input",
        "ready for approval",
        question="Approve TIN parameters?",
        checkpoint_kind="plan_approval",
        options=[
            {"id": "approve", "label": "Approve 20/45min TIN", "recommended": True},
            {"id": "corridor", "label": "Use 500m corridor"},
        ],
    )
    assert good["ok"] and good["checkpoint_kind"] == "plan_approval"
    assert len(good["options"]) == 2 and good["options"][0]["recommended"] is True


def test_v910_ring2_events_hil_checkpoint_and_stop_steer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-token")
    monkeypatch.setattr("gis_agent.config.load_dotenv", lambda _: None)
    monkeypatch.delenv("GIS_AGENT_QGIS_DIR", raising=False)

    project = tmp_path / "proj"
    project.mkdir()
    settings_file = tmp_path / "settings.json"
    workspace = WorkspaceService(project, settings_path=settings_file)
    figures = FigureService()
    spatial = SpatialService()

    slow_script = project / "slow_calc.py"
    slow_script.write_text("import time; time.sleep(20)\n", encoding="utf-8")

    stage = {"turn": 0}

    @contextmanager
    def fake_open_conv(cfg: AppConfig, sid: str, *, api_key=None, on_event=None, workspace_context=None, cancel_event=None):
        store = SessionStore(cfg.session_root, sid)
        cfg.session_root.mkdir(parents=True, exist_ok=True)
        output_dir = cfg.output_root / sid
        output_dir.mkdir(parents=True, exist_ok=True)
        messages = store.read_record()

        def chat_fn(req_msgs: list[dict[str, Any]], _schemas: list[dict[str, Any]]) -> ModelReply:
            stage["turn"] += 1
            t = stage["turn"]
            if t == 1:
                return _tool_reply("c1", "update_plan", {
                    "goal": "Hospital accessibility",
                    "steps": [{"content": "Inspect data", "status": "completed"}, {"content": "Approve plan", "status": "in_progress"}],
                })
            if t == 2:
                return _tool_reply("c2", "finish_task", {
                    "status": "needs_input",
                    "summary": "Prepared plan for approval",
                    "question": "Proceed with Trimmed-TIN?",
                    "checkpoint_kind": "plan_approval",
                    "options": [{"id": "approve", "label": "Approve", "recommended": True}],
                })
            if t == 3:
                return _tool_reply("c3", "run_python_script", {"script_path": str(slow_script), "timeout_sec": 30})
            return _tool_reply("c4", "finish_task", {"status": "answer", "summary": "Steered cleanly after stop."})

        with SqliteCheckpointer.from_conn_string(str(cfg.session_root / "checkpoints.sqlite")) as saver:
            factory = AgentFactory(cfg, chat_fn, make_token_counter(cfg.model))
            agent = factory.create(
                store, messages, output_dir, saver, "Test instructions",
                on_event=on_event, cancel_event=cancel_event, workspace_context=workspace_context,
            )
            yield Conversation(agent, messages, output_dir, cancel_event=cancel_event, workspace_context=workspace_context)

    manager = SessionManager(workspace, figures, conversation_factory=fake_open_conv)
    app = create_app(workspace, manager, spatial, figures, token="secret-tok", allow_bootstrap=True)
    client = TestClient(app)

    # Auth enforcement
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/env").status_code == 401
    assert client.get("/api/env", headers={"X-OpenGIS-Token": "wrong"}).status_code == 401
    headers = {"X-OpenGIS-Token": "secret-tok"}
    assert client.get("/api/env", headers=headers).status_code == 200

    # Create session & send message with large AOI (> 2 KB)
    sid = client.post("/api/sessions", json={"session_id": "hil_demo"}, headers=headers).json()["session_id"]
    ring = [[118.7 + 0.001 * i, 32.0 + 0.001 * (i % 5)] for i in range(180)]
    ring.append(ring[0])
    big_aoi = {"type": "Polygon", "coordinates": [ring]}

    res = client.post(
        f"/api/sessions/{sid}/messages",
        json={"text": "Run hospital analysis", "workspace_context": {"execution_policy": "plan_first", "drawn_geometry_geojson": big_aoi}},
        headers=headers,
    )
    assert res.status_code == 200

    # Poll until plan_approval checkpoint arrives
    deadline = time.monotonic() + 8.0
    detail: dict[str, Any] = {}
    while time.monotonic() < deadline:
        detail = client.get(f"/api/sessions/{sid}", headers=headers).json()
        if not detail["busy"] and detail["waiting"]:
            break
        time.sleep(0.05)

    assert detail["waiting"]["checkpoint_kind"] == "plan_approval"
    assert detail["plan"]["goal"] == "Hospital accessibility"
    assert (project / "outputs" / sid / "_user_aoi.geojson").is_file()

    # Reply to checkpoint -> starts turn 3 (slow script), then stop & steer!
    req_id = detail["waiting"]["request_id"]
    rep = client.post(
        f"/api/sessions/{sid}/reply",
        json={"text": "", "option_id": "approve", "request_id": req_id},
        headers=headers,
    )
    assert rep.status_code == 200
    time.sleep(0.35)
    stop_res = client.post(f"/api/sessions/{sid}/stop", headers=headers).json()
    assert stop_res["ok"] is True

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        detail = client.get(f"/api/sessions/{sid}", headers=headers).json()
        if not detail["busy"]:
            break
        time.sleep(0.05)

    # Verify SessionStore integrity and ability to steer immediately in same session
    store = SessionStore(project / "sessions", sid)
    message_units(store.load())

    steer = client.post(
        f"/api/sessions/{sid}/messages",
        json={"text": "Skip slow run and summarize instead"},
        headers=headers,
    )
    assert steer.status_code == 200
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        detail = client.get(f"/api/sessions/{sid}", headers=headers).json()
        if not detail["busy"] and len(detail["messages"]) >= 7:
            break
        time.sleep(0.05)
    assert any(m.get("role") == "assistant" and "Steered cleanly" in str(m.get("content", "")) for m in detail["messages"])

    # Verify live SSE broadcast ordering with manager subscriber
    _rt, sub_q = manager.subscribe(sid)
    try:
        manager._publish_sse(sid, "plan_updated", {"goal": "SSE Verify", "steps": []})
        manager._publish_sse(sid, "artifact_published", {"path": "out.geojson", "kind": "vector"})
        ev1 = sub_q.get(timeout=1.0)
        ev2 = sub_q.get(timeout=1.0)
        assert ev1["type"] == "plan_updated" and ev2["type"] == "artifact_published"
        assert ev2["id"] > ev1["id"]
    finally:
        manager.unsubscribe(sid, sub_q)

    # Verify SSE HTTP stream emits ready + published events
    with client.stream("GET", f"/api/sessions/{sid}/events", headers=headers) as stream:
        line_iter = stream.iter_lines()
        first_event = next(line_iter)
        assert "ready" in first_event
        manager._publish_sse(sid, "usage_updated", {"calls": 4})
        seen_usage = False
        for _ in range(10):
            line = next(line_iter)
            if "usage_updated" in line:
                seen_usage = True
                break
        assert seen_usage


def test_v910_spatial_vector_raster_identify_attributes_and_security(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gis_agent.config.load_dotenv", lambda _: None)
    for var in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA"):
        monkeypatch.delenv(var, raising=False)
    project = tmp_path / "ws"
    project.mkdir()
    outside = tmp_path / "secret_outside.txt"
    outside.write_text("secret", encoding="utf-8")

    # 1. Create real projected GeoPackage (EPSG:3857)
    polys = []
    names = []
    vals = []
    for i in range(15):
        cx = 13200000.0 + i * 1000.0
        cy = 3760000.0
        polys.append(Polygon([(cx - 400, cy - 400), (cx + 400, cy - 400), (cx + 400, cy + 400), (cx - 400, cy + 400)]))
        names.append(f"Zone_{i:02d}")
        vals.append(float((i + 1) * 10))
    gdf = gpd.GeoDataFrame({"name": names, "score": vals}, geometry=polys, crs="EPSG:3857")
    gpkg_path = project / "zones.gpkg"
    gdf.to_file(gpkg_path, driver="GPKG")

    # 2. Create real GeoTIFF with NoData around exact same WGS84 region
    wgs_bounds = gdf.to_crs("EPSG:4326").total_bounds
    w, s, e, n = map(float, wgs_bounds)
    arr = np.linspace(10.0, 200.0, 32 * 32, dtype=np.float32).reshape(32, 32)
    arr[0:4, 0:4] = -9999.0
    tif_path = project / "heatmap.tif"
    transform = from_origin(w - 0.05, n + 0.05, (e - w + 0.1) / 32, (n - s + 0.1) / 32)
    with rasterio.open(
        tif_path, "w", driver="GTiff", height=32, width=32, count=1, dtype="float32", crs="EPSG:4326", transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(arr, 1)

    workspace = WorkspaceService(project, settings_path=tmp_path / "settings.json")
    app = create_app(workspace, SessionManager(workspace, FigureService()), SpatialService(), FigureService(), token="tok")
    client = TestClient(app)
    headers = {"X-OpenGIS-Token": "tok"}

    # Path traversal defense
    assert client.get("/api/spatial/layer-meta", params={"path": str(outside)}, headers=headers).status_code == 403
    assert client.get("/api/figures/file", params={"path": str(project / ".." / "secret_outside.txt")}, headers=headers).status_code == 403

    # Vector meta + truncated bbox read + attribute stats
    meta = client.get("/api/spatial/layer-meta", params={"path": str(gpkg_path)}, headers=headers).json()
    assert meta["kind"] == "vector" and meta["feature_count"] == 15
    assert len(meta["bbox_wgs84"]) == 4

    vec = client.get("/api/spatial/vector", params={"path": str(gpkg_path), "zoom": 10}, headers=headers).json()
    assert vec["type"] == "FeatureCollection"
    assert len(vec["features"]) == 15
    assert "_fid" in vec["features"][0]["properties"]

    attrs = client.get("/api/spatial/attributes", params={"path": str(gpkg_path), "stats_field": "score", "page_size": 10}, headers=headers).json()
    assert attrs["total"] == 15 and len(attrs["rows"]) == 10
    assert attrs["stats"]["min"] == 10.0 and attrs["stats"]["max"] == 150.0
    assert len(attrs["stats"]["histogram"]) == 12

    # Raster WarpedVRT preview
    png_res = client.get("/api/spatial/raster/preview", params={"path": str(tif_path), "colormap": "viridis"}, headers=headers)
    assert png_res.status_code == 200
    assert png_res.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(png_res.content))
    assert img.mode == "RGBA" and img.size[0] >= 2
    bounds_hdr = json.loads(png_res.headers["X-OpenGIS-Bounds"])
    assert len(bounds_hdr) == 4 and bounds_hdr[0] < bounds_hdr[2]

    # Spatial Identify hitting both projected vector & raster simultaneously
    cx_wgs, cy_wgs = gdf.to_crs("EPSG:4326").geometry.iloc[0].centroid.coords[0]
    id_res = client.post(
        "/api/spatial/identify",
        json={
            "lon": cx_wgs,
            "lat": cy_wgs,
            "zoom": 13,
            "layers": [{"path": str(gpkg_path), "type": "vector"}, {"path": str(tif_path), "type": "raster"}],
        },
        headers=headers,
    )
    assert id_res.status_code == 200
    results = id_res.json()["results"]
    assert results[0]["hits"][0]["properties"]["name"] == "Zone_00"
    assert results[1]["inside"] is True and results[1]["bands"][0]["physical_value"] is not None


def test_v910_figure_service_and_studio_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "fig_ws"
    fig_out = project / "outputs" / "demo_sess" / "figures"
    fig_out.mkdir(parents=True)

    configure_plotting(font_style="serif")
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot([0, 1], [0, 1], gid="flow_arcs")
    ax.set_title("Test Figure", fontsize=14)
    ax.set_xlabel("Lon", fontsize=10)
    ax.set_ylabel("Lat", fontsize=10)
    export_figure(fig, fig_out, formats=("png", "svg"), dpi=120, map_panels=(MapPanel("main", ax, "EPSG:4326"),))
    plt.close(fig)

    workspace = WorkspaceService(project, settings_path=tmp_path / "settings.json")
    figures = FigureService()
    app = create_app(workspace, SessionManager(workspace, figures), SpatialService(), figures, token="tok")
    client = TestClient(app)
    headers = {"X-OpenGIS-Token": "tok"}

    listed = client.get("/api/figures/demo_sess", headers=headers).json()["figures"]
    assert len(listed) == 1
    assert listed[0]["png_path"].endswith("map.png")
    assert listed[0]["svg_path"].endswith("map.svg")
    assert isinstance(listed[0]["layout_diagnostics"], dict)

    svg_layers = client.get("/api/figures/svg-layers", params={"path": listed[0]["svg_path"]}, headers=headers).json()["layers"]
    assert any(layer["id"] == "flow_arcs" and layer["semantic"] for layer in svg_layers)

    img_res = client.get("/api/figures/file", params={"path": listed[0]["png_path"]}, headers=headers)
    assert img_res.status_code == 200 and img_res.headers["content-type"] == "image/png"

    # CLI studio subcommand forwards resolved arguments cleanly
    called = []
    import gis_agent.server.app as server_app

    monkeypatch.setattr(server_app, "run_server", lambda **kw: called.append(kw))
    r = CliRunner().invoke(cli.app, ["studio", "--folder", str(project), "--no-browser", "--port", "8765"])
    assert r.exit_code == 0, r.output
    assert called and called[0]["project"] == project.resolve() and called[0]["port"] == 8765 and called[0]["open_browser"] is False
