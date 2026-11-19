---
name: gis-verification
description: Audit geospatial outputs against external invariants, metamorphic relations, conservation balances, boundary counterexamples, spatial anomaly signals, and honest abstention boundaries. Use whenever multi-step analysis makes consequential claims, deliverables trigger outputs[].anomalies, failures repeat (stagnation_alert), or missing prerequisites require partial/needs_input/blocked disclosure. Skip for simple read-only metadata queries cleanly answered by inspect_data.
compatibility: Core measurement and metamorphic helpers require GeoPandas, Shapely, pandas, and NumPy in GeoPython; precision and validation-split examples run with NumPy or stdlib. Optional host tools (summarize_fields, check_spatial_relation) complement scripts.
---

# GIS verification and honest abstention

Zero exit code proves execution, never semantic correctness. Verify consequential claims using minimal extrinsic evidence (CRITIC / property-based checks), triage `outputs[].anomalies` systematically, and stop honestly via `blocked` or `needs_input` rather than fabricating data or coercing invalid assumptions.

## Pre-Analysis Feasibility Check & Three-Branch Decision

Before writing heavy processing scripts, audit discovered inputs across 4 dimensions (**spatial coverage**, **core entity/indicator presence**, **spatial/temporal granularity**, **key policy/metric ambiguity**) and route cleanly:
1. **Branch 1 — Valid derivation or minor auxiliary gap (Proceed + disclose, never over-refuse)**: Core analytical layers and granularity are valid; only a secondary display boundary is missing (derivable proxy envelope clearly marked) or standard physical/geometric unit derivation applies (e.g., pixel population counts divided by exact pixel area to obtain density). Execute cleanly without interrupting the user and disclose normal bounds in `summary`.
2. **Branch 2 — Partial-coverage / coarse-granularity proxy or policy fork (`needs_input` — preferred collaborative checkpoint)**: Local data covers only a small fraction of the requested region, substitutes coarse national totals for sub-national spatial patterns, or has mutually exclusive policy choices where guessing wastes compute or misleads. Pause *before* heavy computation and invoke `finish_task(status="needs_input", question=...)` presenting (a) observed local data facts, (b) the core gap and potential distortion, and (c) 2 concrete options (supply complete data vs authorize scoped proxy analysis) so the session can resume seamlessly after user reply.
3. **Branch 3 — Wholly infeasible prerequisite (`blocked`)**: Mandatory subject data is entirely missing with no meaningful alternative entry point, or strict original-scope requirements cannot be met. Report immediately via `finish_task(status="blocked", ...)` after read-only inspection (no dummy scripts).

## Core Verification Workflow

1. **Triage automatic spatial signals**: Check `outputs[].spatial` and `outputs[].anomalies` (`ZERO_FEATURES`, `MISSING_CRS`, `ALL_INVALID_OR_EMPTY`, `ALL_NODATA_RASTER`, `CONSTANT_RASTER_SURFACE`, `UNSCALED_HIGH_DN`, `CORRUPT_OR_UNREADABLE`). Never hide fatal errors; repair defects, or confirm expected limitations with `acknowledged_anomalies`.
2. **Choose the smallest extrinsic oracle (never re-read code alone)**:
   - **Conservation & key coverage**: [allocation_balance.py](scripts/allocation_balance.py) and [identity_audit.py](scripts/identity_audit.py).
   - **Metamorphic & boundary properties**: [metamorphic_checks.py](scripts/metamorphic_checks.py) (`check_conservation`, `check_permutation_invariance`, `compare_boundary_predicates`, `check_scale_invariance`).
   - **Geometry & numerical precision**: [geometry_facts.py](scripts/geometry_facts.py) and [precision_example.py](scripts/precision_example.py).
   - **Held-out split leakage**: [validation_split.py](scripts/validation_split.py).
   - **Domain counterexamples**: parallel-edge routing in [parallel_edges.py](../gis-vector-and-network/scripts/parallel_edges.py) and [network-access](../gis-vector-and-network/references/network-access.md); terrain/NoData/cache in [terrain-hydrology](../gis-terrain-and-hydrology/references/terrain-hydrology.md).
3. **Host inspection shortcuts**: Reuse `summarize_fields` (column stats, key nulls/duplicates, geometry checks) and `check_spatial_relation` (foreign-key predicate check) before writing custom audit scripts.
4. **Prevent futile repair loops & timeout thrashing**: When `stagnation_alert` (including merged `:TIMEOUT` signatures) or `efficiency_hint` warns on repeated retries or late-stage polishing loops, stop blind retries immediately: benchmark `< 10s` on a small sample to switch to chunked/rasterized methods, deliver once core deliverables pass verification, or stop honestly via `needs_input` / `blocked` / `partial`.

## References

- Anomaly triage table, metamorphic check guide, and abstention matrix: [metamorphic & abstention](references/metamorphic-and-abstention.md).
- Detailed claim-specific audit recipes, allocation patterns, precision, and Processing boilerplate: [checks](references/checks.md) and [QGIS execution guide](../../integrations/qgis/execution.md).
