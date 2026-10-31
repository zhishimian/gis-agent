# Minimal sufficient evidence

## Reuse host tools first

These GIS-Agent tools are optional in other hosts; use their supplied schemas. Existing tools already cover the following facts:

```json
{"tool":"inspect_data","arguments":{"source":"/data/result.gpkg"}}
{"tool":"summarize_fields","arguments":{"source":"/data/result.gpkg|layername=objects","fields":["value"],"key":"object_key","check_geometry":true}}
{"tool":"check_spatial_relation","arguments":{"source":"/data/result.gpkg|layername=objects","reference":"/data/zones.gpkg|layername=zones","foreign_key":"zone_key","reference_key":"zone_key","relation":"intersects"}}
```

Call the named tool with its arguments; these envelopes are examples, not a new API. inspect_data returns container layers or vector/raster metadata in `data`; batches return `data.datasets` with per-item status. summarize_fields reports full-column statistics, key null/duplicate counts and optional empty/invalid geometry in `result`; samples are at most the first five rows and may all be zero. Numeric sum does not prove a formula or assignment.
check_spatial_relation measures `source relation reference`. Both CRSs must be valid and equal; reference keys must be unique. It counts missing keys, empty geometry and violations, but cannot find source objects already dropped. Measuring full-footprint intersects also does not certify a representative-point assignment policy.

## Select an independent failure signal

| Risk | Sufficient starting evidence | What remains uncertain |
| --- | --- | --- |
| Formula/units | Target quantity, raw fields/units and one nondegenerate substitution; distinguish null and zero denominator. | Normalized range and rankings do not prove direction. |
| Identity after joins | Source/result coverage and multiplicities; then a few meaningful spatial/attribute counterexamples. | Equal ID sets can still have wrong assignments. |
| Multipart geometry | Types, all relevant components/holes, valid CRS and selected quantitative facts. | Validity and area alone do not prove the requested operation. |
| Network approximation | Attachment model, direction, impedance and unreachable count; test an edge-midpoint or disconnected case. | Easy samples do not validate all approximations; straight-line display length is not network cost. |

Match the evidence to the claim:

- A feasible route whose length equals its stored cost may still be longer than an alternative. For a shortest-route claim, inspect parallel-edge preservation and compare one consequential source/destination against a candidate alternative or another suitable routing implementation. The [parallel-edge counterexample](../../gis-spatial-analysis/scripts/parallel_edges.py) demonstrates this gap. Use the same direction, attachment and impedance semantics.
- A normal-looking field range can survive an inverted formula. Substitute raw fields into a nondegenerate case and check the intended quantity/unit.
- Population totals remain unchanged if two source IDs exchange spatial assignments. Combine conservation with keyed source/result and location checks where assignment matters.
- Valid geometries can still use the wrong spatial predicate or omit a required part. Inspect a boundary/multipart counterexample chosen from the task.

An alternative that is cheaper disproves a claimed optimum; failing to find one in a sample does not prove global optimality. Start with a discriminating case, widen only when necessary, and report the checked scope. Avoid rebuilding every stage merely to repeat the same assumptions.

A failed assumption should be checked before its results enter dependent ranking/selection/maps. Prefer one discriminating example to a second full pipeline. Do not start a cross-engine replica just to demonstrate diligence.

## Prediction and terrain evidence

For interpolation, inspect the actual IDs used for fitting, tuning and final scoring. Disjoint training/test IDs alone are insufficient if test errors selected the winning method. Verify the selection history and training-only tuning. State the number of valid/excluded evaluation observations, units and missing-prediction policy alongside RMSE. Low residuals at fitted samples do not establish prediction accuracy. [validation_split.py](../scripts/validation_split.py) is a runnable synthetic selection-leakage counterexample; it needs only Python's standard library, takes no arguments and writes JSON to GIS_AGENT_RESULT_PATH or stdout. Errors propagate. It demonstrates a protocol error without estimating general interpolation performance.

For registration, request actual correspondence evidence, transform model, residual units and independent checkpoint coverage. An attractive overlay or matching center cannot establish geographic truth. If correspondence is unknown, mark dependent measurements UNKNOWN; record the boundary of usable independent work.

For catchments, challenge a nested outlet pair. Complete upstream areas can overlap; partition labels cannot directly supply every outlet's full area. Compare to compatible flow accumulation, including the self-cell and grid-area conventions. For profiles, slope and volume, check which DEM was used and whether filling changed the relevant elevations. Inspect NoData at borders and bilinear neighborhoods; a valid raster CRS does not certify its elevation semantics.

The shared [terrain reference](../../gis-spatial-analysis/references/terrain-imagery.md) contains execution details and a tiny runnable counterexample. These checks establish specific failure signals; they do not certify an entire basin or storage calculation. Prefer a consequential counterexample and coverage facts before duplicating a complete pipeline.

## Numerical precision

Keep four decisions separate: the stored source precision, calculation precision, comparison precision/tolerance, and required output/display precision. Casting a Float32 to Python float preserves that stored value but cannot recover information already lost in the source. Accumulate means in a suitable dtype when necessary. Round a required intermediate field only when the task defines that stage; retain other raw extrema for later calculations.

For example, a task may define a rounded base elevation while leaving a surface maximum unrounded. Compute height from that base and the raw maximum, then round the final height if requested. Rounding the maximum first can change the result. A rounded display column also cannot substitute for the original values in a spatial threshold test unless the task defines that quantization. Choose units and any tolerance from the measurement model; there is no universal number of decimals.

[precision_example.py](../scripts/precision_example.py) demonstrates both failures with synthetic Float32 values. Run without arguments through run_python_script or Python; NumPy is required. It returns source values, raw/early-rounded differences and opposite threshold decisions. JSON goes to GIS_AGENT_RESULT_PATH when set, otherwise stdout; exceptions propagate. The numbers illustrate binary arithmetic only and impose no elevation unit, formula or tolerance on a real task.
Its stored maximum is about 12.34500027 and its defined base is 2.11: rounding the final raw difference gives 10.24; rounding the Float32 maximum first gives 10.23. A stored distance just above 100 fails a <=100 test, while its two-decimal display incorrectly passes if reused for comparison.

## Cross-version identity helper

[identity_audit.py](../scripts/identity_audit.py) fills the coverage gap: nulls, duplicate rows, lost/new keys and actual shared multiplicities such as `1:2`. Requires GeoPandas/pandas; reads attributes only. It makes no one-to-one policy or spatial correctness claim.

```json
{"source":"/data/before.gpkg","source_layer":"objects","result":"/data/after.gpkg","result_layer":"objects","key":"object_key","examples":5}
```

`result_key` allows a renamed key. All rows are counted; examples are bounded (0-50). String IDs retain leading zeros. Type changes are reported, not normalized. A deliberate split or filter may explain counts; the model must compare them with the task. Missing fields or unreadable data raise errors.

## Selected geometry facts helper

[geometry_facts.py](../scripts/geometry_facts.py) fills the multipart/distance gap. Requires GeoPandas/Shapely/NumPy. It reports type, null/empty/valid status, recursive leaf and polygon counts, holes and bounds. For projected data it also reports planar XY area/length. `measure_crs` explicitly reprojects selected objects; units come from CRS axes. Geographic input gets type/topology only. Projection suitability still needs judgment.

```json
{"source":"/data/result.gpkg","layer":"objects","key":"object_key","ids":["sample-key"],"limit":5,"reference":{"source":"/data/reference.gpkg","layer":"anchors","key":"anchor_key","value":"chosen-anchor"}}
```

The reference must select exactly one valid nonempty feature. Distance includes all components, with no early rounding. Polygon-boundary distance is separate from geometry distance. Vertex distance minima/maxima include all rings and closure vertices; they do not certify the entire boundary or a circular buffer. GeometryCollection is traversed for part/hole facts; no universal collection-boundary metric is inferred. Invalid geometries receive topology facts without unsafe quantitative claims.
Null and empty geometry remain explicit. `limit` (1-50) bounds measured rows; IDs not found are visible through selected/measured counts, not silently certified. These facts describe a sample, not a full-dataset proof.

## Execution and stopping

Each helper accepts one JSON settings-file argument through run_python_script, writes JSON to GIS_AGENT_RESULT_PATH and preserves exceptions/nonzero exits. Other hosts can import the functions or configure that output environment variable. Only necessary custom Processing checks use the [shared execution reference](../../../integrations/qgis/execution.md).
Record object/sample, observation, scope and PASS/FAIL/UNKNOWN briefly. Keep original precision for comparisons and apply a task-appropriate tolerance. Null measurements, an unresolved execution error or a wrong semantic assumption prevent claiming that requirement has passed. Stop once evidence is sufficient; presentation files and evidence registration are not prerequisites.
