---
name: gis-verification
description: Audit geospatial outputs against external invariants, metamorphic relations, conservation balances, boundary counterexamples, spatial anomaly signals, and honest abstention boundaries. Use whenever multi-step analysis makes consequential claims, deliverables trigger outputs[].anomalies, failures repeat (stagnation_alert), or missing prerequisites require partial/needs_input/blocked disclosure. Skip for simple read-only metadata queries cleanly answered by inspect_data.
compatibility: Core measurement and metamorphic helpers require GeoPandas, Shapely, pandas, and NumPy in GeoPython; precision and validation-split examples run with NumPy or stdlib. Optional host tools (summarize_fields, check_spatial_relation) complement scripts.
---

# GIS verification and honest abstention

Zero exit code proves execution, never semantic correctness. Verify consequential claims using minimal extrinsic evidence (CRITIC / property-based checks), triage `outputs[].anomalies` systematically, and stop honestly via `blocked` or `needs_input` rather than fabricating data or coercing invalid assumptions.

## Core Verification Workflow

1. **Triage automatic spatial signals**: Check `outputs[].spatial` and `outputs[].anomalies` (`ZERO_FEATURES`, `MISSING_CRS`, `ALL_INVALID_OR_EMPTY`, `ALL_NODATA_RASTER`, `CONSTANT_RASTER_SURFACE`, `UNSCALED_HIGH_DN`, `CORRUPT_OR_UNREADABLE`). Never hide fatal errors; repair defects, or confirm expected limitations with `acknowledged_anomalies`.
2. **Choose the smallest extrinsic oracle (never re-read code alone)**:
   - **Conservation & key coverage**: [allocation_balance.py](scripts/allocation_balance.py) and [identity_audit.py](scripts/identity_audit.py).
   - **Metamorphic & boundary properties**: [metamorphic_checks.py](scripts/metamorphic_checks.py) (`check_conservation`, `check_permutation_invariance`, `compare_boundary_predicates`, `check_scale_invariance`).
   - **Geometry & numerical precision**: [geometry_facts.py](scripts/geometry_facts.py) and [precision_example.py](scripts/precision_example.py).
   - **Held-out split leakage**: [validation_split.py](scripts/validation_split.py).
   - **Domain counterexamples**: parallel-edge routing in [parallel_edges.py](../gis-vector-and-network/scripts/parallel_edges.py) and [network-access](../gis-vector-and-network/references/network-access.md); terrain/NoData/cache in [terrain-hydrology](../gis-terrain-and-hydrology/references/terrain-hydrology.md).
3. **Host inspection shortcuts**: Reuse `summarize_fields` (column stats, key nulls/duplicates, geometry checks) and `check_spatial_relation` (foreign-key predicate check) before writing custom audit scripts.
4. **Prevent futile repair loops & honor knowledge limits**: When `stagnation_alert` fires or mandatory inputs/CRS/connections are missing, follow the abstention matrix instead of forcing brittle approximations:
   - Missing user policy/weight choice -> `finish_task(status="needs_input", reason="business_decision"|"missing_input", question=...)`.
   - Physically missing datasets or infeasible task -> immediate `finish_task(status="blocked", ...)` after read-only audit (no dummy writes required).
   - Verified subset alongside unresolved limitations -> `finish_task(status="partial", artifacts=[...], unresolved=[...])`.

## References

- Anomaly triage table, metamorphic check guide, and abstention matrix: [metamorphic & abstention](references/metamorphic-and-abstention.md).
- Detailed claim-specific audit recipes, allocation patterns, precision, and Processing boilerplate: [checks](references/checks.md) and [QGIS execution guide](../../integrations/qgis/execution.md).
