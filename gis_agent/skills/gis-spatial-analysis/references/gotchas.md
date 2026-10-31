# Execution gotchas

| Symptom | Action |
| --- | --- |
| `processing` cannot be imported | Use the configured GIS interpreter and [run_processing](../../../integrations/qgis/execution.md). Its initialization sets the actual plugins path. |
| INPUT missing or parameter type conflict | Read the current schema/help. Preserve original spelling and case; provider conventions differ. CLI expression strings may not fit a typed tool schema. |
| GeoPackage layer not found | Enumerate actual layers and reuse returned outputs. A filename, alias and layer name can differ. |
| MultiPolygon has no exterior | Traverse all required components and holes. GeometryCollection can mix types. See patterns; geometry_facts measures these without guessing APIs. |
| `QgsMultiPolygon.isMultipart` fails | That method belongs to QgsGeometry. Do not copy wrapper methods onto constGet objects. |
| New FID points to an old object | Recover the original business key; check multiplicities and spatial relations. Do not use row positions or regenerated FIDs for write-back. |
| `fid` disappears after a GeoPackage read | The driver may expose its primary key separately from attributes. Use an explicit persisted business key and inspect the returned columns. |
| A numbered lookup yields null or shifts objects | Distinguish index labels, zero-based positions and one-based labels. Map by a stable key, not by adding offsets across unrelated tables. |
| A guessed joined field is missing | Inspect actual saved layers/columns; merge may create `_x`/`_y`. Select or rename colliding fields before merging and choose an appropriate cardinality check. Recheck after upstream schema edits. pandas itertuples may also rename unsuitable field names. |
| Routes exist but are longer than a known alternative | Check whether Graph.add_edge overwrote a parallel road's weight/geometry. See [parallel_edges.py](../scripts/parallel_edges.py); shortest-path success does not certify the input graph. |
| A boundary match changes after reprojection | Floating-point round trips can move an exact boundary point slightly. Inspect original/analysis coordinates and predicate semantics; choose any tolerance or snapping policy explicitly. Do not round or buffer silently. |
| Data exists but exit is 3221225477 | A local reproduction showed global layers surviving application cleanup. Keep objects in job scope and use run_processing; retain original errors. Other native causes still require diagnosis. |
| Check returns null measurements | A successful process may have skipped a geometry branch. Inspect coverage and actual values before accepting the claim. Do not convert API exceptions to null silently. |
| Holdout error keeps improving during method selection | That set has become validation data. Tune within training and reserve untouched evaluation observations; see [terrain and imagery](terrain-imagery.md). |
| An ungeoreferenced image aligns after matching centers | Visual coincidence supplies no control/check points. Keep the candidate uncertain and its downstream measurements conditional. |
| Downstream basin is unexpectedly smaller than accumulation | Check whether multiple outlet seeds partitioned nested complete catchments. |
| A profile has extreme dips or edge slopes approach vertical | Apply actual validity masks to every interpolation/derivative contributor. Inspect original versus filled terrain. |
| A long interpolation produces only a file header | Inspect source/target sizes and algorithm complexity before rerunning. A file header is incomplete; reuse only validated intermediate outputs. |

Fix the affected computation and dependent results. Reuse unchanged valid work. `os._exit(0)` bypasses cleanup and cannot certify a repair.
