---
name: gis-vector-and-network
description: Execute non-trivial vector workflows (CRS separation, multi-part geometry, overlays, spatial joins with key audits, tile-halo chunking) and directed road-network routing, attachment, OD matrices, facility location, or 2SFCA accessibility. Use when workflows combine multiple operations, touch boundary/multiplicity rules, or model road networks. Skip when a single supplied native QGIS algorithm schema needs no custom join or topology logic.
compatibility: Requires GeoPython (geopandas, shapely, pyogrio, pandas, numpy, scipy, networkx); QGIS Processing required only for Processing chains like reproject_clip.
---

# Vector operations and road networks

Separate storage/analysis/delivery CRSs cleanly, keep spatial join multiplicities explicit, and preserve multi-edge physical topology in road networks.

## Vector Execution Workflow

1. **CRS separation**: `set_crs` edits labels; `to_crs` transforms coordinates. Measure distances, buffers, and areas in an appropriate local metric CRS (UTM/equal-area, avoiding Web Mercator area distortion), and reproject back only for explicit delivery requirements.
2. **Geometry & keys**: Recurse through `Multi*` and `GeometryCollection` parts; keep explicit persisted business keys before overlay/clip/dissolve; rename colliding join columns and assert cardinality (`validate="many_to_one"`).
3. **Predicate, micro-benchmarking, & chunking**: Choose `intersects` vs `within` vs `covered_by` consciously for boundary contacts. When `inspect_data` reports `> 5,000` features or `> 10 MB` complex multi-part geometries, run a `< 10s` micro-benchmark on a small sample or single tile before executing global `buffer`, `unary_union`, or `overlay`; if superlinear growth appears, route immediately to Spatial Index + **Halo buffer** tiling (clip to unbuffered tiles and deduplicate split features by business key) or metric rasterization.

## Road Network Workflow

1. **Primal MultiDiGraph**: Check projected CRS, unique road IDs, legal endpoints, grade levels (no 2D bridge intersections), and directions. Never overwrite parallel edges with `DiGraph.add_edge` or sum duplicate pairs via SciPy `COO->CSR` silently ([parallel_edges.py](scripts/parallel_edges.py)).
2. **Exact attachment & directed search**: Query full edges with `STRtree.query_nearest(all_matches=True)`, split roads at snapped demand/facility terminals cleanly, include demand tail + road + facility tail costs, and run reversed multi-source Dijkstra for directed demand->facility shortest paths. Apply point/line/polygon barriers (`apply_barriers`), Top-K closest search (`closest_k_facilities`), or edge-state turn restrictions/penalties (`build_turn_graph`) via [network_advanced.py](scripts/network_advanced.py) when traffic constraints apply.
3. **Service areas & location models**: For polygon service areas when ArcGIS Network Analyst is absent, prefer Method A Trimmed-TIN isochrones (`trimmed_tin_service_areas` in [service_area_polygon.py](scripts/service_area_polygon.py)) paired with Method B corridor buffers (`corridor_service_areas`) as sensitivity bounds rather than naive global buffers. Use HiGHS MILP (`locate_milp` for `p_median`, `p_center`, `maximum_coverage`, `minimum_facilities`, capacitated/required siting) and `huff_market_share` in [network_location.py](scripts/network_location.py) beyond small enumeration budgets.

## References & Runnable Assets

- Vector CRS, joins, and halo chunking: [vector patterns](references/vector-patterns.md), [reproject_clip.py](scripts/reproject_clip.py), [spatial_join.py](scripts/spatial_join.py).
- Network routing guides & N1-N6 checks: [networks](references/networks.md), [topology](references/network-topology.md), [access](references/network-access.md), [applications](references/network-applications.md).
- Network scripts: [parallel_edges.py](scripts/parallel_edges.py), [network_cases.py](scripts/network_cases.py), [network_access.py](scripts/network_access.py), [service_area_polygon.py](scripts/service_area_polygon.py), [network_location.py](scripts/network_location.py), [network_advanced.py](scripts/network_advanced.py).
- Rounding & precision rules: [numerical precision](../gis-verification/references/checks.md#numerical-precision).
