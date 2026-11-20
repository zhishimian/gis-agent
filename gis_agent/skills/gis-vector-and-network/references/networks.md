# Network resource guide

Start with the actual claim and costs. Demand-to-facility, reachable roads,
land service polygons, barriers, turn-constrained paths, siting, and gravity capture
are distinct products.

| Need | Read | Executable asset |
| --- | --- | --- |
| Topology, grade, direction, alternatives | [Topology](network-topology.md) | [network_access.py](../scripts/network_access.py) build_primal |
| Exact attachment, costs, shortest paths | [Access](network-access.md) | project_to_edges, split_at_positions, attach_terminals, nearest_facilities |
| Barriers, Top-K closest, turn restrictions | [Topology](network-topology.md) | [network_advanced.py](../scripts/network_advanced.py) apply_barriers, closest_k_facilities, build_turn_graph |
| Service area polygons, MILP siting, Huff & 2SFCA | [Applications](network-applications.md) | [service_area_polygon.py](../scripts/service_area_polygon.py), [network_location.py](../scripts/network_location.py) |
| Minimal failure examples | Run [network_cases.py](../scripts/network_cases.py) without arguments | N1-N6 assertions and facts JSON |

These zero-new-dependency patterns run cleanly across standard GIS Python stacks. Multi-vehicle VRP,
GTFS timetable transit routing, and real-time traffic require dedicated external engines (`OR-Tools`/`PyVRP`,
`r5py`/`OpenTripPlanner`, or live speed feeds). [parallel_edges.py](../scripts/parallel_edges.py) remains a short overwrite example.
