# Execution patterns

## Routes and data flow

Use the supplied schema for a standard independent algorithm. A batch with reusable intermediates can use Processing; a custom vector/table calculation can use GeoPandas/Shapely. Avoid probing an environment already described by the execution tool.
A file can contain several layers. Use actual layer metadata: QGIS takes `path.gpkg|layername=actual`; GeoPandas takes `read_file(path, layer="actual")`. A layer object stays in its process. Cross-process intermediates need disk paths.

`set_crs` assigns a label; `to_crs` transforms coordinates. Record the source, analysis and requested delivery CRS separately. Matching the unit name does not guarantee suitable distortion. If a requested CRS conflicts with a measurement CRS, transform only where needed and deliver the requested CRS explicitly.

## Geometry and identity

Shapely Polygon exposes `exterior` and `interiors`; MultiPolygon exposes `geoms`. Recurse through Multi* and GeometryCollection for all relevant components. Some collections mix dimensions. Keeping the largest polygon silently changes the object; representative points change the query geometry, so keep original geometry for delivery when required.
PyQGIS `QgsGeometry` and the object returned by `constGet()` have different interfaces. Use the wrapper's `isMultipart()/asMultiPolygon()` or Shapely, and verify the actual type. Never guess wrapper methods on `QgsMultiPolygon`.

Keep a stable business key before operations that rebuild FIDs or reorder rows. Read keys and attributes together, join results by that key, and inspect cardinality before updating the source. Dataset FIDs are storage identifiers; preserving them is unnecessary unless explicitly required.

A GeoPackage primary-key FID may be exposed as an index or omitted from ordinary columns by the reader. Save an explicit business-key attribute before export. A DataFrame index, its zero-based position and a one-based display number are different values; never use them interchangeably for write-back. Keep generated labels alongside their source keys.

After writing an intermediate layer, inspect its actual schema before composing downstream code. Joins can add suffixes, and an upstream edit can invalidate an old field assumption. This example requires one reference row per zone key; a one-to-many task needs a relation ledger instead:

```python
layers = gpd.list_layers(intermediate)
left = gpd.read_file(intermediate, layer=actual_layer)
reference = zones[["zone_key", "name"]].rename(columns={"name": "zone_name"})
joined = left.merge(reference, on="zone_key", how="left", validate="many_to_one")
```

Use the returned layers/columns, choose a nonconflicting output name, and preserve the source business key. A successful merge still needs the task's match/coverage policy.

A spatial join is a relation: zero, one or many matches per source object. Retain unmatched and multiple matches until the task chooses a policy. `intersects` includes boundary contact; point `within` excludes boundary contact; `covered_by` includes it. These predicates do not choose maximum-overlap ownership. Inspect overlap and boundary cases before propagating a relation into calculations.

## Quantities and networks

Write the target quantity and unit before choosing numerator/denominator. Distinguish counts, densities and weights when aggregating a raster. Check one nondegenerate source sample before normalization or ranking; normalization cannot repair an inverted quantity. Keep zero denominators and missing values separate. For calculation, threshold, storage and display precision, use the [precision reference](../../gis-verification/references/checks.md#numerical-precision).

For raster/elevation work, establish pixel-center versus all-touched inclusion, masks/NoData, horizontal CRS and vertical units. Align grids explicitly when needed. A maximum surface elevation and an object's height above its base are different quantities. Derive each field from its specified inputs, and apply required rounding at the stage named by the task.

For networks specify edge versus vertex attachment, access costs, direction and impedance. Connecting to a nearest vertex can change the route compared with splitting the nearest edge. Unreachable objects remain explicit; substitute Euclidean cost only under an agreed interpretation and keep it distinguishable. A connector line's length alone does not encode network cost.

NetworkX Graph/DiGraph store one edge per node pair; adding the same edge updates its attributes. A longer road can overwrite a shorter parallel road, including its geometry, while Dijkstra still returns successfully. Preserve the cost, geometry and road identity together. Choose a minimum-cost edge or MultiGraph/MultiDiGraph from the task's model. Collapsing alternatives is valid only when costs are additive and the roads are interchangeable for this query; attach/split facilities first. Turn restrictions, mode/access rules or road-specific state can require retaining distinct edges.

[parallel_edges.py](../scripts/parallel_edges.py) is a complete synthetic NetworkX example with three nodes. Run it without arguments through run_python_script or Python. It reports the overwritten graph's cost, the minimum-edge graph's cost and the MultiGraph cost. Dependencies: NetworkX and the standard library. It writes JSON to GIS_AGENT_RESULT_PATH when set, otherwise stdout; failures propagate. This is a counterexample, not a road loader, snapping implementation or routing framework. A correct shortest-path routine cannot repair roads lost during graph construction.
The overwritten graph costs 9; both preserved-alternative graphs cost 5 (2 + 3). The shorter road's ID remains attached to its retained cost.

## Complete Processing example

[reproject_clip.py](../scripts/reproject_clip.py) reprojects the source and mask into an explicit analysis CRS, then clips. Requires QGIS Processing and the shared helper. Example settings (replace paths/CRS from the task):

```json
{"source":"/data/input.gpkg|layername=features","mask":"/data/mask.gpkg|layername=boundary","target_crs":"EPSG:3857","output":"/work/clipped.gpkg"}
```

The CRS above is illustrative; select a suitable local CRS for metric measurements. Pass one settings-file path to the script through `run_python_script`. Temporary objects stay inside one job; the final output is a new GeoPackage. Existing outputs fail with nonzero status. Processing failures retain their traceback. Clipping may split IDs; the example does not promise one-to-one identity.

## Complete GeoPandas example

[spatial_join.py](../scripts/spatial_join.py) emits `features.gpkg` with every original source geometry/attribute and `match_count`, plus `matches.csv` with every matched source/reference key pair. It keeps multiplicity; no assignment winner is selected. Requires GeoPandas/Shapely/pandas/NumPy. Both business keys must be nonnull and unique before the join.

```json
{"source":"/data/features.gpkg","source_layer":"objects","reference":"/data/zones.gpkg","reference_layer":"zones","source_key":"object_key","reference_key":"zone_key","output_dir":"/work/join","predicate":"intersects","query_geometry":"geometry"}
```

`query_geometry="representative_point"` is an explicit alternative. `analysis_crs` transforms query copies; delivered source geometry keeps its original CRS. A CRS mismatch without explicit analysis_crs fails. Existing output files, missing keys and null/empty geometry fail. Unknown geometry needs an explicit policy before it can be called unmatched. CSV readers must preserve ID types, including leading zeros; its rows are matches, not a reconstructed source table.
Optional `numerator`, `denominator`, `ratio_field` compute a caller-selected field ratio on source attributes. Choose its units from the task. Undefined ratios remain null and are counted. This is arithmetic machinery, not a domain formula. An input field with the requested output name fails instead of being overwritten.

Run, import, copy or extend examples as useful. For counts, key coverage and semantic evidence, consult [verification](../../gis-verification/references/checks.md).
