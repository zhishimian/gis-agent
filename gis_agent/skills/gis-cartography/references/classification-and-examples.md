# Fisher-Jenks Classification, Executable Examples & Composable Details

## Fisher-Jenks

[classify_values.py](../scripts/classify_values.py) requires pinned `jenkspy` 0.4.1 in the actual GIS interpreter. `classify_values(values, k=5)` returns `lower`, `upper_bounds`, positional `labels` (`-1` for missing), `counts`, `effective_k`, and fit metadata. First interval is closed; later intervals are left-open/right-closed.
Use the SAME labels for colors and counts, and `legend_labels` for legend text.
Do not deduplicate a repeated minimum break: it may represent a singleton class.
Constant input has one class. Zero stays valid; nonfinite values are missing.
Integer observations outside exact Float64 precision are rejected; preserve source precision before classification. Business IDs should remain separate.
Above the explicit fitting budget, opt into `sample_size` with reported seed and approximation, or select a suitable exact method. No log-domain substitution.
[choropleth.py](../scripts/choropleth.py) accepts `method="fisher_jenks"`, `k`, and optional `sample_size` instead of manual breaks. Explicit-break and continuous modes remain available.
When importing an example from another directory, put its `scripts` directory on `sys.path`; controlled jobs must declare `classify_values.py` as a helper dependency.

## Executable settings

Every example accepts one JSON settings-file path as its argument, writes through `export_figure`, and preserves traceback/nonzero failures. Inputs are real files with explicit layer names. Examples require known nonempty CRS and never overwrite source data. Output folders should be dedicated to the render. Defaults illustrate usage, not a required style.

[publication_composite.py](../scripts/publication_composite.py):
```json
{"output_dir":"/work/composite","style":"light_geo","formats":["png","svg"]}
```
Runs offline from synthetic data (or defaults when invoked with no argument) showcasing `attach_marginal_profiles`, `bivariate_classify`, `add_bivariate_legend`, circular `add_locator_inset`, `add_leader_callouts`, `add_scalebar_and_north`, even-integer `theme["fonts"]`, and `layout_diagnostics`.

[vector_map.py](../scripts/vector_map.py):
```json
{"area_path":"/data/areas.gpkg","area_layer":"areas","point_path":"/data/points.gpkg","point_layer":"points","output_dir":"/work/overlay","title":"Study area"}
```
Optional `scale_length` is in metres and requires an appropriate local metric projection. The script reprojects points to the area CRS and draws them above areas. Geographic aspect is an approximate local display; adapt it for wide/polar extents.

[choropleth.py](../scripts/choropleth.py):
```json
{"source":"/data/areas.gpkg","layer":"areas","field":"value","unit":"task unit","output_dir":"/work/values","breaks":[0,10,20],"colors":["#dbe9f3","#3776a4"]}
```
Breaks must be finite, strictly increasing, and cover valid values; the last interval includes its upper bound. Omit `breaks`/`colors` for a continuous colorbar. Zero is a valid value; missing values get a separate symbol. Nonfinite values fail. `encoding.json` records actual class counts. A density/rate and a total need different semantic justification before choosing choropleth encoding.

[raster_composite.py](../scripts/raster_composite.py):
```json
{"raster_path":"/data/surface.tif","point_path":"/data/points.gpkg","point_layer":"points","display_crs":"EPSG:3857","output_dir":"/work/raster"}
```
Uses masked band 1, `WarpedVRT`, a bounded display sample, inset, and histogram sharing a norm. Optional `bounds` are `left,bottom,right,top` in display CRS. Bilinear resampling suits continuous surfaces; adapt to `nearest` for categorical data. The histogram describes sampled display pixels, not full-raster totals. All-NoData windows fail. Rotated/reprojected grids are handled through the VRT and correctly scaled transform.

## Composable library operations

Use `gpd.list_layers(path)`, `gpd.read_file(path, layer=actual)`, and `to_crs(display_crs)`. `Patch`/`Line2D` build explicit legends; `Normalize`/`BoundaryNorm` share the map's mapping with its colorbar/legend. Point `markersize` and `scatter` `s` are areas in `pt^2`.
`AnchoredSizeBar(ax.transData, length, label, ...)` uses data-coordinate length; it needs projection scale and unit justification. Up can mean grid north, so label true north only with a justified orientation. Raster `imshow` extents come from `rasterio.plot.plotting_extent`. Downsampling also changes transform.

For manual `AnchoredSizeBar` text (when not using `add_scalebar_and_north`), supply `FontProperties` at construction:

```python
from matplotlib.font_manager import FontProperties
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar

bar = AnchoredSizeBar(ax.transData, length, label, "lower left",
                      fontproperties=FontProperties(size=10))
ax.add_artist(bar)
```

`TextArea` is a container, not a `Text` artist; it has neither `set_fontsize` nor `set_text_props` in the tested environment. To edit an existing label, obtain its `Text` child through `txt_label.get_children()` and set that artist's font. Dependencies, including `jenkspy` for fitted classification, are listed in [requirements](../../../integrations/plotting/requirements.txt).
