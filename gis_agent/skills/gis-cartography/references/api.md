# Plotting Runtime & Primitives Quick Reference

## Exact imports

Use these exact names (`compass_star`/`sleek_needle`/`chevron` are `north_style=` values on `add_scalebar_and_north`, not standalone imports):

```python
from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure
from gis_agent.integrations.plotting.primitives import (
    GEO_COLORS, apply_publication_theme, get_scientific_cmap, build_perceptual_norm,
    get_palette, list_palettes, get_bivariate_palette, build_bivariate_palette,
    bivariate_classify, add_graticule_frame, add_scalebar_and_north, add_locator_inset,
    add_continuous_colorbar, add_bivariate_legend, add_clean_legend,
    add_leader_callouts, attach_marginal_profiles, find_quiet_corner,
    rank_quiet_corners, add_flow_arcs, add_size_legend,
)
```

Call `configure_plotting()` BEFORE `apply_publication_theme()` and BEFORE importing `pyplot`. Put checkout on `PYTHONPATH` if outside `run_python_script`.

## Minimal runnable skeleton

```python
from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure
from gis_agent.integrations.plotting.primitives import (
    GEO_COLORS, apply_publication_theme, add_graticule_frame,
    add_scalebar_and_north, add_clean_legend,
)
configure_plotting(font_style="serif", svg_editable_text=True)  # serif | kaiti | fangsong | sans
import geopandas as gpd, matplotlib.pyplot as plt

gdf = gpd.read_file(source, layer=actual_layer).to_crs(target_crs)
theme = apply_publication_theme("light_geo", fig_width=8.5)
fig = plt.figure(figsize=(8.5, 6.2))
try:
    ax = fig.add_axes([0.08, 0.12, 0.68, 0.78])
    gdf.plot(ax=ax, facecolor=GEO_COLORS["land_warm"], edgecolor=GEO_COLORS["border_study"], linewidth=0.9, zorder=8)
    ax.set_aspect("equal")
    add_graticule_frame(ax, crs=gdf.crs, style="ticks_only", dms=True)
    add_scalebar_and_north(ax, crs_units="metre", loc="lower right", north_loc="upper left", north_style="compass_star")
    ax_leg = fig.add_axes([0.78, 0.14, 0.20, 0.42]); ax_leg.set_axis_off()
    add_clean_legend(ax_leg, [("Study Area", GEO_COLORS["land_warm"])], title="Legend", loc="center", frameon=True, title_align="center")
    res = export_figure(fig, output_dir, formats=("png", "svg"), inputs=(source,), map_panels=(MapPanel("main", ax, gdf.crs.to_string()),))
finally:
    plt.close(fig)
```

## Primitives & flow cheat sheet

- `configure_plotting(font_files=None, *, font_style=None, svg_editable_text=True)` — bundled `Source Serif 4` + `LXGW WenKai Lite`; editable `<text>` SVG.
- `export_figure(fig, output_dir, *, formats=("png",), dpi=300, inputs=(), map_panels=())` — writes `map.*`, `preview.png`, `manifest.json` (`layout_diagnostics`).
- `get_scientific_cmap(kind="sequential", name=None, *, n=None, reverse=False, zero_anchored=False)` + `build_perceptual_norm(vals)` + `add_continuous_colorbar(..., zero_label=None)`.
- `apply_publication_theme(style="light_geo", font_scale=1.0, *, fig_width=None)` -> `{"fonts": {"T1":16,"T2":14,"T3":12,"T4":10}, "colors": ...}`.
- `add_graticule_frame(ax, *, crs=None, style="ticks_only", dms=True, step_deg=None)` — projected & `GeoAxes` integer DMS ticks.
- `add_scalebar_and_north(ax, *, crs_units="metre", loc="lower left", north=True, north_loc="upper left", scale_style="cartographic", north_style="compass_star")`
- `add_locator_inset(fig_or_ax, bounds, *, shape="rect"|"circle", projection=None, facecolor=GEO_COLORS["ocean_soft"])`
- `add_clean_legend(ax, items, *, title=None, loc="lower left", ncol=1, frameon=False, title_align="center")` — `items`: `[(lbl,hex)]` or `[{"label","color","kind":"patch"|"line"|"marker"}]`.
- `add_leader_callouts(ax, items, *, use_adjust_text=True, fontsize=None, zorder=15)` — `[{"label","xy":(x,y),"xytext":(tx,ty)}]` halo-only leaders.
- `add_flow_arcs(ax, flows, *, value_col=None, directed=False, symmetric=True, bend_outward=True, curvature=0.18, length_scale=True, breaks=None, n_classes=4, lw_range=(0.7,4.2), alpha_range=(0.38,0.94), gamma=0.75, cmap="carto_oryel", colors=None, halo=True, top_n=None, min_value=None, zorder=5.0)` — `flows`: `GeoDataFrame` or `(x0,y0,x1,y1)` DataFrame/`(x0,y0,x1,y1,v)`; returns `{"count","breaks","colors","linewidths","legend_items"}`.
- `add_size_legend(ax, items, *, layout="nested"|"vertical"|"horizontal", title=None, line_items=None, line_title=None, facecolor="#d96f32", edgecolor="#ffffff", alpha=0.85, frameon=True, title_align="center", fontsize=None, title_fontsize=None)` — `items`: `[(lbl, s_pt2)]` or `[{"label","size","color","edgecolor","alpha"}]` (`scatter s`); stacks cleanly with `line_items=flow["legend_items"]` inside one card.
- `attach_marginal_profiles`, `find_quiet_corner`, `rank_quiet_corners`, `add_bivariate_legend`, `bivariate_classify`.

## Further details

- Fisher-Jenks, standalone scripts & `AnchoredSizeBar`: [classification & examples](classification-and-examples.md#fisher-jenks).
