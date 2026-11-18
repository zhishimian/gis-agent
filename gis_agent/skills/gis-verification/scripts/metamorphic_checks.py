from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon


def check_conservation(
    expected_total: float,
    observed_total: float,
    unmatched_total: float = 0.0,
    *,
    rtol: float = 1e-6,
    atol: float = 1e-9,
) -> dict[str, Any]:
    """Audit conservation across input total, delivered total, and explicit residuals."""
    accounted = float(observed_total) + float(unmatched_total)
    residual = float(expected_total) - accounted
    scale = max(abs(float(expected_total)), 1.0)
    within_tolerance = abs(residual) <= max(atol, rtol * scale)
    return {
        "expected_total": float(expected_total),
        "observed_total": float(observed_total),
        "unmatched_total": float(unmatched_total),
        "residual": residual,
        "within_tolerance": bool(within_tolerance),
    }


def check_permutation_invariance(
    fn: Callable[[pd.DataFrame], pd.DataFrame],
    df: pd.DataFrame,
    key_col: str,
    value_cols: list[str],
    *,
    seed: int = 7,
) -> dict[str, Any]:
    """Detect latent row-position or FID coupling by shuffling input order and comparing keyed values."""
    baseline = fn(df.copy()).sort_values(key_col).reset_index(drop=True)
    shuffled_input = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    permuted = fn(shuffled_input).sort_values(key_col).reset_index(drop=True)

    same_keys = baseline[key_col].tolist() == permuted[key_col].tolist()
    mismatches: list[str] = []
    if same_keys:
        for col in value_cols:
            a = baseline[col]
            b = permuted[col]
            if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
                if not np.allclose(a.to_numpy(dtype=float), b.to_numpy(dtype=float), equal_nan=True):
                    mismatches.append(col)
            elif not a.equals(b):
                mismatches.append(col)
    return {
        "invariant": bool(same_keys and not mismatches),
        "same_keys": bool(same_keys),
        "mismatched_columns": mismatches,
    }


def compare_boundary_predicates(
    points_gdf: gpd.GeoDataFrame,
    polys_gdf: gpd.GeoDataFrame,
    point_key: str,
) -> dict[str, Any]:
    """Expose boundary-contact sensitivity across intersects, within, and covered_by."""
    if points_gdf.crs != polys_gdf.crs:
        raise ValueError(f"CRS mismatch in boundary check: {points_gdf.crs} vs {polys_gdf.crs}")
    counts: dict[str, list[Any]] = {}
    for predicate in ("intersects", "within", "covered_by"):
        joined = gpd.sjoin(points_gdf[[point_key, "geometry"]], polys_gdf[["geometry"]], how="inner", predicate=predicate)
        counts[predicate] = sorted(joined[point_key].drop_duplicates().tolist())
    boundary_only = sorted(set(counts["intersects"]) - set(counts["within"]))
    return {
        "intersects_count": len(counts["intersects"]),
        "within_count": len(counts["within"]),
        "covered_by_count": len(counts["covered_by"]),
        "boundary_only_keys": boundary_only,
    }


def check_scale_invariance(
    fn: Callable[[float, float], float],
    a: float,
    b: float,
    *,
    factor: float = 10000.0,
) -> dict[str, Any]:
    """Measure output divergence when positive inputs are scaled uniformly by factor."""
    base = float(fn(a, b))
    scaled = float(fn(a * factor, b * factor))
    diff = abs(scaled - base)
    return {
        "base": round(base, 8),
        "scaled": round(scaled, 8),
        "abs_diff": round(diff, 8),
        "scale_invariant": bool(diff <= 1e-6 * max(1.0, abs(base))),
    }


def run_demo() -> dict[str, Any]:
    conservation_ok = check_conservation(1000.0, 925.0, unmatched_total=75.0)
    conservation_leak = check_conservation(1000.0, 925.0, unmatched_total=0.0)

    df = pd.DataFrame({"object_key": ["k3", "k1", "k2"], "score": [30.0, 10.0, 20.0]})
    good_inv = check_permutation_invariance(
        lambda d: d.assign(rank=d["score"].rank(ascending=False)),
        df,
        "object_key",
        ["score", "rank"],
    )
    bad_pos_bug = check_permutation_invariance(
        lambda d: d.assign(rank=np.arange(len(d), dtype=float)),
        df,
        "object_key",
        ["rank"],
    )

    polys = gpd.GeoDataFrame({"zone": ["Z1"]}, geometry=[Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])], crs="EPSG:32650")
    pts = gpd.GeoDataFrame(
        {"pt_id": ["interior", "edge", "outside"]},
        geometry=[Point(5, 5), Point(0, 5), Point(20, 5)],
        crs="EPSG:32650",
    )
    boundary = compare_boundary_predicates(pts, polys, "pt_id")

    ndvi_scale = check_scale_invariance(lambda nir, red: (nir - red) / (nir + red), 0.4, 0.2)
    savi_scale = check_scale_invariance(lambda nir, red: 1.5 * (nir - red) / (nir + red + 0.5), 0.4, 0.2)

    return {
        "ok": True,
        "conservation_ok": conservation_ok,
        "conservation_leak": conservation_leak,
        "permutation_good_invariant": good_inv["invariant"],
        "permutation_pos_bug_invariant": bad_pos_bug["invariant"],
        "boundary": boundary,
        "ndvi_scale_invariant": ndvi_scale["scale_invariant"],
        "savi_scale_invariant": savi_scale["scale_invariant"],
    }


if __name__ == "__main__":
    payload = run_demo()
    text = json.dumps(payload, ensure_ascii=False)
    if result_path := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(result_path).write_text(text, encoding="utf-8")
    print(text)
