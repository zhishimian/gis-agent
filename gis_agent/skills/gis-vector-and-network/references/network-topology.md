# Road topology and graph identity

Road geometry requires evidence of legal connectivity. A primal MultiDiGraph
represents trusted endpoints and road segments. Same-level crossings and
T-junctions inside segments require explicit noding. Distinct bridge/tunnel
levels remain disconnected unless a known ramp connects them. STRtree ignores
Z; 2D intersection cannot establish traffic access.

The example builder checks projected CRS, unique road IDs, nonnegative costs,
direction values, simple nonzero LineStrings and explicit nonnull level fields.
It rejects un-noded same-level crossings/overlaps. It uses exact endpoints and
trusted levels; it never infers grade or tolerance-snaps gaps. Missing levels
are an explicit 2D assumption. Source trust and turn restrictions remain external
premises. Estimate intersection-check cost before processing a large dataset.

Graph/DiGraph keep one edge per ordered node pair: add_edge can overwrite cost
and geometry. MultiDiGraph preserves (u,v,key) and physical road identity.
Minimum parallel-edge reduction fits only interchangeable additive arcs; retain
the matching geometry. Mid-edge access, modes, turns and tolls can prevent it.
COO->CSR sums duplicate pairs; explicitly reduce to minimum only where valid.
maximum(transpose) cannot undo the sum. Keep curved lengths after simplification.

Dual graphs represent roads/turn relations and suit angular/morphological
questions; hop count is not metres. Node-edge routing cannot universally express
turn restrictions; use edge-state models or a suitable existing router.

Disconnected components may be real barriers or missing data. Quantify them.
Do not join every component with invented straight lines. Use tolerances only
with precision/scale evidence; compare justified alternatives and retain a link
ledger. Stop where no evidence supports connection.

Sources: [QGIS](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/network_analysis.html),
[momepy](https://docs.momepy.org/en/stable/api/momepy.gdf_to_nx.html),
[OSM restrictions](https://wiki.openstreetmap.org/wiki/Relation:restriction),
[SciPy COO](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.coo_matrix.html).
