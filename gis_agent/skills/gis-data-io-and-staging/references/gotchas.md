# Execution gotchas

For backend errors see [data I/O](data-io.md). For repeated expensive prefixes see [staged Python](staged-python.md). Routing topology, COO duplicate sums, and access-cost failures belong in [network guide](../../gis-vector-and-network/references/networks.md).

| Symptom | Action |
| --- | --- |
| `processing` cannot be imported | Use the configured GIS interpreter and [run_processing](../../../integrations/qgis/execution.md). Its initialization sets the actual plugins path. |
| `INPUT` missing or parameter type conflict | Read the current schema/help. Preserve original spelling and case; provider conventions differ. |
| GeoPackage layer not found | Enumerate actual layers (`pyogrio.list_layers`) and reuse returned outputs. A filename, alias, and layer name can differ. |
| `PROJ_LIB` / `PROJ_DATA` mismatch (`DATABASE.LAYOUT.VERSION.MINOR`) | Avoid hardcoding another software's external `PROJ_LIB` in Python scripts; let `rasterio`/`pyproj` or the QGIS launcher manage its own bundled `proj.db`. |
| `MultiPolygon` has no `exterior` | Traverse all components and holes (`geoms`); `GeometryCollection` can mix dimensions. |
| `QgsMultiPolygon.isMultipart` fails | That method belongs to `QgsGeometry`. Do not copy wrapper methods onto `constGet()` objects. |
| New `FID` points to an old object | Recover the persisted business key; check multiplicities and spatial relations instead of row position or regenerated `FID`. |
| `fid` disappears after a GeoPackage read | The driver may expose its primary key separately from attributes. Use an explicit persisted business key and inspect returned columns. |
| Numbered lookup shifts objects | Distinguish index labels, zero-based positions, and one-based labels. Merge on a stable key. |
| Guessed joined field is missing | Inspect actual saved layers/columns; merge creates `_x`/`_y` on collisions. Rename colliding columns before merging and validate join cardinality. |
| Routes exist but exceed known shortest path | Check whether `DiGraph.add_edge` overwrote parallel links or SciPy COO summed duplicates. See [parallel_edges.py](../../gis-vector-and-network/scripts/parallel_edges.py). |
| Boundary match changes after reprojection | Floating-point round trips can move an exact boundary point slightly. Inspect original/analysis coordinates and choose predicate (`intersects` vs `within` vs `covered_by`) explicitly. |
| Process exits with `3221225477` on cleanup | Keep PyQGIS layers/writers inside job scope and use `run_processing`; preserve real tracebacks rather than masking cleanup. |
| Holdout error keeps dropping during selection | That set has become validation data. Tune inside training/spatial blocks and isolate evaluation data. See [spatial stats](../../gis-spatial-statistics/references/spatial-stats.md). |
| An ungeoreferenced image aligns visually | Matching centers supplies no control/check points. Keep alignment uncertain and downstream stats conditional. See [raster imagery](../../gis-raster-and-imagery/references/raster-imagery.md). |
| Downstream basin is smaller than accumulation | Multiple simultaneous outlet seeds partition inter-outlet areas instead of returning complete nested upstream catchments. See [terrain and hydrology](../../gis-terrain-and-hydrology/references/terrain-hydrology.md). |
| Long interpolation emits only a header | Estimate `source * target` work first, use windowed/chunked blocks, and reuse only reopened, verified stage outputs. |

Fix the affected computation and dependent results. `os._exit(0)` bypasses cleanup and cannot certify a repair.
