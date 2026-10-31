"""Complete editable map example; run with one JSON settings-file argument.

Requires the checkout's plotting helpers and GIS scientific Python libraries.
Inputs, optional parameters and limits are in ../references/api.md. Produces
PNG/preview/manifest through export_figure and GIS_AGENT_RESULT_PATH. Errors
propagate with nonzero status. Titles may use any configured font's language.
"""
import json
import math
import sys
from pathlib import Path

import geopandas as gpd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar

from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure


def draw(area_path: str, point_path: str, output_dir: str, *, area_layer: str | None = None,
         point_layer: str | None = None, title: str = "", scale_length: float | None = None) -> dict:
    configure_plotting()
    import matplotlib.pyplot as plt

    area = gpd.read_file(area_path, layer=area_layer)
    points = gpd.read_file(point_path, layer=point_layer)
    if area.empty or points.empty or area.crs is None or points.crs is None:
        raise ValueError("Point and area data must be nonempty and have a valid CRS.")
    points = points.to_crs(area.crs)
    fig, ax = plt.subplots(figsize=(7, 6), layout="constrained")
    try:
        area.plot(ax=ax, color="#c7e4ed", edgecolor="#36768c", linewidth=0.9, zorder=1)
        points.plot(ax=ax, color="#ba453b", edgecolor="white", linewidth=0.8, markersize=45, zorder=3)
        ax.margins(0.12)
        ax.set_aspect("equal" if area.crs.is_projected else 1 / math.cos(math.radians(area.total_bounds[[1, 3]].mean())))
        ax.set_axis_off()
        if title:
            ax.set_title(title, fontsize=15, pad=12)
        ax.legend(handles=[Patch(facecolor="#c7e4ed", edgecolor="#36768c", label="Area"),
                           Line2D([], [], linestyle="", marker="o", markerfacecolor="#ba453b",
                                  markeredgecolor="white", label="Input points")], frameon=False, loc="upper right")
        if scale_length is not None:
            if not math.isfinite(scale_length) or scale_length <= 0 or not area.crs.is_projected or any(axis.unit_name != "metre" for axis in area.crs.axis_info[:2]):
                raise ValueError("Scale length must be positive in a local metric projection; verify projection distortion for the task.")
            ax.add_artist(AnchoredSizeBar(ax.transData, scale_length, f"{scale_length:g} m", "lower left",
                                         frameon=False, size_vertical=scale_length / 80))
        return export_figure(fig, output_dir, inputs=(area_path, point_path),
                             map_panels=(MapPanel("main", ax, area.crs.to_string()),))
    finally:
        plt.close(fig)


if __name__ == "__main__":
    draw(**json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
