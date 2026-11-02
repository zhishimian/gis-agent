"""Small planar network patterns, not a traffic topology repair engine.

Dependencies: GeoPandas, Shapely >=2, NetworkX. Import the functions below;
run network_cases.py for executable inputs, outputs and assertions. Errors raise
ValueError (nonzero CLI exit). Costs are nonnegative, additive and proportional
to length when splitting. Inputs must have trusted, already-noded topology in
a projected CRS. Crossings at distinct explicit levels remain disconnected.
Turn restrictions, snapping tolerances and GPS map matching are outside scope.
"""
import math

import networkx as nx
import numpy as np
import shapely
from shapely.ops import substring


def _cost(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('Costs must be finite and nonnegative')
    return value


def build_primal(lines, *, road_key, direction, cost, level_fields=(),
                 topology='already_noded_endpoints'):
    """Build a MultiDiGraph; direction values: both/forward/backward.

    Reject un-noded same-level intersections and endpoint/interior touches.
    Distinct level attributes are accepted only as caller-supplied facts.
    Missing levels imply an explicit 2D assumption; no automatic noding.
    """
    if topology != 'already_noded_endpoints':
        raise ValueError('Supply trusted already_noded_endpoints topology')
    if lines.crs is None or not lines.crs.is_projected or lines.empty:
        raise ValueError('Nonempty projected line data required; costs use declared CRS units')
    if lines[road_key].isna().any() or lines[road_key].duplicated().any():
        raise ValueError('Unique nonnull road identity required')
    if level_fields and lines[list(level_fields)].isna().any().any():
        raise ValueError('Level attributes must be explicit and nonnull')
    data = lines.reset_index(drop=True)
    for geometry in data.geometry:
        if geometry is None or geometry.geom_type != 'LineString' or geometry.is_empty or not geometry.is_valid or not geometry.is_simple or geometry.length <= 0:
            raise ValueError('Simple nonzero LineStrings required; resolve multipart/degenerate roads explicitly')
    levels = [tuple(row[f] for f in level_fields) for _, row in data.iterrows()]
    tree = shapely.STRtree(data.geometry.to_numpy())
    for i, geometry in enumerate(data.geometry):
        ends = {tuple(geometry.coords[0][:2]), tuple(geometry.coords[-1][:2])}
        for j in tree.query(geometry, predicate='intersects'):
            j = int(j)
            if j <= i or levels[i] != levels[j]:
                continue
            other = data.geometry.iloc[j]
            hit = geometry.intersection(other)
            points = list(hit.geoms) if hit.geom_type == 'MultiPoint' else [hit]
            other_ends = {tuple(other.coords[0][:2]), tuple(other.coords[-1][:2])}
            # Identical physical alternatives need an explicit upstream policy.
            if any(p.geom_type != 'Point' or (p.x, p.y) not in ends & other_ends for p in points):
                raise ValueError('Un-noded intersection/overlap at the same level; resolve topology before routing')
    graph = nx.MultiDiGraph(crs=data.crs.to_string(), topology=topology,
                            assumptions=['2D levels unspecified'] if not level_fields else [])
    roads = {}
    for i, row in data.iterrows():
        rid, geometry = row[road_key], data.geometry.iloc[i]
        d = row[direction]
        if d not in {'both', 'forward', 'backward'}:
            raise ValueError('Direction must be both, forward or backward')
        u = ('xy', *geometry.coords[0][:2], levels[i])
        v = ('xy', *geometry.coords[-1][:2], levels[i])
        record = dict(road_id=rid, geometry=geometry, cost=_cost(row[cost]), u=u, v=v, direction=d)
        roads[rid] = record
        if d in {'both', 'forward'}:
            graph.add_edge(u, v, key=(rid, 'f'), road_id=rid, cost=record['cost'], geometry=geometry)
        if d in {'both', 'backward'}:
            graph.add_edge(v, u, key=(rid, 'b'), road_id=rid, cost=record['cost'], geometry=shapely.reverse(geometry))
    graph.graph['roads'] = roads
    return graph


def project_to_edges(points, edges, *, point_key, edge_key, max_distance):
    """Exact nearest physical lines; return records plus unmatched IDs.

    Filter eligible roads before calling. Preserve ALL tied roads; choosing an
    access policy is the caller's responsibility. Positional indices never act
    as business keys. Distance units are the common projected CRS units.
    """
    if points.crs is None or points.crs != edges.crs or not points.crs.is_projected:
        raise ValueError('Common projected CRS required')
    if not math.isfinite(max_distance) or max_distance <= 0 or edges.empty:
        raise ValueError('Positive finite access limit and nonempty eligible roads required')
    for frame, key in ((points, point_key), (edges, edge_key)):
        if frame[key].isna().any() or frame[key].duplicated().any():
            raise ValueError('Unique nonnull business keys required')
    if any(g is None or g.is_empty or not g.is_valid or g.geom_type != 'Point' for g in points.geometry):
        raise ValueError('Nonempty Point geometries required')
    if any(g is None or g.is_empty or not g.is_valid or g.geom_type != 'LineString' or g.length <= 0 for g in edges.geometry):
        raise ValueError('Nonzero LineStrings required')
    if points.empty:
        return {'matches': [], 'unmatched': [], 'ambiguous': []}
    tree = shapely.STRtree(edges.geometry.to_numpy())
    pairs, distances = tree.query_nearest(points.geometry.to_numpy(), max_distance=max_distance,
                                         all_matches=True, return_distance=True)
    records = []
    for (i, j), distance in zip(pairs.T, distances):
        geometry, point = edges.geometry.iloc[j], points.geometry.iloc[i]
        fraction = float(geometry.project(point, normalized=True))
        projected = geometry.interpolate(fraction, normalized=True)
        records.append({'point_id': points[point_key].iloc[i], 'road_id': edges[edge_key].iloc[j],
                        'fraction': fraction, 'access_distance': float(distance),
                        'x': projected.x, 'y': projected.y})
    counts = {}
    for row in records:
        counts[row['point_id']] = counts.get(row['point_id'], 0) + 1
    return {'matches': records, 'unmatched': [key for key in points[point_key] if key not in counts],
            'ambiguous': [key for key, count in counts.items() if count > 1]}


def split_at_positions(graph, positions, *, cost_model):
    """Return a new graph, splitting all positions together. No fixed tolls.

    positions contains road_id/fraction records. Corresponding forward and
    reverse physical arcs share split nodes; distinct roads retain identity.
    """
    if cost_model != 'length_proportional':
        raise ValueError('Only explicitly length-proportional costs can be split')
    roads = graph.graph['roads']
    fractions = {rid: {0., 1.} for rid in roads}
    for row in positions:
        rid, fraction = row['road_id'], float(row['fraction'])
        if rid not in roads or not math.isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError('Unknown road or invalid fraction')
        fractions[rid].add(fraction)
    result = nx.MultiDiGraph(**graph.graph)
    access_nodes = {}
    for rid, road in roads.items():
        parts = sorted(fractions[rid])
        def node(f):
            return road['u'] if f == 0 else road['v'] if f == 1 else ('on', rid, f)
        for f in parts:
            access_nodes[rid, f] = node(f)
        for a, b in zip(parts, parts[1:]):
            geom = substring(road['geometry'], a, b, normalized=True)
            cost = road['cost'] * (b - a)
            if road['direction'] in {'both', 'forward'}:
                result.add_edge(node(a), node(b), key=(rid, a, 'f'), road_id=rid, cost=cost, geometry=geom)
            if road['direction'] in {'both', 'backward'}:
                result.add_edge(node(b), node(a), key=(rid, a, 'b'), road_id=rid, cost=cost, geometry=shapely.reverse(geom))
    result.graph['access_nodes'] = access_nodes
    return result


def attach_terminals(graph, matches, *, role, cost_per_unit=1.):
    """Add demand-only outgoing or facility-only incoming access arcs.

    Multiple candidates must be approved by the caller (for example a known
    entrance); this function never treats a facility as a road-through node.
    """
    if role not in {'demand', 'facility'}:
        raise ValueError('role must be demand or facility')
    factor = _cost(cost_per_unit)
    result = {}
    for row in matches:
        terminal = (role, row['point_id'])
        road_node = graph.graph['access_nodes'][row['road_id'], row['fraction']]
        result[row['point_id']] = terminal
        u, v = (terminal, road_node) if role == 'demand' else (road_node, terminal)
        graph.add_edge(u, v, cost=_cost(row['access_distance']) * factor, terminal=True)
    return result


def nearest_facilities(graph, demand_nodes, facility_nodes, *, weight='cost'):
    """Demand->facility distances, including explicit terminal access costs.

    One representative minimizer is returned. Ties are not certified unique.
    Supply only known terminal node IDs; graph construction remains a premise.
    """
    if not facility_nodes:
        raise ValueError('At least one facility terminal required')
    for _, _, attributes in graph.edges(data=True):
        if weight not in attributes:
            raise ValueError('Every edge needs an explicit cost')
        _cost(attributes[weight])
    if any(graph.out_degree(node) for node in facility_nodes.values()):
        raise ValueError('Facility terminals must have no outgoing road connections')
    if any(graph.in_degree(node) for node in demand_nodes.values()):
        raise ValueError('Demand terminals must have no incoming road connections')
    reverse_ids = {node: key for key, node in facility_nodes.items()}
    costs, paths = nx.multi_source_dijkstra(graph.reverse(copy=False),
        sorted(reverse_ids, key=repr), weight=weight)
    return [{'demand_id': key, 'facility_id': reverse_ids[paths[node][0]] if node in costs else None,
             'cost': float(costs[node]) if node in costs else None,
             'status': 'reachable' if node in costs else 'unreachable', 'ties_checked': False}
            for key, node in demand_nodes.items()]


def reachable_arcs(graph, origins, budget, *, weight='cost', cost_model):
    """Directed full/partial road arcs within budget; never a land polygon."""
    if cost_model != 'length_proportional':
        raise ValueError('Nonlinear edge costs need a different boundary model')
    budget = _cost(budget)
    for _, _, data in graph.edges(data=True):
        _cost(data[weight])
    distances = nx.multi_source_dijkstra_path_length(graph, list(origins), cutoff=budget, weight=weight)
    records = []
    for u, v, key, data in graph.edges(keys=True, data=True):
        if u not in distances or data.get('terminal'):
            continue
        remaining = budget - distances[u]
        fraction = min(1., remaining / data[weight]) if data[weight] else 1.
        if fraction > 0:
            records.append({'u': u, 'v': v, 'key': key, 'fraction': fraction,
                            'geometry': substring(data['geometry'], 0, fraction, normalized=True)})
    return records
