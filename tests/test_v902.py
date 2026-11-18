import json
from pathlib import Path
from typing import Any

import pytest

from gis_agent import config as configuration
from gis_agent.config import AppConfig
from gis_agent.core.auxiliary import AuxiliaryCalls
from gis_agent.core.context import SUMMARY_SECTIONS, ContextConfig, ContextManager
from gis_agent.core.model import ModelConfig, ModelReply
from gis_agent.integrations.llm import make_token_counter
from gis_agent.persistence.sessions import SessionStore


def test_ninety_percent_compaction_triggers_before_hard_limit(tmp_path: Path) -> None:
    """超过可用输入预算 90% 时主动压缩旧工具批次，低于 90% 保持原前缀不变。"""
    store = SessionStore(tmp_path, "compact90")
    messages: list[dict[str, Any]] = [{"role": "user", "origin": "user", "content": "开始分析任务。"}]
    for idx in range(3):
        messages.extend(
            [
                {
                    "role": "assistant",
                    "tool_calls": [{"id": f"c{idx}", "function": {"name": "analysis", "arguments": "{}"}}],
                },
                {
                    "role": "tool",
                    "tool_call_id": f"c{idx}",
                    "tool_name": "analysis",
                    "content": json.dumps({"ok": True, "detail": f"step {idx}: " + ("alpha beta " * 140)}),
                },
            ]
        )
    store.save(messages)

    count_tokens = make_token_counter(ModelConfig())
    # 先测量完整视图实际 token 数，构造刚好处于 90%～99% 区间的预算上限
    probe_ctx = ContextManager(
        store,
        ContextConfig(request_token_limit=50000, compact_ratio=0.9, recent_batches=2, recent_users=1),
        AuxiliaryCalls(lambda *_: pytest.fail("未达阈值不应总结"), store.record_model_call, count_tokens),
        set(),
    )
    full_tokens = probe_ctx.prepare("系统", messages, {}, []).estimated_tokens
    # 使 full_tokens 约占 request_token_limit 的 94%（> 90%，但 <= 100%）
    tight_limit = max(600, int(full_tokens / 0.94))
    assert int(tight_limit * 0.9) < full_tokens <= tight_limit

    summary = {key: [] for key in SUMMARY_SECTIONS}
    summary["goal"] = [{"text": "完成三阶段分析", "sources": [0]}]
    summary["work"] = [{"text": "已完成第 0 批", "sources": [1, 2]}]
    compact_calls = 0

    def fake_summary(*_args: Any) -> ModelReply:
        nonlocal compact_calls
        compact_calls += 1
        return ModelReply({"role": "assistant", "content": json.dumps(summary, ensure_ascii=False)}, "offline", None, "stop")

    active_ctx = ContextManager(
        store,
        ContextConfig(request_token_limit=tight_limit, compact_ratio=0.9, recent_batches=2, recent_users=1),
        AuxiliaryCalls(fake_summary, store.record_model_call, count_tokens),
        set(),
    )
    prepared = active_ctx.prepare("系统", messages, {}, [])
    assert compact_calls == 1
    assert active_ctx.covered > 0
    assert prepared.estimated_tokens < full_tokens


def test_compact_ratio_validation_and_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="compact_ratio"):
        ContextConfig(compact_ratio=0.05)
    with pytest.raises(ValueError, match="compact_ratio"):
        ContextConfig(compact_ratio=1.2)

    monkeypatch.setattr(configuration, "load_dotenv", lambda _: None)
    monkeypatch.delenv("GIS_AGENT_QGIS_DIR", raising=False)
    monkeypatch.setenv("GIS_AGENT_COMPACT_RATIO", "0.85")
    cfg = AppConfig.from_env(tmp_path)
    assert cfg.context.compact_ratio == 0.85
    assert cfg.context.compact_token_limit == int(cfg.context.request_token_limit * 0.85)


def test_standalone_uv_geopython_inspect_and_plotting_without_qgis(tmp_path: Path) -> None:
    """脱离 Conda 与桌面 QGIS 时，独立 GeoPython 解释器仍可完成快速探针与成图导出。"""
    import importlib.util
    import sys

    if any(importlib.util.find_spec(mod) is None for mod in ("geopandas", "rasterio", "matplotlib", "pyogrio")):
        pytest.skip("当前解释器未安装 geo 可选依赖组。")

    import geopandas as gpd
    from matplotlib import pyplot as plt
    from shapely.geometry import Point

    from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure
    from gis_agent.runtime.probe import probe_launcher
    from gis_agent.tools.qgis_python import inspect_data

    launcher = Path(sys.executable)
    probed = probe_launcher(launcher)
    assert probed["has_qgis"] is False or "geopandas" in probed["packages"]
    assert {"geopandas", "rasterio", "pyogrio", "matplotlib"}.issubset(probed["packages"].keys())

    shp_dir = tmp_path / "data"
    shp_dir.mkdir()
    pts_path = shp_dir / "pts.gpkg"
    gpd.GeoDataFrame({"name": ["A"]}, geometry=[Point(500000, 3500000)], crs="EPSG:32650").to_file(pts_path)
    info = inspect_data(launcher, tmp_path / "logs", source=str(pts_path))
    assert info["ok"] and info["data"]["feature_count"] == 1 and info["data"]["units"] == "metre"

    configure_plotting()
    fig, ax = plt.subplots()
    gpd.read_file(pts_path).plot(ax=ax)
    map_dir = tmp_path / "map_out"
    exported = export_figure(fig, map_dir, inputs=(pts_path,), map_panels=(MapPanel("main", ax, "EPSG:32650"),))
    plt.close(fig)
    assert exported["ok"] and Path(exported["files"]["png"]).stat().st_size > 0
