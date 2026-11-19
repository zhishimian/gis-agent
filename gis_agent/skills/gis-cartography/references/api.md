# Plotting API, primitives and complete examples

## Fisher-Jenks

[classify_values.py](../scripts/classify_values.py) requires pinned jenkspy 0.4.1
in the actual GIS interpreter. classify_values(values, k=5) returns lower,
upper_bounds, positional labels (-1 for missing), counts, effective_k and fit
metadata. First interval is closed; later intervals are left-open/right-closed.
Use the SAME labels for colors and counts, and legend_labels for legend text.
Do not deduplicate a repeated minimum break: it may represent a singleton class.
Constant input has one class. Zero stays valid; nonfinite values are missing.
Integer observations outside exact Float64 precision are rejected; preserve
source precision before classification. Business IDs should remain separate.
Above the explicit fitting budget, opt into sample_size with reported seed and
approximation, or select a suitable exact method. No log-domain substitution.
choropleth.py accepts method="fisher_jenks", k and optional sample_size instead
of manual breaks. The old explicit-break/continuous modes remain available.
When importing an example from another directory, put its scripts directory on
sys.path; controlled jobs must declare classify_values.py as a helper dependency.

Use run_python_script in GIS-Agent. In Codex/Claude Code, use the configured GIS Python interpreter with this checkout on PYTHONPATH, and set GIS_AGENT_RESULT_PATH to a writable JSON result file. No model-specific invocation is required. Dependencies, including jenkspy for fitted classification, are listed in [requirements](../../../integrations/plotting/requirements.txt). Do not assume another Python shares them.

```python
import geopandas as gpd
from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure
configure_plotting(font_style="sans", svg_editable_text=True)
import matplotlib.pyplot as plt

data = gpd.read_file(source, layer=actual_layer)
fig, ax = plt.subplots(figsize=(8, 6), layout="constrained")
try:
    data.plot(ax=ax, color="#b8dce8", edgecolor="#326d87", zorder=1, gid="study_area")
    ax.set_aspect("equal")
    ax.set_axis_off()
    export_figure(fig, output_dir, formats=("png", "svg"), inputs=(source,),
                  map_panels=(MapPanel("main", ax, data.crs.to_string()),))
finally:
    plt.close(fig)
```

`configure_plotting(font_files=None, *, font_style=None, svg_editable_text=True)` sets Agg, registers bundled SIL OFL open-source and system fonts (`font_style="serif"` [default when neither `font_style` nor `GIS_AGENT_FONT_FILES` is given] uses bundled `Source Serif 4` + `Times New Roman` + `STSong`/`SimSun` + bundled `LXGW WenKai Lite`; `"kaiti"` prioritizes `Source Serif 4` + bundled `LXGW WenKai Lite` + `STKaiti`/`KaiTi`; `"fangsong"` adds `STFangsong`/`FangSong`; `"sans"` uses `Segoe UI` + `Microsoft YaHei` + `Arial` + `LXGW WenKai Lite` fallback). Passing explicit `font_style` always takes precedence over `GIS_AGENT_FONT_FILES`, and `svg.fonttype="none"` preserves editable `<text>` nodes (PDF uses TrueType `42`).
`export_figure(fig, output_dir, *, formats=("png",), dpi=300, inputs=(), map_panels=())` writes `map.png/svg/pdf`, `preview.png` and `manifest.json`. Iterate quickly with `formats=("png",)` during QA; export final `formats=("png", "svg")` once visual checks pass (apply `rasterized=True` on heavy raster layers and simplify dense basemaps slightly so vector SVGs stay compact and fast).
`export_figure` appends `layout_diagnostics` including outer whitespace, typography checks and automated anti-slop hygiene flags:
- `margin_whitespace_ratio`: `{"top", "bottom", "left", "right"}`, `excessive_margin_warning` (`> 0.18`).
- `typography`: `{"font_sizes_pt", "tier_count", "min_font_pt", "max_font_pt", "min_font_height_ratio", "non_even_font_sizes", "small_text_warning", "fragmented_font_tiers_warning", "non_even_font_warning"}`.
- `hygiene`: `{"subtitle_detected_warning", "callout_box_warning", "duplicate_axis_ticks_warning", "clipped_text_warning", "frame_overflow_warning", ...}` — auto-flags stacked subtitles, boxed `bbox` callout pills, raw numeric ticks colliding with hand-placed `°E/W/N/S` labels, clipped text extending past figure bounds, and interior labels/north arrows crossing map panel borders.
MapPanel(name, axes, crs) records map axes and their declared display CRS; bounds are xmin,ymin,xmax,ymax. Statistics axes need no MapPanel. For several maps use separate directories and collect results, since the last export replaces the structured result.

## Cartographic primitives

`gis_agent.integrations.plotting.primitives` exposes composable Axes/Figure helpers with pure-Matplotlib Tier A fallbacks and even-integer typography defaults (`10 / 12 / 14 / 16 pt`):

- `GEO_COLORS`, `list_palettes()`, `get_scientific_cmap(kind="sequential", name=None, *, n=None, reverse=False, nodata_color=GEO_COLORS["nodata_gray"], zero_anchored=False, zero_color=GEO_COLORS["zero_neutral"])` (rejects `jet`/`rainbow`/`hsv`; set `zero_anchored=True` on non-negative continuous fields to blend `#f7f7f7` zero seamlessly into the ramp), `build_perceptual_norm(values, *, vmin=None, vmax=None, positive_only=True, target_median_pos=0.40)` (auto-fits `PowerNorm` gamma for skewed fields so mid-range zones retain rich contrast), `get_palette(name="okabe_ito", n=None)`, `get_bivariate_palette(name="stevens_pinkblue")`, `build_bivariate_palette(c00, c10, c01, c11, n=3)`, `bivariate_classify(x, y, *, bins=3, method="quantile")`.
- `apply_publication_theme(style="light_geo", font_scale=1.0, *, fig_width=None, font_style=None)` — snaps 4-tier fonts `T1..T4` to even integers scaled proportionally to `fig_width` (call AFTER `configure_plotting()`).
- `add_graticule_frame(ax, *, crs=None, style="ticks_only", dms=True, step=None, step_deg=None, labelsize=None)` — `"ticks_only"`, `"minimal_grid"`, `"clean_borderless"` for `Axes` and Cartopy `GeoAxes`; when `step` is omitted on projected or geographic axes, automatically solves clean integer-degree DMS tick locations (`step_deg` overrides angular spacing cleanly without fractional-minute artifacts).
- `add_scalebar_and_north(ax, *, crs_units="metre", lat_center=None, loc="lower left", north=True, north_loc="upper left", scale_style="cartographic", north_style="compass_star", fontsize=None)` — high-craft segmented/ticked scalebar (`box_alpha=0`, haloed labels; prefer lower-zone `loc="lower left"`/`"lower right"`/`"lower center"`) + 8-facet compass-star / sleek-needle / chevron north arrow with aspect correction & spine-safe margins (`gid="scalebar"` / `gid="north_arrow"`).
- `add_locator_inset(fig_or_ax, bounds, *, shape="rect", projection=None, frame_lw=0.75, facecolor=GEO_COLORS["ocean_soft"])` — `"rect"` or `"circle"` inset (`Circle` clipping + `set_box_aspect(1.0)` + `gid="locator_inset"`) for compact provincial/basin macro context alongside a dashed study-area highlight rectangle (keep cleanly standalone without cross-axes connector lines; omit on iconic CONUS/China/Global extents).
- `add_continuous_colorbar(fig_or_ax, mappable=None, *, cmap=None, norm=None, bounds=None, orientation="horizontal", label=None, ticks=None, tick_labels=None, zero_label=None, nodata_label=None, fontsize=None, title_fontsize=None)` — smooth gradient colorbar supporting `Normalize`/`PowerNorm`/`LogNorm`/`TwoSlopeNorm`; pair `zero_anchored=True` with `zero_label=None` for seamless `0`-to-max ramps (`gid="colorbar"`).
- `add_bivariate_legend(fig_or_ax, bounds, colors_grid="stevens_pinkblue", x_label="X", y_label="Y", *, x_ticks=("Low", "High"), y_ticks=("Low", "High"), fontsize=None)` — 3x3 / 5x5 bivariate square (`gid="bivariate_legend"`).
- `add_clean_legend(ax, items, *, title=None, loc="lower left", ncol=1, frameon=False, show_pct=False, nodata_label=None, zero_label=None, fontsize=None, title_fontsize=None, title_align="center", frame_facecolor="#faf9f7", frame_edgecolor="#b8b4ac", frame_lw=0.7, borderpad=0.55, labelspacing=0.45)` — centered bold title & warm framed card option for sidebar legends (`gid="legend"`).
- `add_leader_callouts(ax, items, *, use_adjust_text=True, fontsize=None, transform=None)` — dot anchors + halo-only labels (zero white `bbox` cards) + L-leaders / `adjustText` (`gid="callouts"`).
- `find_quiet_corner(ax, geoms=None, *, raster_mask=None, raster_extent=None, exclude=())` & `rank_quiet_corners(...)` — ranks unoccupied corners (`"lower right"`, `"lower left"`, etc.) for placement of north arrow, scalebar, inset or legend.
- `attach_marginal_profiles(fig, main_spec=None, *, top=True, right=True, ratio=0.20, pad=0.03, main_projection=None)` — aligned top longitude and right latitude axes returning `{"main": ..., "top": ..., "right": ...}`.

```python
from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure
from gis_agent.integrations.plotting.primitives import (
    apply_publication_theme, add_graticule_frame, add_scalebar_and_north,
    add_continuous_colorbar, add_locator_inset, add_clean_legend,
    add_leader_callouts, find_quiet_corner,
)
configure_plotting(font_style="serif", svg_editable_text=True)
import matplotlib.pyplot as plt
theme = apply_publication_theme("light_geo", fig_width=8.5)
# Plot layers with semantic gid="basemap" / "subject", then compose:
add_graticule_frame(ax, crs=gdf.crs, style="ticks_only")
corner = find_quiet_corner(ax, gdf)
add_scalebar_and_north(ax, crs_units="metre", loc="lower right", north_loc="upper right")
inset = add_locator_inset(ax, [0.03, 0.68, 0.24, 0.24], shape="circle")
add_clean_legend(ax, [("Protected forest", "#4D8C57"), ("Road", "#666666")], loc="lower left")
```

## Executable settings

Every example accepts one JSON settings-file path as its argument, writes through export_figure, and preserves traceback/nonzero failures. Inputs are real files with explicit layer names. Examples require known nonempty CRS; do not overwrite source data. Output folders should be dedicated to the render. Defaults illustrate usage, not a required style.

[publication_composite.py](../scripts/publication_composite.py):
```json
{"output_dir":"/work/composite","style":"light_geo","formats":["png","svg"]}
```
Runs offline from synthetic data (or defaults when invoked with no argument) showcasing `attach_marginal_profiles`, `bivariate_classify`, `add_bivariate_legend`, circular `add_locator_inset`, `add_leader_callouts`, `add_scalebar_and_north`, even-integer `theme["fonts"]` and `layout_diagnostics`.

[vector_map.py](../scripts/vector_map.py):
```json
{"area_path":"/data/areas.gpkg","area_layer":"areas","point_path":"/data/points.gpkg","point_layer":"points","output_dir":"/work/overlay","title":"Study area"}
```
Optional scale_length is in metres and requires an appropriate local metric projection. The script reprojects points to the area CRS and draws them above areas. Geographic aspect is an approximate local display; adapt it for wide/polar extents.

[choropleth.py](../scripts/choropleth.py):
```json
{"source":"/data/areas.gpkg","layer":"areas","field":"value","unit":"task unit","output_dir":"/work/values","breaks":[0,10,20],"colors":["#dbe9f3","#3776a4"]}
```
Breaks must be finite, strictly increasing and cover valid values; the last interval includes its upper bound. Omit breaks/colors for a continuous colorbar. Zero is a valid value; missing values get a separate symbol. Nonfinite values fail. encoding.json records actual class counts. A density/rate and a total need different semantic justification before choosing choropleth encoding.

[raster_composite.py](../scripts/raster_composite.py):
```json
{"raster_path":"/data/surface.tif","point_path":"/data/points.gpkg","point_layer":"points","display_crs":"EPSG:3857","output_dir":"/work/raster"}
```
Uses masked band 1, WarpedVRT, a bounded display sample, inset and histogram sharing a norm. Optional bounds are left,bottom,right,top in display CRS. CRS here is illustrative; choose the task's display projection. Bilinear resampling suits continuous surfaces; adapt to nearest for categorical data. The histogram describes sampled display pixels, not full-raster totals. All-NoData windows fail. Rotated/reprojected grids are handled through the VRT and correctly scaled transform.

## Composable library operations

Use gpd.list_layers(path), gpd.read_file(path, layer=actual), and to_crs(display_crs). Patch/Line2D build explicit legends; Normalize/BoundaryNorm share the map's mapping with its colorbar/legend. Point markersize and scatter s are areas in pt².
AnchoredSizeBar(ax.transData, length, label, ...) uses data-coordinate length; it needs projection scale and unit justification. Up can mean grid north, so label true north only with a justified orientation. Raster imshow extents come from rasterio.plot.plotting_extent. Downsampling also changes transform.

For scale-bar text, supply FontProperties at construction:

```python
from matplotlib.font_manager import FontProperties
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar

bar = AnchoredSizeBar(ax.transData, length, label, "lower left",
                      fontproperties=FontProperties(size=10))
ax.add_artist(bar)
```

TextArea is a container, not a Text artist; it has neither set_fontsize nor set_text_props in the tested environment. To edit an existing label, obtain its Text child through txt_label.get_children() and set that artist's font. A hasattr guard that skips an unsupported method leaves the original font unchanged. Keep the task's coordinate units and a useful scale length.
