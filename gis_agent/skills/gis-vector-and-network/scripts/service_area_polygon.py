"""Zero-new-dependency open-source Service Area Polygon generators.

Supports three calibrated polygonization models over directed reachable road networks:
- Method A (default): Trimmed-TIN isochrone polygons using SciPy Delaunay + Matplotlib
  tricontourf + long-edge `trim_m` masking + small rural corridor union. Matches the core
  urban-fill vs. gap-exclusion behavior of ArcGIS Detailed Service Area polygons.
- Method B: Fixed-width road corridor buffer (fast sensitivity lower/upper control).
- Method C: Clustered concave hull envelope (coarse macro boundary via KDTree + shapely).

Dependencies: NumPy, SciPy, Shapely >=2, GeoPandas, Matplotlib.
"""
import argparse
from functools import reduce
import json
import math
import os
from pathlib import Path
import sys

import geopandas as gpd
from matplotlib.figure import Figure
from matplotlib.tri import Triangulation
import numpy as np
from scipy.spatial import Delaunay, QhullError, cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
import shapely
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon
from shapely.ops import substring, unary_union


def _validate_thresholds(thresholds):
    vals = sorted({float(t) for t in thresholds})
    if not vals or any(not math.isfinite(t) or t <= 0 for t in vals):
        raise ValueError("thresholds must contain positive finite numbers")
    return vals


def _make_valid_polygonal(geom):
    if geom is None or geom.is_empty:
        return Polygon()
    g = shapely.make_valid(geom)
    parts = []
    stack = [g]
    while stack:
        cur = stack.pop()
        if cur is None or cur.is_empty:
            continue
        if cur.geom_type in {"Polygon", "MultiPolygon"}:
            parts.append(cur)
        elif cur.geom_type == "GeometryCollection":
            stack.extend(cur.geoms)
    if not parts:
        return Polygon()
    merged = unary_union(parts)
    return shapely.make_valid(merged)


def _path_to_shapely(path):
    """Reconstruct valid Polygon/MultiPolygon with holes preserved via ring parity."""
    rings = []
    for arr in path.to_polygons(closed_only=True):
        if len(arr) < 3:
            continue
        poly = Polygon(arr)
        if not poly.is_valid:
            poly = shapely.make_valid(poly)
        if not poly.is_empty and poly.area > 0:
            rings.append(_make_valid_polygonal(poly))
    if not rings:
        return Polygon()
    if len(rings) == 1:
        return rings[0]
    combined = reduce(lambda a, b: a.symmetric_difference(b), rings)
    return _make_valid_polygonal(combined)


def _slice_bands_or_disks(disks_by_t, thresholds, *, clip_boundary=None, mode="rings", method="trimmed_tin", crs=None, extra_cols=None):
    mode_norm = str(mode).strip().lower()
    if mode_norm not in {"rings", "disks"}:
        raise ValueError("mode must be 'rings' or 'disks'")
    clip_geom = None
    if clip_boundary is not None:
        if hasattr(clip_boundary, "geometry"):
            clip_geom = _make_valid_polygonal(unary_union(list(clip_boundary.geometry)))
        else:
            clip_geom = _make_valid_polygonal(clip_boundary)

    rows = []
    prev_disk = Polygon()
    prev_t = 0.0
    ordered_disks = []
    for t in thresholds:
        cur = _make_valid_polygonal(disks_by_t.get(t, Polygon()))
        if not prev_disk.is_empty:
            cur = _make_valid_polygonal(unary_union([cur, prev_disk]))
        if clip_geom is not None and not cur.is_empty:
            cur = _make_valid_polygonal(cur.intersection(clip_geom))
        ordered_disks.append((prev_t, t, cur))
        prev_disk = cur
        prev_t = t

    prev_clipped = Polygon()
    for t_min, t_max, disk_geom in ordered_disks:
        if mode_norm == "rings":
            out_geom = _make_valid_polygonal(disk_geom.difference(prev_clipped)) if not prev_clipped.is_empty else disk_geom
            low_val = t_min
        else:
            out_geom = disk_geom
            low_val = 0.0
        prev_clipped = disk_geom
        row = {
            "threshold_min": float(low_val),
            "threshold_max": float(t_max),
            "mode": mode_norm,
            "method": method,
            "area_m2": float(out_geom.area) if not out_geom.is_empty else 0.0,
            "geometry": out_geom,
        }
        if extra_cols:
            row.update(extra_cols)
        rows.append(row)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)


def densify_reachable_samples(
    graph,
    distances,
    thresholds,
    *,
    max_spacing_m=250.0,
    weight="cost",
    cost_model="length_proportional",
):
    """Collect road node times, exact cutoff points, and densified interior samples."""
    if cost_model != "length_proportional":
        raise ValueError("Only length_proportional edge costs support cutoff interpolation")
    if not math.isfinite(max_spacing_m) or max_spacing_m <= 0:
        raise ValueError("max_spacing_m must be finite and positive")
    t_vals = _validate_thresholds(thresholds)
    t_max = t_vals[-1]

    sample_costs = {}
    reachable_lines = {t: [] for t in t_vals}

    def _record_pt(x, y, cost_val):
        key = (round(float(x), 6), round(float(y), 6))
        prev = sample_costs.get(key)
        if prev is None or cost_val < prev:
            sample_costs[key] = float(cost_val)

    for u, v, _key, data in graph.edges(keys=True, data=True):
        if data.get("terminal"):
            continue
        geom = data.get("geometry")
        if geom is None or geom.is_empty or geom.length <= 0:
            continue
        edge_cost = float(data[weight])
        if not math.isfinite(edge_cost) or edge_cost < 0:
            raise ValueError("All road edges require finite nonnegative costs")

        c0 = geom.coords[0]
        c1 = geom.coords[-1]
        du = float(distances.get(u, math.inf))
        dv = float(distances.get(v, math.inf))
        _record_pt(c0[0], c0[1], du)
        _record_pt(c1[0], c1[1], dv)

        # Densify along road geometry so long corridors retain TIN control nodes
        n_seg = max(1, int(math.ceil(float(geom.length) / float(max_spacing_m))))
        if math.isfinite(du):
            for idx in range(1, n_seg):
                frac = idx / n_seg
                pt = geom.interpolate(frac, normalized=True)
                _record_pt(pt.x, pt.y, du + frac * edge_cost)
            end_reached = du + edge_cost
            _record_pt(c1[0], c1[1], min(dv, end_reached))

            for t in t_vals:
                if du > t:
                    continue
                if edge_cost == 0:
                    frac_t = 1.0
                else:
                    frac_t = min(1.0, max(0.0, (t - du) / edge_cost))
                if frac_t > 0:
                    seg = geom if frac_t >= 1.0 else substring(geom, 0.0, frac_t, normalized=True)
                    if seg is not None and not seg.is_empty and seg.length > 0:
                        reachable_lines[t].append(seg)
                    if frac_t < 1.0:
                        pt_cut = geom.interpolate(frac_t, normalized=True)
                        _record_pt(pt_cut.x, pt_cut.y, t)
        else:
            for idx in range(1, n_seg):
                pt = geom.interpolate(idx / n_seg, normalized=True)
                _record_pt(pt.x, pt.y, math.inf)

    if not sample_costs:
        return np.empty((0, 2), dtype=float), np.empty((0,), dtype=float), reachable_lines
    coords = np.array(list(sample_costs.keys()), dtype=float)
    times = np.array(list(sample_costs.values()), dtype=float)
    return coords, times, reachable_lines


def trimmed_tin_service_areas(
    points_xy,
    times,
    thresholds,
    *,
    trim_m=500.0,
    reachable_lines=None,
    corridor_floor_m=100.0,
    clip_boundary=None,
    mode="rings",
    crs=None,
):
    """Build ArcGIS-analog Trimmed-TIN isochrone rings/disks using SciPy Delaunay + tricontourf."""
    if not math.isfinite(trim_m) or trim_m <= 0:
        raise ValueError("trim_m must be finite and positive")
    if not math.isfinite(corridor_floor_m) or corridor_floor_m < 0:
        raise ValueError("corridor_floor_m must be finite and nonnegative")
    t_vals = _validate_thresholds(thresholds)
    xy = np.asarray(points_xy, dtype=float)
    z = np.asarray(times, dtype=float)
    if xy.ndim != 2 or xy.shape[1] != 2 or z.shape != (xy.shape[0],):
        raise ValueError("points_xy must have shape (N, 2) aligned with times (N,)")

    disks_by_t = {t: Polygon() for t in t_vals}
    if len(xy) >= 3:
        try:
            tri = Delaunay(xy)
            simplices = tri.simplices
            p = xy[simplices]  # (T, 3, 2)
            e01 = np.hypot(p[:, 1, 0] - p[:, 0, 0], p[:, 1, 1] - p[:, 0, 1])
            e12 = np.hypot(p[:, 2, 0] - p[:, 1, 0], p[:, 2, 1] - p[:, 1, 1])
            e20 = np.hypot(p[:, 0, 0] - p[:, 2, 0], p[:, 0, 1] - p[:, 2, 1])
            max_edge = np.maximum(e01, np.maximum(e12, e20))
            tri_z = z[simplices]
            all_unreach = ~np.any(np.isfinite(tri_z) & (tri_z <= t_vals[-1] * 2.0), axis=1)
            mask = (max_edge > 2.0 * float(trim_m)) | all_unreach

            if not np.all(mask):
                finite_mask = np.isfinite(z)
                cap_z = (float(np.max(z[finite_mask])) if np.any(finite_mask) else t_vals[-1]) * 2.0 + t_vals[-1] + 1.0
                z_clean = np.where(finite_mask, z, cap_z)
                mpl_tri = Triangulation(xy[:, 0], xy[:, 1], triangles=simplices, mask=mask)
                levels = [-1e-9, *t_vals]
                fig = Figure(figsize=(4, 4))
                try:
                    ax = fig.add_subplot(111)
                    cs = ax.tricontourf(mpl_tri, z_clean, levels=levels)
                    paths = cs.get_paths()
                    band_acc = Polygon()
                    for idx_lvl, path in enumerate(paths):
                        if idx_lvl >= len(t_vals):
                            break
                        band_poly = _path_to_shapely(path)
                        if not band_poly.is_empty:
                            band_acc = _make_valid_polygonal(unary_union([band_acc, band_poly]))
                        disks_by_t[t_vals[idx_lvl]] = band_acc
                finally:
                    fig.clear()
        except (QhullError, ValueError):
            pass

    if reachable_lines is not None and corridor_floor_m > 0:
        for t in t_vals:
            lines = reachable_lines.get(t) or []
            if lines:
                floor_poly = _make_valid_polygonal(unary_union([ln.buffer(float(corridor_floor_m)) for ln in lines]))
                disks_by_t[t] = _make_valid_polygonal(unary_union([disks_by_t[t], floor_poly]))

    return _slice_bands_or_disks(
        disks_by_t,
        t_vals,
        clip_boundary=clip_boundary,
        mode=mode,
        method="trimmed_tin",
        crs=crs,
        extra_cols={"trim_m": float(trim_m), "corridor_floor_m": float(corridor_floor_m)},
    )


def corridor_service_areas(
    reachable_lines,
    thresholds,
    *,
    corridor_m=500.0,
    clip_boundary=None,
    mode="rings",
    crs=None,
):
    """Method B control: buffer reachable road lines directly by fixed corridor half-width."""
    if not math.isfinite(corridor_m) or corridor_m <= 0:
        raise ValueError("corridor_m must be finite and positive")
    t_vals = _validate_thresholds(thresholds)
    disks_by_t = {}
    for t in t_vals:
        lines = reachable_lines.get(t) or []
        disks_by_t[t] = _make_valid_polygonal(unary_union([ln.buffer(float(corridor_m)) for ln in lines])) if lines else Polygon()
    return _slice_bands_or_disks(
        disks_by_t,
        t_vals,
        clip_boundary=clip_boundary,
        mode=mode,
        method="corridor_buffer",
        crs=crs,
        extra_cols={"corridor_m": float(corridor_m)},
    )


def clustered_concave_service_areas(
    points_xy,
    times,
    thresholds,
    *,
    ratio=0.25,
    cluster_eps_m=1000.0,
    corridor_floor_m=100.0,
    reachable_lines=None,
    clip_boundary=None,
    mode="rings",
    crs=None,
):
    """Method C: spatial connected-component clustering + Shapely concave_hull."""
    if not (0.0 <= ratio <= 1.0):
        raise ValueError("ratio must stay in [0, 1]")
    if not math.isfinite(cluster_eps_m) or cluster_eps_m <= 0:
        raise ValueError("cluster_eps_m must be finite and positive")
    t_vals = _validate_thresholds(thresholds)
    xy = np.asarray(points_xy, dtype=float)
    z = np.asarray(times, dtype=float)
    disks_by_t = {t: Polygon() for t in t_vals}

    for t in t_vals:
        keep = np.isfinite(z) & (z <= t)
        pts = xy[keep]
        hulls = []
        if len(pts) >= 3:
            tree = cKDTree(pts)
            pairs = tree.query_pairs(r=float(cluster_eps_m), output_type="ndarray")
            n_pts = len(pts)
            if len(pairs):
                rows = np.concatenate([pairs[:, 0], pairs[:, 1]])
                cols = np.concatenate([pairs[:, 1], pairs[:, 0]])
                adj = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n_pts, n_pts)).tocsr()
            else:
                adj = coo_matrix((n_pts, n_pts)).tocsr()
            n_comp, labels = connected_components(adj, directed=False)
            for cid in range(n_comp):
                sub = pts[labels == cid]
                if len(sub) >= 3:
                    mp = shapely.MultiPoint([tuple(pt) for pt in sub])
                    hull = shapely.concave_hull(mp, ratio=float(ratio))
                    if hull is not None and not hull.is_empty and hull.area > 0:
                        hulls.append(_make_valid_polygonal(hull))
        if reachable_lines is not None and corridor_floor_m > 0:
            lines = reachable_lines.get(t) or []
            if lines:
                hulls.append(_make_valid_polygonal(unary_union([ln.buffer(float(corridor_floor_m)) for ln in lines])))
        disks_by_t[t] = _make_valid_polygonal(unary_union(hulls)) if hulls else Polygon()

    return _slice_bands_or_disks(
        disks_by_t,
        t_vals,
        clip_boundary=clip_boundary,
        mode=mode,
        method="clustered_concave",
        crs=crs,
        extra_cols={"cluster_eps_m": float(cluster_eps_m), "ratio": float(ratio)},
    )


def _run_cli(settings_path):
    cfg = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    pts = np.asarray(cfg["points_xy"], dtype=float)
    times = np.asarray(cfg["times"], dtype=float)
    thresholds = cfg["thresholds"]
    method = str(cfg.get("method", "trimmed_tin")).lower()
    if method == "trimmed_tin":
        gdf = trimmed_tin_service_areas(
            pts,
            times,
            thresholds,
            trim_m=float(cfg.get("trim_m", 500.0)),
            corridor_floor_m=float(cfg.get("corridor_floor_m", 100.0)),
            mode=cfg.get("mode", "rings"),
            crs=cfg.get("crs"),
        )
    elif method == "clustered_concave":
        gdf = clustered_concave_service_areas(
            pts,
            times,
            thresholds,
            ratio=float(cfg.get("ratio", 0.25)),
            cluster_eps_m=float(cfg.get("cluster_eps_m", 1000.0)),
            mode=cfg.get("mode", "rings"),
            crs=cfg.get("crs"),
        )
    else:
        raise ValueError(f"Unsupported CLI method '{method}' without pre-built lines")

    out_path = cfg.get("output")
    if out_path:
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(target, driver=cfg.get("driver", "GPKG"))
    summary = {
        "ok": True,
        "method": method,
        "mode": gdf["mode"].iloc[0] if len(gdf) else cfg.get("mode", "rings"),
        "bands": [
            {"threshold_min": float(r.threshold_min), "threshold_max": float(r.threshold_max), "area_m2": float(r.area_m2)}
            for r in gdf.itertuples(index=False)
        ],
        "output": str(out_path) if out_path else None,
    }
    text = json.dumps(summary, allow_nan=False)
    if os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Service area TIN / corridor / concave polygon builder")
    parser.add_argument("settings")
    args = parser.parse_args()
    _run_cli(args.settings)
