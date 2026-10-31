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
import rasterio
from affine import Affine
from matplotlib.colors import Normalize
from rasterio.enums import Resampling
from rasterio.plot import plotting_extent
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds

from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure


def draw(raster_path: str, output_dir: str, *, point_path: str | None = None, point_layer: str | None = None,
         display_crs: str | None = None, bounds: list[float] | None = None, title: str = "") -> dict:
    configure_plotting()
    import matplotlib.pyplot as plt

    with rasterio.open(raster_path) as source:
        if source.crs is None:
            raise ValueError("Raster needs a valid CRS.")
        with WarpedVRT(source, crs=display_crs or source.crs, resampling=Resampling.bilinear) as display:
            window = from_bounds(*bounds, transform=display.transform).intersection(display.window(*display.bounds)) if bounds else display.window(*display.bounds)
            factor = max(window.width, window.height) / 1200
            shape = (max(1, round(window.height / max(1, factor))), max(1, round(window.width / max(1, factor))))
            array = display.read(1, window=window, out_shape=shape, masked=True, resampling=Resampling.bilinear)
            transform = display.window_transform(window) * Affine.scale(window.width / shape[1], window.height / shape[0])
            crs = display.crs
    values = array.compressed()
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("Display window has no valid finite values.")
    extent = plotting_extent(array, transform)
    norm = Normalize(values.min(), values.max())
    points = gpd.read_file(point_path, layer=point_layer).to_crs(crs) if point_path else None
    fig = plt.figure(figsize=(9, 6), layout="constrained")
    try:
        grid = fig.add_gridspec(2, 3)
        ax = fig.add_subplot(grid[:, :2])
        detail = fig.add_subplot(grid[0, 2])
        histogram = fig.add_subplot(grid[1, 2])
        for target in (ax, detail):
            image = target.imshow(array, extent=extent, origin="upper", cmap="terrain", norm=norm, zorder=0)
            if points is not None:
                points.plot(ax=target, color="#c33e36", edgecolor="white", linewidth=0.6, markersize=28, zorder=2)
            target.set_aspect("equal" if crs.is_projected else 1 / np.cos(np.deg2rad((extent[2] + extent[3]) / 2)))
            target.set_axis_off()
        left, right, bottom, top = extent
        detail.set_xlim(left + (right - left) * 0.3, left + (right - left) * 0.7)
        detail.set_ylim(bottom + (top - bottom) * 0.3, bottom + (top - bottom) * 0.7)
        ax.set_xlim(left, right)
        ax.set_ylim(bottom, top)
        ax.indicate_inset_zoom(detail, edgecolor="#333333", linewidth=0.7)
        histogram.hist(values, bins=25, color="#53857c", edgecolor="white")
        histogram.set(xlabel="Raster value", ylabel="Display sample count")
        histogram.spines[["top", "right"]].set_visible(False)
        fig.colorbar(image, ax=[ax, detail], shrink=0.7, label="Raster value")
        if title:
            ax.set_title(title, fontsize=15)
        return export_figure(fig, output_dir, inputs=tuple(path for path in (raster_path, point_path) if path),
                             map_panels=(MapPanel("main", ax, crs.to_string()), MapPanel("detail", detail, crs.to_string())))
    finally:
        plt.close(fig)


if __name__ == "__main__":
    draw(**json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
