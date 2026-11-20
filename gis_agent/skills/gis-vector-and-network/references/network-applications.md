# Applications and computational scope

## Service Area Polygons (Methods A / B / C)

QGIS native `native:serviceareafromlayer` and `grass:v.net.iso` return reachable road arcs (`OUTPUT_LINES`) and nodes rather than ArcGIS Network Analyst `Detailed Polygon` isochrone polygons. Use [service_area_polygon.py](../scripts/service_area_polygon.py) (zero new dependencies) to convert `reachable_arcs` and vertex travel costs into comparable land polygons:
- **Method A (default recommended — Trimmed-TIN isochrones)**: Call `densify_reachable_samples` followed by `trimmed_tin_service_areas(..., trim_m=500.0, corridor_floor_m=100.0)`. Uses `scipy.spatial.Delaunay` + `matplotlib.tri.Triangulation` masking triangles whose longest edge exceeds `2 * trim_m` (excluding roadless lakes/farmland gaps) while unioning a `corridor_floor_m` buffer around `reachable_arcs` so isolated rural spurs stay covered. Disclose explicitly that results use an open-source Trimmed-TIN equivalent rather than ArcGIS Network Analyst.
- **Method B (corridor sensitivity control)**: Call `corridor_service_areas(reachable_lines, thresholds, corridor_m=...)` for direct along-road strip coverage or upper/lower sensitivity bounds alongside Method A.
- **Method C (macro concave envelope)**: Call `clustered_concave_service_areas` (`cKDTree` connected components + `shapely.concave_hull`) for coarse regional overviews.

## Facility Location, MILP, Huff Gravity & 2SFCA

Construct an OD matrix with stable demand/candidate IDs, units, and direction. Network detours can reverse Euclidean site choices. Keep infinite OD entries unreachable; zero weights must not create `0 * inf` NaNs. Deliver actual point/entrance geometry when requested, not only selected zone polygons.

[network_location.py](../scripts/network_location.py) provides:
- `locate(costs, weights, p, objective, threshold)` for tiny matrices (`<= 100,000` combinations via enumeration) automatically delegating to `locate_milp` beyond enumeration limits or when constraints are present.
- `locate_milp` (`scipy.optimize.milp` / HiGHS) supporting `p_median`, `p_center`, `maximum_coverage`, `minimum_facilities` (location set covering), `capacities`, and `required_sites`.
- `huff_market_share(costs, attractiveness, beta=2.0, ...)` for probabilistic gravity market capture over reachable candidates.

2SFCA uses capacity and competing demand: `R_j = S_j / sum(P_k within threshold)`, then `A_i = sum(R_j for reachable facilities)`. Declare supply units, direction, threshold, and decay. Missing capacity prevents capacity-based conclusions.

## Scope Boundaries (External Engines)

Native zero-dependency solvers handle service areas, OD matrices, Top-K closest facilities, point/line/polygon barriers, edge-state turn penalties/restrictions, MILP facility location, Huff capture, and 2SFCA. For **multi-vehicle VRP fleet routing**, use `OR-Tools` or `PyVRP`; for **GTFS transit timetable routing**, use `r5py` or `OpenTripPlanner`; for **live/time-dependent traffic**, integrate an external dynamic speed feed.

Estimate graph/attachment size, OD bytes, and search counts before executing large OD runs. Persist costly stable preparation before volatile export; see [staged Python](../../gis-data-io-and-staging/references/staged-python.md).

Sources: [OSMnx](https://osmnx.readthedocs.io/en/stable/user-reference.html), [spopt](https://pysal.org/spopt/notebooks/p-median.html), [SciPy MILP](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html), [Wang and Luo](https://www.niu.edu/landform/papers/Wang_Luo2005.pdf).
