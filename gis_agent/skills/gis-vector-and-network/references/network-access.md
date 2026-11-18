# Attachment, costs and evidence

Query full eligible line geometries with STRtree.query_nearest(all_matches=True,
max_distance=...). Nearest nodes or segment midpoints can miss a long nearby
edge. Filter known mode/level eligibility first. Keep IDs, fraction, projection,
access distance, unmatched and tied candidates. A tie across levels needs an
explicit access policy. This example handles individual points, not GPS tracks.

Collect every position on each physical road before splitting. Preserve keys,
geometry and direction. Only length-proportional costs split by fraction; fixed
tolls or variable speed require another model. Use demand-only outgoing and
facility-only incoming terminals, so multiple entrances cannot bridge roads.

Complete distance = demand access + legal road distance + facility access.
Time needs separately justified speeds/units. Facility access can reverse the
nearest choice. Constant demand access affects thresholds even if it preserves
facility ranking. QGIS point tolerance allows attachment; TRAVEL_COST does not
automatically include off-road tails. Node tolerance is a separate parameter.

For demand->facility costs in a directed graph, search from facilities on the
REVERSED graph. Dijkstra requires nonnegative weights; A* needs a justified
lower bound in the correct units. SciPy min_only reduces repeated searches;
preserve source/node ID mappings and use directed=True for asymmetric costs.
A representative minimizer does not establish uniqueness; state ties_checked.

Distinguish no eligible access, beyond access limit, graph-unreachable and
beyond travel budget. Test asymmetric directions, facility tails and a separate
component. Existence and stored-length agreement cannot prove shortestness;
a cheaper valid alternative falsifies it. Compare under identical assumptions.
Use existing results and a discriminating counterexample before repeating a
whole network calculation. Report unreachable counts and unverified assumptions.

Sources: [Shapely](https://shapely.readthedocs.io/en/stable/strtree.html),
[NetworkX](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.weighted.multi_source_dijkstra.html),
[QGIS](https://documentation.qgis.org/3.44/en/docs/user_manual/processing_algs/qgis/networkanalysis.html),
[SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csgraph.dijkstra.html).
