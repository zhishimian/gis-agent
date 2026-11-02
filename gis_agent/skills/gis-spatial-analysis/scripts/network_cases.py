"""Run N1-N6 synthetic network examples and mathematical counterexamples.

Dependencies: GeoPandas/Shapely/NetworkX/NumPy/SciPy. No input files/network.
CLI: python network_cases.py; emits facts JSON to stdout and optional
GIS_AGENT_RESULT_PATH. Assertions or invalid inputs exit nonzero. Import and
adapt the patterns for real data only after checking topology/access premises.
"""
import json
import os
from pathlib import Path

import geopandas as gpd
import networkx as nx
from scipy.sparse import coo_matrix
from shapely.geometry import LineString, Point

from network_access import (build_primal, project_to_edges, split_at_positions,
                            attach_terminals, nearest_facilities, reachable_arcs)
from network_location import locate


def roads(geometries, directions=None, levels=None, costs=None):
    return gpd.GeoDataFrame({'rid': [str(i) for i in range(len(geometries))],
        'direction': directions or ['both'] * len(geometries),
        'level': levels or [0] * len(geometries),
        'cost': costs or [g.length for g in geometries]}, geometry=geometries, crs='EPSG:32650')


def build(data):
    return build_primal(data, road_key='rid', direction='direction', cost='cost', level_fields=('level',))


def rejected(function):
    try:
        function()
    except ValueError:
        return True
    raise AssertionError('Unsafe premise was accepted')


def cases():
    facts = {}
    crossing = [LineString([(0, 0), (10, 0)]), LineString([(5, -5), (5, 5)])]
    assert rejected(lambda: build(roads(crossing)))
    separate = build(roads(crossing, levels=[0, 1]))
    assert nx.number_weakly_connected_components(separate) == 2
    parallel = build(roads([LineString([(0, 0), (5, 0), (10, 0)]),
                            LineString([(0, 0), (5, 3), (10, 0)])], costs=[10, 7]))
    nodes = list(parallel.nodes)
    assert parallel.number_of_edges() == 4 and nx.shortest_path_length(parallel, nodes[0], nodes[1], weight='cost') == 7
    summed = float(coo_matrix(([2., 7.], ([0, 0], [1, 1])), shape=(2, 2)).tocsr()[0, 1])
    assert summed == 9
    facts['N1'] = {'grade_components': 2, 'parallel_cost': 7, 'coo_sum_counterexample': summed,
                   'unnoded_crossing_rejected': True}

    edges = roads([LineString([(-1000, 0), (1000, 0)]), LineString([(900, 10), (900, 11)])])
    points = gpd.GeoDataFrame({'pid': ['near', 'far']}, geometry=[Point(900, 1), Point(5000, 5000)], crs=edges.crs)
    hits = project_to_edges(points, edges, point_key='pid', edge_key='rid', max_distance=20)
    assert hits['matches'][0]['road_id'] == '0' and hits['unmatched'] == ['far']
    assert min(range(2), key=lambda i: edges.geometry.iloc[i].interpolate(.5, normalized=True).distance(points.geometry.iloc[0])) == 1
    tied = project_to_edges(gpd.GeoDataFrame({'pid': ['tie']}, geometry=[Point(0, 1)], crs=edges.crs),
        roads([LineString([(-1, 0), (1, 0)]), LineString([(-1, 2), (1, 2)])]),
        point_key='pid', edge_key='rid', max_distance=3)
    assert len(tied['matches']) == 2 and tied['ambiguous'] == ['tie']
    facts['N2'] = {'nearest_edge': '0', 'midpoint_edge': '1', 'unmatched': hits['unmatched'], 'ties': 2}

    line = roads([LineString([(0, 0), (10, 0)])])
    demands = gpd.GeoDataFrame({'pid': ['d']}, geometry=[Point(0, 1)], crs=line.crs)
    facilities = gpd.GeoDataFrame({'pid': ['a', 'b']}, geometry=[Point(5, 100), Point(9, 0)], crs=line.crs)
    d = project_to_edges(demands, line, point_key='pid', edge_key='rid', max_distance=200)['matches']
    f = project_to_edges(facilities, line, point_key='pid', edge_key='rid', max_distance=200)['matches']
    graph = split_at_positions(build(line), d + f, cost_model='length_proportional')
    dn = attach_terminals(graph, d, role='demand')
    fn = attach_terminals(graph, f, role='facility')
    chosen = nearest_facilities(graph, dn, fn)
    assert chosen[0]['facility_id'] == 'b' and chosen[0]['cost'] == 10
    assert graph.out_degree(fn['a']) == graph.out_degree(fn['b']) == 0
    directed = build(roads([LineString([(0, 0), (10, 0)])], directions=['forward']))
    directed.add_edge('d', list(directed.nodes)[1], cost=0, terminal=True)
    directed.add_edge(list(directed.nodes)[0], 'f', cost=0, terminal=True)
    assert nearest_facilities(directed, {'d': 'd'}, {'f': 'f'})[0]['status'] == 'unreachable'
    facts['N3'] = {'nearest': chosen, 'reverse_unreachable': True, 'terminals_do_not_bridge': True}

    plain = build(line)
    origin = next(iter(plain.nodes))
    arcs = reachable_arcs(plain, [origin], 3, cost_model='length_proportional')
    assert len(arcs) == 1 and abs(arcs[0]['geometry'].length - 3) < 1e-12
    assert rejected(lambda: reachable_arcs(plain, [origin], 3, cost_model='fixed_toll'))
    facts['N4'] = {'partial_length': 3, 'land_polygon_claimed': False}

    # Network detours reverse the cheapest facility compared with geometric OD.
    network = locate([[1, 9], [20, 2]], [1, 1], 1)
    euclidean = locate([[1, 9], [2, 8]], [1, 1], 1)
    assert network['sites'] == [1] and euclidean['sites'] == [0]
    assert locate([[None, 2], [None, 4]], [1, 0], 1)['sites'] == [1]
    assert rejected(lambda: locate([[None]], [1], 1))
    assert locate([[1, 8], [9, 2]], [2, 3], 1, 'maximum_coverage', 3)['value'] == 3
    facts['N5'] = {'network': network, 'euclidean': euclidean}

    disconnected = nx.DiGraph()
    disconnected.add_weighted_edges_from([('d', 'x', 5), ('y', 'f', 6)], weight='cost')
    assert not nx.has_path(disconnected, 'd', 'f')
    hypothesis = disconnected.copy()
    hypothesis.add_edge('x', 'y', cost=1, assumption='unverified bridge')
    assert nx.shortest_path_length(hypothesis, 'd', 'f', weight='cost') == 12
    facts['N6'] = {'observed_unreachable': True, 'hypothetical_connected_cost': 12,
                   'bridge_verified': False}
    return facts


if __name__ == '__main__':
    value = cases()
    text = json.dumps(value, allow_nan=False)
    if os.environ.get('GIS_AGENT_RESULT_PATH'):
        Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(text, encoding='utf-8')
    print(text)
