# Plotting API and complete examples

Use run_python_script in GIS-Agent. In Codex/Claude Code, use the configured GIS Python interpreter with this checkout on PYTHONPATH, and set GIS_AGENT_RESULT_PATH to a writable JSON result file. No model-specific invocation is required. The environment supplies Matplotlib, GeoPandas and Rasterio; do not assume another Python shares them. Dependencies are listed in [requirements](../../../integrations/plotting/requirements.txt). No new packages are needed by these examples.

```python
import geopandas as gpd
from gis_agent.integrations.plotting.runtime import MapPanel, configure_plotting, export_figure
configure_plotting()
import matplotlib.pyplot as plt

data = gpd.read_file(source, layer=actual_layer)
fig, ax = plt.subplots(figsize=(7, 6), layout="constrained")
try:
    data.plot(ax=ax, color="#b8dce8", edgecolor="#326d87", zorder=1)
    ax.set_aspect("equal")
    ax.set_axis_off()
    export_figure(fig, output_dir, inputs=(source,),
                  map_panels=(MapPanel("main", ax, data.crs.to_string()),))
finally:
    plt.close(fig)
```

configure_plotting(font_files=None) sets Agg and registers explicit fonts. It uses GIS_AGENT_FONT_FILES when configured, raises on missing paths, and supports Chinese when the font contains the glyphs. PDF uses TrueType; SVG defaults to glyph paths. Each process initializes its fonts.
export_figure(fig, output_dir, *, formats=("png",), dpi=300, inputs=(), map_panels=()) writes map.png/svg/pdf, preview.png and a manifest. It also writes structured JSON to GIS_AGENT_RESULT_PATH. Returned files/preview/manifest/artifacts are actual paths. Preview longest edge is at most 1800 pixels; the original canvas is preserved.
MapPanel(name, axes, crs) records map axes and their declared display CRS; bounds are xmin,ymin,xmax,ymax. Statistics axes need no MapPanel. The manifest records hashes, environment/fonts and Artist zorder, not the semantic truth of plotted data. For several maps use separate directories and collect results, since the last export replaces the structured result.

## Executable settings

Every example accepts one JSON settings-file path as its argument, writes through export_figure, and preserves traceback/nonzero failures. Inputs are real files with explicit layer names. Examples require known nonempty CRS; do not overwrite source data. Output folders should be dedicated to the render. Defaults illustrate usage, not a required style.

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
                      fontproperties=FontProperties(size=9))
ax.add_artist(bar)
```

TextArea is a container, not a Text artist; it has neither set_fontsize nor set_text_props in the tested environment. To edit an existing label, obtain its Text child through txt_label.get_children() and set that artist's font. A hasattr guard that skips an unsupported method leaves the original font unchanged. Keep the task's coordinate units and a useful scale length.
