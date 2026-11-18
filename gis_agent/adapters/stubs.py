"""V9.0.1 桌面端与 QGIS 插件适配器边界协议（GUI 壳层绑定接口）。

契约约束：
1. 桌面端（Desktop Studio）通过订阅 core.events.EventCallback 获取实时状态与 tool_finished.outputs 产物路径，
   严禁在 UI 线程直接执行模型请求或空间计算；用户点击停止时调用 conversation.request_stop()。
2. QGIS 插件端必须在后台任务线程运行 Agent，重计算经独立子进程隔离；仅在收到 tool_finished / turn_finished
   信号并切回 Qt 主线程后，才允许访问 QgsProject.instance() 或地图画布对象。
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from gis_agent.core.events import AgentEvent


class FrontendBridge(Protocol):
    def on_agent_event(self, event: AgentEvent) -> None: ...
    def publish_layer(self, path: Path) -> None: ...


@dataclass(frozen=True)
class WorkspaceContext:
    selected_layers: tuple[str, ...] = ()
    drawn_bbox_wgs84: tuple[float, float, float, float] | None = None
    selected_feature_ids: tuple[int | str, ...] = ()
    active_crs: str | None = None
    project_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.selected_layers:
            payload["selected_layers"] = list(self.selected_layers)
        if self.drawn_bbox_wgs84 is not None:
            payload["drawn_bbox_wgs84"] = list(self.drawn_bbox_wgs84)
        if self.selected_feature_ids:
            payload["selected_feature_ids"] = list(self.selected_feature_ids)
        if self.active_crs:
            payload["active_crs"] = self.active_crs
        if self.project_path:
            payload["project_path"] = self.project_path
        return payload
