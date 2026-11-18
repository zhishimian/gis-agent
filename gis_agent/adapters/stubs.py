"""V9.0 桌面端与 QGIS 插件适配器边界桩定义（GUI 实现延后至 V9.1+）。

契约约束：
1. 桌面端（Desktop Studio）通过订阅 core.events.EventCallback 获取实时状态与新产物路径，
   严禁在 UI 线程直接执行模型请求或空间计算。
2. QGIS 插件端必须在后台任务或独立子进程运行 Agent 与重计算；仅在收到 tool_finished / turn_finished
   信号并切回 Qt 主线程后，才允许访问 QgsProject.instance() 或地图画布对象。
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gis_agent.core.events import AgentEvent


class FrontendBridge(Protocol):
    def on_agent_event(self, event: AgentEvent) -> None: ...
    def publish_layer(self, path: Path) -> None: ...


@dataclass(frozen=True)
class WorkspaceContext:
    selected_layers: tuple[str, ...] = ()
    drawn_bbox_wgs84: tuple[float, float, float, float] | None = None
    selected_feature_ids: tuple[int | str, ...] = ()
