# Anomaly triage, metamorphic checks, and honest abstention

## Triaging automatic spatial anomaly signals

Host execution attaches objective `outputs[].anomalies` (and `anomalies` on `run_qgis_algorithm`) when spatial outputs show non-standard properties. Treat these as diagnostic signals rather than automatic failures:

| Signal (`code`) | Level | Likely valid explanation | Silent bug to rule out before delivery |
| --- | --- | --- | --- |
| `UNSCALED_HIGH_DN` | `notice` | Integer DN band evaluated directly in scale-invariant ratio (`NDVI`) | Additive-constant index (`SAVI`, `EVI`) run on unscaled `0..10000` integers |
| `PARTIAL_INVALID_GEOMETRY` | `notice` | Legacy input polygons retained untouched for attribute-only reporting | Invalid self-intersections breaking downstream overlay or area calculation |
| `ZERO_FEATURES` | `warning` | Empty filter match is legitimately zero rows for the given constraints | CRS mismatch, wrong layer name, or inverted filter predicate |
| `MISSING_CRS` | `warning` | Local engineering grid or deliberately ungeoreferenced asset | Export writer dropped CRS or intermediate numpy->GeoTIFF omitted `crs=` |
| `ALL_INVALID_OR_EMPTY` | `warning` | None (rarely valid when geometry was requested) | Geometry construction bug or dropped geometry column before export |
| `ALL_NODATA_RASTER` | `warning` | Empty tile in tiled grid cleanly outside data footprint | Clipped outside valid bounds or wrong `nodata` sentinel assignment |
| `CONSTANT_RASTER_SURFACE` | `warning` | Synthetic uniform surface intentionally generated | Band-math integer truncation (`uint8` division -> 0) or collapsed denominator |
| `CORRUPT_OR_UNREADABLE` | `fatal` | Never acceptable for `completed` delivery | Unclosed WAL/GPKG handle, truncated write, or wrong extension |

When a deliverable has a `warning` signal that you verified is expected or inherent to raw inputs:
1. Inspect it explicitly (`summarize_fields` / `inspect_data` or independent script verification), OR
2. Disclose the confirmed limitation clearly in `summary` and list the code in `finish_task(acknowledged_anomalies=[...])`.

## Oracle-free metamorphic and property checks

A script exiting with code 0 does not prove domain correctness. Run fast (`< 2s`), bounded external checks against domain invariants rather than re-reading your own code:

- **Conservation**: verify `expected_total == observed_total + unmatched_total` within tolerance (`check_conservation`). Distinguish zero values from missing/null rows.
- **Permutation invariance**: shuffle input feature order (`check_permutation_invariance`) and verify keyed outputs match; exposes positional `iloc`/FID write-back bugs without needing external ground truth.
- **Boundary predicate contrast**: compare `intersects` vs `within` vs `covered_by` on boundary geometries (`compare_boundary_predicates`) so perimeter points are neither silently included nor dropped without policy.
- **Scale invariance**: test scaling inputs uniformly (`check_scale_invariance`) when working with DN vs reflectance or metres vs kilometres.
- **Small-sample exact oracle**: check `N <= 20` sampled items using brute-force exact logic or an independent engine instead of duplicating the full pipeline.

## Honest abstention and stagnation decision matrix

Stop guessing when evidence fails to converge or prerequisites do not exist:

| Observed condition | Target `finish_task` status | Required fields and rule |
| --- | --- | --- |
| All user goals verified; deliverables clean or anomalies confirmed | `completed` | `artifacts=[...]`, optional `acknowledged_anomalies` + `evidence` |
| Core branch completed reliably; blocked subset remains due to input/tool gap | `partial` | `artifacts=[...]`, `unresolved=[...]`, disclose limitations in `summary` |
| Missing user policy/weight/threshold choice with material impact | `needs_input` | `reason="business_decision"` or `"missing_input"`, clear `question` + options |
| Missing mandatory files/layers, impossible topology, or exhausted repair strategies | `blocked` | `reason="missing_input"` / `"data_quality"` / `"unsupported"` / `"capability_limit"`; allowed immediately after read-only inspection without dummy scripts |

When `business["stagnation_alert"]` warns on repeated identical failures (`warn` or `escalate`), stop minor retries immediately: inspect inputs/schema with read-only probes, switch implementation route via the relevant domain Skill, or report `blocked` / `needs_input` with factual diagnosis.
