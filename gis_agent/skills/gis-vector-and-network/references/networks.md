# Network resource guide

Start with the actual claim and costs. Demand-to-facility, reachable roads,
land service polygons, siting and capacity competition are different products.

| Need | Read | Executable asset |
| --- | --- | --- |
| Topology, grade, direction, alternatives | [Topology](network-topology.md) | [network_access.py](../scripts/network_access.py) build_primal |
| Exact attachment, costs, shortest paths | [Access](network-access.md) | project_to_edges, split_at_positions, attach_terminals, nearest_facilities |
| Service areas, siting and 2SFCA | [Applications](network-applications.md) | reachable_arcs; [network_location.py](../scripts/network_location.py) |
| Minimal failure examples | Run [network_cases.py](../scripts/network_cases.py) without arguments | N1-N6 assertions and facts JSON |

These bounded patterns use existing GIS Python libraries. They do not repair
arbitrary traffic topology or implement turn restrictions/GPS map matching.
[parallel_edges.py](../scripts/parallel_edges.py) remains a short overwrite example.
