"""Advanced zero-new-dependency road network solvers: barriers, Top-K closest facilities, and turn penalties/restrictions.

Dependencies: NumPy, Shapely >=2, NetworkX.
Works directly on MultiDiGraph objects built by `network_access.build_primal` / `split_at_positions`.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys

import networkx as nx
import numpy as np
import shapely


def _edge_unit_tangents(geom):
    """Return unit start and end tangent vectors along a LineString geometry."""
    coords = list(geom.coords)
    if len(coords) < 2:
        raise ValueError("LineString requires at least 2 coordinates")
    sx, sy = 0.0, 0.0
    for a, b in zip(coords[:-1], coords[1:]):
        dx, dy = float(b[0] - a[0]), float(b[1] - a[1])
        norm = math.hypot(dx, dy)
        if norm > 1e-12:
            sx, sy = dx / norm, dy / norm
            break
    ex, ey = 0.0, 0.0
    for a, b in zip(reversed(coords[:-1]), reversed(coords[1:])):
        dx, dy = float(b[0] - a[0]), float(b[1] - a[1])
        norm = math.hypot(dx, dy)
        if norm > 1e-12:
            ex, ey = dx / norm, dy / norm
            break
    if sx == 0.0 and sy == 0.0:
        raise ValueError("Degenerate zero-length LineString cannot define turn direction")
    if ex == 0.0 and ey == 0.0:
        ex, ey = sx, sy
    return (sx, sy), (ex, ey)


def _classify_turn(in_end, out_start, *, same_physical_reverse=False):
    if same_physical_reverse:
        return "uturn", 180.0
    ax, ay = in_end
    bx, by = out_start
    dot = max(-1.0, min(1.0, ax * bx + ay * by))
    cross = ax * by - ay * bx
    angle = math.degrees(math.atan2(cross, dot))
    if abs(angle) <= 30.0:
        return "straight", angle
    if abs(angle) >= 150.0:
        return "uturn", angle
    if angle > 0.0:
        return "left", angle
    return "right", angle


def apply_barriers(
    graph,
    *,
    point_barriers=None,
    line_barriers=None,
    polygon_barriers=None,
    point_tol_m=1.0,
    weight="cost",
):
    """Apply point/line closures and polygon restriction or scaled-cost congestion zones without mutating input graph."""
    if not math.isfinite(point_tol_m) or point_tol_m < 0:
        raise ValueError("point_tol_m must be finite and nonnegative")

    out = graph.copy()
    if isinstance(out.graph.get("roads"), dict):
        out.graph["roads"] = dict(out.graph["roads"])

    restrict_geoms = []
    for pt in point_barriers or ():
        if pt is not None and not pt.is_empty:
            restrict_geoms.append(pt.buffer(float(point_tol_m)) if point_tol_m > 0 else pt)
    for ln in line_barriers or ():
        if ln is not None and not ln.is_empty:
            restrict_geoms.append(ln)

    scaled_zones = []
    for item in polygon_barriers or ():
        if isinstance(item, dict):
            poly = item["geometry"]
            mode = str(item.get("mode", "restriction")).strip().lower()
            factor = float(item.get("factor", 2.0))
        else:
            poly = item
            mode = "restriction"
            factor = 1.0
        if poly is None or poly.is_empty:
            continue
        if mode == "restriction":
            restrict_geoms.append(poly)
        elif mode == "scaled_cost":
            if not math.isfinite(factor) or factor < 0:
                raise ValueError("Scaled barrier factor must be finite and nonnegative")
            scaled_zones.append((poly, factor))
        else:
            raise ValueError(f"Unsupported polygon barrier mode '{mode}'")

    edges = [
        (u, v, key, data)
        for u, v, key, data in out.edges(keys=True, data=True)
        if not data.get("terminal") and data.get("geometry") is not None
    ]
    if not edges:
        return {"graph": out, "removed_edges": 0, "scaled_edges": 0}

    geoms = np.array([e[3]["geometry"] for e in edges], dtype=object)
    tree = shapely.STRtree(geoms)

    to_remove = set()
    for barrier in restrict_geoms:
        for idx in tree.query(barrier, predicate="intersects"):
            to_remove.add(int(idx))

    removed_count = 0
    for idx in sorted(to_remove):
        u, v, key, data = edges[idx]
        if out.has_edge(u, v, key):
            out.remove_edge(u, v, key)
            removed_count += 1
        rid = data.get("road_id")
        if rid in out.graph.get("roads", {}):
            # Remove road metadata only if no parallel directional twin remains
            still_present = any(d.get("road_id") == rid for _, _, d in out.edges(data=True))
            if not still_present:
                out.graph["roads"].pop(rid, None)

    scaled_count = 0
    if scaled_zones:
        rem_edges = [(u, v, key, data) for i, (u, v, key, data) in enumerate(edges) if i not in to_remove]
        if rem_edges:
            rem_tree = shapely.STRtree(np.array([e[3]["geometry"] for e in rem_edges], dtype=object))
            scaled_keys = set()
            for poly, factor in scaled_zones:
                for idx in rem_tree.query(poly, predicate="intersects"):
                    u, v, key, data = rem_edges[int(idx)]
                    g = data["geometry"]
                    if g.length <= 0:
                        continue
                    overlap_len = float(g.intersection(poly).length)
                    if overlap_len <= 0:
                        continue
                    frac = min(1.0, overlap_len / float(g.length))
                    mult = 1.0 - frac + frac * factor
                    data[weight] = float(data[weight]) * mult
                    scaled_keys.add((u, v, key))
            scaled_count = len(scaled_keys)

    return {"graph": out, "removed_edges": removed_count, "scaled_edges": scaled_count}


def closest_k_facilities(
    graph,
    demand_nodes,
    facility_nodes,
    *,
    k=3,
    cutoff=None,
    weight="cost",
    direction="demand_to_facility",
):
    """Find exact ranked Top-K closest facilities per demand node within optional cutoff."""
    if type(k) is not int or k <= 0:
        raise ValueError("k must be a positive integer")
    if cutoff is not None and (not math.isfinite(cutoff) or cutoff < 0):
        raise ValueError("cutoff must be finite and nonnegative")
    if direction not in {"demand_to_facility", "facility_to_demand"}:
        raise ValueError("direction must be 'demand_to_facility' or 'facility_to_demand'")
    if not facility_nodes:
        raise ValueError("At least one facility node required")
    for _, _, attrs in graph.edges(data=True):
        if weight not in attrs:
            raise ValueError(f"Every edge must define '{weight}'")
        val = float(attrs[weight])
        if not math.isfinite(val) or val < 0:
            raise ValueError("All edge weights must be finite and nonnegative")

    search_graph = graph.reverse(copy=False) if direction == "demand_to_facility" else graph
    candidates = {did: [] for did in demand_nodes}

    for fid, fnode in facility_nodes.items():
        if fnode not in search_graph:
            continue
        dists = nx.single_source_dijkstra_path_length(search_graph, fnode, cutoff=cutoff, weight=weight)
        for did, dnode in demand_nodes.items():
            if dnode in dists:
                candidates[did].append((float(dists[dnode]), fid))

    results = []
    for did in demand_nodes:
        ranked = sorted(candidates[did], key=lambda item: (item[0], repr(item[1])))[:k]
        results.append({
            "demand_id": did,
            "facilities": [
                {"facility_id": fid, "cost": cost, "rank": idx + 1}
                for idx, (cost, fid) in enumerate(ranked)
            ],
            "reachable_count": len(ranked),
        })
    return results


def build_turn_graph(
    graph,
    *,
    weight="cost",
    forbidden_turns=(),
    turn_penalties=None,
    forbid_uturns=True,
    allow_deadend_uturns=True,
    straight_penalty=0.0,
    right_penalty=0.0,
    left_penalty=0.0,
    uturn_penalty=0.0,
):
    """Expand a primal MultiDiGraph into an edge-state DiGraph modeling exact turn restrictions & delays."""
    for name, val in (
        ("straight_penalty", straight_penalty),
        ("right_penalty", right_penalty),
        ("left_penalty", left_penalty),
        ("uturn_penalty", uturn_penalty),
    ):
        if not math.isfinite(val) or val < 0:
            raise ValueError(f"{name} must be finite and nonnegative")

    forbidden = {(a, b) for a, b in forbidden_turns}
    specific = {tuple(k): float(v) for k, v in (turn_penalties or {}).items()}
    if any(not math.isfinite(v) or v < 0 for v in specific.values()):
        raise ValueError("turn_penalties values must be finite and nonnegative")

    turn_graph = nx.DiGraph(crs=graph.graph.get("crs"))
    edge_meta = {}
    out_by_node = {}

    for u, v, key, data in graph.edges(keys=True, data=True):
        if data.get("terminal"):
            continue
        geom = data.get("geometry")
        if geom is None or geom.is_empty:
            raise ValueError("All road edges require valid LineString geometries for turn modeling")
        c = float(data[weight])
        if not math.isfinite(c) or c < 0:
            raise ValueError("All edge weights must be finite and nonnegative")
        start_vec, end_vec = _edge_unit_tangents(geom)
        state_node = ("edge", u, v, key)
        rid = data.get("road_id", key)
        edge_meta[state_node] = {
            "u": u,
            "v": v,
            "key": key,
            "road_id": rid,
            "cost": c,
            "start_vec": start_vec,
            "end_vec": end_vec,
        }
        out_by_node.setdefault(u, []).append(state_node)
        turn_graph.add_node(state_node, road_id=rid, base_cost=c)

        turn_graph.add_edge(("start", u), state_node, **{weight: c, "travel_cost": c, "turn_penalty": 0.0, "turn_type": "start", "road_id": rid})
        turn_graph.add_edge(state_node, ("end", v), **{weight: 0.0, "travel_cost": 0.0, "turn_penalty": 0.0, "turn_type": "end", "road_id": None})

    type_penalties = {
        "straight": float(straight_penalty),
        "right": float(right_penalty),
        "left": float(left_penalty),
        "uturn": float(uturn_penalty),
    }

    for in_node, m_in in edge_meta.items():
        v = m_in["v"]
        candidates = out_by_node.get(v, [])
        if not candidates:
            continue
        non_reverse = [
            out_node for out_node in candidates
            if not (edge_meta[out_node]["v"] == m_in["u"] and edge_meta[out_node]["road_id"] == m_in["road_id"])
        ]
        is_deadend = len(non_reverse) == 0
        for out_node in candidates:
            m_out = edge_meta[out_node]
            rid_in = m_in["road_id"]
            rid_out = m_out["road_id"]
            if (rid_in, rid_out) in forbidden:
                continue
            same_rev = (m_out["v"] == m_in["u"] and rid_out == rid_in)
            ttype, angle = _classify_turn(m_in["end_vec"], m_out["start_vec"], same_physical_reverse=same_rev)
            if ttype == "uturn" and forbid_uturns and not (allow_deadend_uturns and is_deadend):
                continue
            penalty = specific.get((rid_in, rid_out), type_penalties[ttype])
            total_w = m_out["cost"] + penalty
            turn_graph.add_edge(
                in_node,
                out_node,
                **{
                    weight: total_w,
                    "travel_cost": m_out["cost"],
                    "turn_penalty": penalty,
                    "turn_type": ttype,
                    "angle_deg": round(angle, 3),
                    "road_id": rid_out,
                },
            )

    return turn_graph


def turn_shortest_path(turn_graph, origin_node, dest_node, *, weight="cost"):
    """Find shortest path over a turn-expanded edge-state DiGraph with turn breakdown."""
    src = ("start", origin_node)
    dst = ("end", dest_node)
    try:
        path = nx.shortest_path(turn_graph, src, dst, weight=weight)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {
            "ok": False,
            "cost": None,
            "travel_cost": None,
            "turn_penalty_total": 0.0,
            "road_ids": [],
            "turn_counts": {},
        }

    total_cost = 0.0
    travel_cost = 0.0
    turn_penalty_total = 0.0
    road_ids = []
    turn_counts = {}
    for a, b in zip(path[:-1], path[1:]):
        attrs = turn_graph[a][b]
        total_cost += float(attrs[weight])
        travel_cost += float(attrs.get("travel_cost", 0.0))
        turn_penalty_total += float(attrs.get("turn_penalty", 0.0))
        rid = attrs.get("road_id")
        if rid is not None:
            road_ids.append(rid)
        ttype = attrs.get("turn_type")
        if ttype in {"straight", "right", "left", "uturn"}:
            turn_counts[ttype] = turn_counts.get(ttype, 0) + 1

    return {
        "ok": True,
        "cost": total_cost,
        "travel_cost": travel_cost,
        "turn_penalty_total": turn_penalty_total,
        "road_ids": road_ids,
        "turn_counts": turn_counts,
    }


def _run_cli(settings_path):
    cfg = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    # Construct small synthetic planar network from JSON roads for standalone checks
    from network_access import build_primal

    gdf = gpd.read_file(cfg["roads_path"], layer=cfg.get("roads_layer")) if "roads_path" in cfg else None
    if gdf is None:
        raise ValueError("CLI requires roads_path")
    graph = build_primal(
        gdf,
        road_key=cfg["road_key"],
        direction=cfg.get("direction", "direction"),
        cost=cfg["cost"],
        level_fields=tuple(cfg.get("level_fields", ())),
    )
    tg = build_turn_graph(
        graph,
        weight="cost",
        forbidden_turns=cfg.get("forbidden_turns", ()),
        forbid_uturns=bool(cfg.get("forbid_uturns", True)),
        left_penalty=float(cfg.get("left_penalty", 0.0)),
        right_penalty=float(cfg.get("right_penalty", 0.0)),
        uturn_penalty=float(cfg.get("uturn_penalty", 0.0)),
    )
    origin = ("xy", float(cfg["origin"][0]), float(cfg["origin"][1]), tuple(cfg.get("origin_level", ())))
    dest = ("xy", float(cfg["dest"][0]), float(cfg["dest"][1]), tuple(cfg.get("dest_level", ())))
    result = turn_shortest_path(tg, origin, dest, weight="cost")
    text = json.dumps(result, allow_nan=False)
    if os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    import geopandas as gpd  # noqa: E402
    parser = argparse.ArgumentParser(description="Turn-restricted routing CLI")
    parser.add_argument("settings")
    args = parser.parse_args()
    _run_cli(args.settings)
