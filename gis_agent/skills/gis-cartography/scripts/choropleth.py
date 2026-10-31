"""Complete editable map example; run with one JSON settings-file argument.

Requires the checkout's plotting helpers and GIS scientific Python libraries.
Inputs, optional parameters and limits are in ../references/api.md. Produces
PNG/preview/manifest through export_figure and GIS_AGENT_RESULT_PATH. Errors
propagate with nonzero status. Titles may use any configured font's language.
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.colors import BoundaryNorm, ListedColormap, Normalize
from matplotlib.patches import Patch

from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure


def draw(source: str, field: str, output_dir: str, *, layer: str | None = None, title: str = "",
         unit: str = "", breaks: list[float] | None = None, colors: list[str] | None = None) -> dict:
    configure_plotting()
    import matplotlib.pyplot as plt

    data = gpd.read_file(source, layer=layer)
    if data.crs is None or data.empty:
        raise ValueError("Area data must be nonempty and have a valid CRS.")
    valid = data[data[field].notna()]
    missing = data[data[field].isna()]
    values = valid[field].to_numpy(dtype=float)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("Values must be finite; resolve nonfinite values separately from missing data.")
    fig, ax = plt.subplots(figsize=(7, 6), layout="constrained")
    try:
        handles = []
        counts = None
        if breaks is not None:
            if len(breaks) < 2 or not np.isfinite(breaks).all() or not np.all(np.diff(breaks) > 0):
                raise ValueError("Class boundaries must be finite and strictly increasing.")
            if values.min() < breaks[0] or values.max() > breaks[-1] or colors is None or len(colors) != len(breaks) - 1:
                raise ValueError("Class boundaries must cover valid values; color count must equal interval count.")
            cmap = ListedColormap(colors)
            norm = BoundaryNorm(breaks, cmap.N, clip=True)
            counts = np.histogram(values, bins=breaks)[0].tolist()
            handles = [Patch(facecolor=color, label=f"[{low:g}, {high:g}{']' if i == len(colors) - 1 else ')'}")
                       for i, (low, high, color) in enumerate(zip(breaks, breaks[1:], colors))]
        else:
            cmap = plt.get_cmap("viridis")
            norm = Normalize(values.min(), values.max())
            fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, label=unit or field, shrink=0.72)
        valid.plot(ax=ax, column=field, cmap=cmap, norm=norm, edgecolor="white", linewidth=0.5, zorder=1)
        if not missing.empty:
            missing.plot(ax=ax, facecolor="#dddddd", edgecolor="white", hatch="///", linewidth=0.5, zorder=1)
            handles.append(Patch(facecolor="#dddddd", hatch="///", label="No data"))
        if handles:
            ax.legend(handles=handles, title=unit or field, frameon=False, loc="best")
        ax.set_aspect("equal" if data.crs.is_projected else 1 / np.cos(np.deg2rad(data.total_bounds[[1, 3]].mean())))
        ax.set_axis_off()
        if title:
            ax.set_title(title, fontsize=15)
        result = export_figure(fig, output_dir, inputs=(source,), map_panels=(MapPanel("main", ax, data.crs.to_string()),))
        Path(output_dir, "encoding.json").write_text(json.dumps({"field": field, "unit": unit, "breaks": breaks,
            "class_counts": counts, "valid": len(valid), "missing": len(missing)}, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        plt.close(fig)


if __name__ == "__main__":
    draw(**json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
