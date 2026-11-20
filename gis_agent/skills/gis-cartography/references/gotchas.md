# Plotting gotchas

- marker does not convert polygons to sites. Inspect geometry types; choose a
  justified centroid/interior point/entrance only when the task permits it.
- Filtered dataframe indices can be nonconsecutive. Use a positional color array
  on the same rows or map by business ID; do not mask NaNs by blind index resets.
- LineCollection does not accept every Line2D argument (for example
  solid_capstyle); use the actual Artist's API. Derive colors/classes/legend from
  one encoding. Keep the requested classification method and original domain.
- Register physical GDB/GPKG paths with export_figure, not GDB/layer pseudo-paths.
  Its metrics report input fingerprint, draw, save and preview time separately.

- GIS libraries live in the configured GIS interpreter; another Python can lack them. Some installations use user-level packages. Check real environment paths when moving machines.
- GeoPandas uses path plus layer, not a QGIS pipe URI. set_crs labels coordinates; to_crs transforms them.
- Higher zorder draws above lower layers. Filled backgrounds can hide the subject. facecolor="none" is transparent; Python None can select a default fill.
- A metric CRS still has projection scale error. Longitude/latitude and Web Mercator distances need appropriate interpretation; an upward arrow may indicate grid north.
- scheme requires mapclassify, which may be absent. Use explicit task thresholds/BoundaryNorm or verify the dependency before using it.
- Keep zero, NoData and NaN separate. Locate nonfinite values; boundaries must cover the maximum and remain strictly increasing.
- Rasterio bounds are left,bottom,right,top. imshow extent is left,right,bottom,top; use plotting_extent. out_shape needs a scaled transform. Use WarpedVRT for rotated grids instead of stretching a bounding box.
- Bilinear resampling mixes categories; use nearest for categorical rasters. A display histogram is not a source-pixel inventory.
- Register fonts each process and inspect missing-glyph warnings. A font file alone does not prove every character is available.
- AnchoredSizeBar.txt_label is a TextArea. Neither set_fontsize nor set_text_props is available in the tested environment. Use fontproperties on the scale bar or edit its Text child; see the [classification and API examples](classification-and-examples.md#composable-library-operations). Silently skipping a nonexistent method does not confirm a style change.
- Keep explicit fig/ax, export that figure, and close it. Do not initialize QGIS/Qt for Matplotlib.
- A file can exist after a failed run; retain the failure rather than accepting partial stdout. Re-read the current image after edits.
- In GIS-Agent an image is visible only to the immediately following model request. Use the preview when the full PNG exceeds reader limits.
- Offline Cartopy environments (`PROJ_NETWORK=OFF`): `cartopy.feature` downloads fail without cached Natural Earth files. Plot supplied local vector layers with `transform=ccrs.PlateCarree()` instead of fetching remote borders.
- Cartopy `GeoAxes` incompatibility with `sharex`/`sharey`: never pass `sharex=geo_ax` directly to `fig.add_subplot`; use `attach_marginal_profiles(..., main_projection=...)` and guard `"geo" in ax.spines` before editing spines.
- Font order: call `configure_plotting()` BEFORE `apply_publication_theme()` so registered CJK and Latin font families remain intact.
- Vector plotting speed & SVG size: NEVER loop `for row in gdf.itertuples(): gpd.GeoSeries([row.geometry]).plot(...)`—a single vectorized `.plot()` is 50-100x faster. Simplify polygon/line layers exceeding `5,000` features and pass `rasterized=True` on ultra-dense background layers so renders stay `< 15 s` and SVGs `< 8 MB`.
- Duplicate tick labels: when placing projected data, call `add_graticule_frame(ax, crs=...)` to replace raw `1e6` metric ticks with DMS labels; never overlay manual `ax.text(..., "8°S")` without clearing default major tick formatters (`duplicate_axis_ticks_warning`).
- Neighbor context visibility: never draw a full-extent opaque white `Rectangle` above background administrative boundaries (`zorder=2` masking `zorder=1` states); keep out-of-scope land `#e8e7e4`–`#f0f0f0` with muted borders visible beneath the study highlight.
- Boxed callout pills: avoid `bbox=dict(boxstyle="round", fc="#ffffff")` on map annotations over thematic fills (`callout_box_warning`); use `add_leader_callouts` with white `path_effects` halos positioned cleanly inside map frame borders (`frame_overflow_warning`).
- Layer occlusion: ALWAYS place national/study-area outlines at `zorder=8` ABOVE overlaid scatter points (`zorder=5-6`) so dots never chop border lines; avoid plotting the study area's own name over its polygon center, unrequested long leader lines, or scalebars in the upper map corners.
- Fractional arcsecond ticks on projected maps: do NOT pass arbitrary metric steps like `step=(1_000_000, 500_000)` to `add_graticule_frame(ax, crs="EPSG:5070")`; omit `step` (or pass `step_deg=(10, 5)`) so `add_graticule_frame` solves exact integer-degree ticks automatically.
- Legend over-engineering & detached zero swatches: never stack both raw counts and `%` shares in one legend block, and use `get_scientific_cmap(..., zero_anchored=True)` + `zero_label=None` for seamless `0`-to-max continuous bars unless zero is a disjoint structural class.
