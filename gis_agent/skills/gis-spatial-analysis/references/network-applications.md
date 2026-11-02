# Applications and computational scope

Service areas start with reachable full and partial directed road arcs.
Buffering/hulling those arcs creates an approximate land polygon; it does not
prove access to every enclosed parcel. Network Voronoi partitions network cost;
dissolving administrative zones by a selected facility expresses those units.
reachable_arcs returns road geometry with proportional costs, no land polygon.

Construct an OD matrix with stable demand/candidate IDs, units and direction.
p-median minimizes weighted total cost, p-center minimizes worst active-demand
cost, maximum coverage maximizes covered demand under a threshold and budget.
Network detours can reverse Euclidean site choices. Keep infinite OD entries
unreachable; zero weights must not create 0*infinity NaNs. Deliver actual point/
entrance geometry when requested, not only selected zone polygons.

[network_location.py](../scripts/network_location.py) enumerates tiny matrices
only (at most 100000 combinations). JSON settings contain costs, weights, p,
objective and optional threshold; null costs mean unreachable. Invalid and
infeasible cases raise. Returned column indices need mapping back to IDs and
coordinates. For larger problems use mature existing optimization libraries.

2SFCA uses capacity and competing demand: R_j=S_j/sum(P_k within travel threshold),
then A_i=sum(R_j for reachable facilities). Declare supply units, direction,
threshold and decay. Missing capacity prevents capacity-based conclusions.
Dynamic traffic, transit timetables and turns require appropriate extra models.

Estimate graph/attachment size, OD bytes and search counts. Nearest queries
usually fit reverse multi-source; threshold questions fit cutoffs. Persist a
costly stable preparation before volatile export; see [staged Python](staged-python.md).

Sources: [OSMnx](https://osmnx.readthedocs.io/en/stable/user-reference.html),
[spopt](https://pysal.org/spopt/notebooks/p-median.html),
[Wang and Luo](https://www.niu.edu/landform/papers/Wang_Luo2005.pdf).
