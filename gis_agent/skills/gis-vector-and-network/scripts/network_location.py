"""Facility location solvers over a declared OD cost matrix.

Supports:
- Exhaustive enumeration for tiny unconstrained matrices (`locate`, <= 100,000 combos).
- Industrial-scale MILP via `scipy.optimize.milp` (HiGHS) supporting `p_median`,
  `p_center`, `maximum_coverage`, `minimum_facilities` (LSCP), optional site
  `capacities` and `required_sites` (`locate_milp`).
- Probabilistic Huff gravity market-share capture (`huff_market_share`).

Dependencies: NumPy, SciPy >= 1.9 (`scipy.optimize.milp`).
Rows are demand, columns candidate facilities; infinite / null costs mean unreachable.
"""
import itertools
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix


def _prepare_location_inputs(costs, weights, required_sites=None):
    cost_arr = np.array([[np.inf if v is None else v for v in row] for row in costs], dtype=float)
    weight_arr = np.asarray(weights, dtype=float)
    if cost_arr.ndim != 2 or cost_arr.shape[0] == 0 or cost_arr.shape[1] == 0 or weight_arr.shape != (cost_arr.shape[0],):
        raise ValueError("Demand rows, candidate columns and aligned weights required")
    if np.isnan(cost_arr).any() or (cost_arr < 0).any() or not np.isfinite(weight_arr).all() or (weight_arr < 0).any():
        raise ValueError("Nonnegative costs/weights; only costs may contain +infinity")
    req = sorted({int(s) for s in (required_sites or ())})
    if any(s < 0 or s >= cost_arr.shape[1] for s in req):
        raise ValueError("required_sites indices out of range")
    return cost_arr, weight_arr, req


def _post_evaluate(cost_arr, sites, weights):
    sites = sorted(int(s) for s in sites)
    if not sites:
        dist = np.full(cost_arr.shape[0], np.inf, dtype=float)
    else:
        sub = cost_arr[:, sites]
        dist = sub.min(axis=1)
    return sites, dist


def locate_milp(
    costs,
    weights,
    *,
    p=None,
    objective="p_median",
    threshold=None,
    capacities=None,
    required_sites=None,
    time_limit=30.0,
):
    """Exact sparse MILP solver using SciPy HiGHS (`scipy.optimize.milp`).

    Objectives:
    - `p_median`: minimize total weighted cost with exact `p` sites.
    - `p_center`: minimize worst active-demand cost with exact `p` sites.
    - `maximum_coverage`: maximize covered demand weight within `threshold` and `p` sites.
    - `minimum_facilities`: minimize open sites to cover all active demand within `threshold`.
    """
    cost_arr, weight_arr, req = _prepare_location_inputs(costs, weights, required_sites)
    n_dem, n_fac = cost_arr.shape
    obj = str(objective).strip().lower()
    if obj not in {"p_median", "p_center", "maximum_coverage", "minimum_facilities"}:
        raise ValueError("Unknown objective; expected p_median, p_center, maximum_coverage, or minimum_facilities")

    if obj != "minimum_facilities":
        if type(p) is not int or not 1 <= p <= n_fac:
            raise ValueError("Invalid integer p in [1, n_facilities]")
        if len(req) > p:
            raise ValueError("required_sites count exceeds budget p")
    if obj in {"maximum_coverage", "minimum_facilities"}:
        if threshold is None or not math.isfinite(threshold) or threshold < 0:
            raise ValueError("Coverage objectives require a finite nonnegative threshold")
    cap_arr = None
    if capacities is not None:
        cap_arr = np.asarray(capacities, dtype=float)
        if cap_arr.shape != (n_fac,) or not np.isfinite(cap_arr).all() or (cap_arr < 0).any():
            raise ValueError("capacities must match candidate columns and be finite nonnegative")

    active = np.flatnonzero(weight_arr > 0)
    options = {"time_limit": float(time_limit)} if time_limit is not None else {}

    if obj == "minimum_facilities":
        # Pure binary y_0..y_{m-1}
        c_vec = np.ones(n_fac, dtype=float)
        rows, cols, vals = [], [], []
        lb, ub = [], []
        r_idx = 0
        for i in active:
            elig = np.flatnonzero(cost_arr[i] <= float(threshold))
            if len(elig) == 0:
                raise ValueError(f"Demand row {int(i)} has no candidate facility within threshold {threshold}")
            for j in elig:
                rows.append(r_idx)
                cols.append(int(j))
                vals.append(1.0)
            lb.append(1.0)
            ub.append(np.inf)
            r_idx += 1
        for r in req:
            rows.append(r_idx)
            cols.append(r)
            vals.append(1.0)
            lb.append(1.0)
            ub.append(1.0)
            r_idx += 1
        mat = coo_matrix((vals, (rows, cols)), shape=(r_idx, n_fac)).tocsc()
        res = milp(
            c=c_vec,
            integrality=np.ones(n_fac, dtype=int),
            bounds=Bounds(0.0, 1.0),
            constraints=LinearConstraint(mat, lb, ub),
            options=options,
        )
        if not res.success:
            raise ValueError(f"MILP failed for minimum_facilities: {res.message}")
        sites = [int(j) for j in range(n_fac) if res.x[j] > 0.5]
        sites, dist = _post_evaluate(cost_arr, sites, weight_arr)
        return {
            "sites": sites,
            "objective": obj,
            "value": float(len(sites)),
            "distance": [float(x) if np.isfinite(x) else None for x in dist],
            "unreachable_rows": np.flatnonzero(~np.isfinite(dist)).tolist(),
            "assignments": {int(i): int(sites[int(np.argmin(cost_arr[i, sites]))]) for i in range(n_dem) if np.isfinite(dist[i])},
            "solver": "milp",
            "status": int(res.status),
        }

    if obj == "maximum_coverage" and cap_arr is None:
        # Uncapacitated maximum coverage: binary y_j + binary u_i for coverable active demands
        coverable = [int(i) for i in active if np.any(cost_arr[i] <= float(threshold))]
        n_cov = len(coverable)
        n_vars = n_fac + n_cov
        c_vec = np.zeros(n_vars, dtype=float)
        for k, i in enumerate(coverable):
            c_vec[n_fac + k] = -float(weight_arr[i])
        rows, cols, vals = [], [], []
        lb, ub = [], []
        r_idx = 0
        # sum_j y_j == p
        for j in range(n_fac):
            rows.append(r_idx)
            cols.append(j)
            vals.append(1.0)
        lb.append(float(p))
        ub.append(float(p))
        r_idx += 1
        for r in req:
            rows.append(r_idx)
            cols.append(r)
            vals.append(1.0)
            lb.append(1.0)
            ub.append(1.0)
            r_idx += 1
        # u_k - sum_{j in N_i} y_j <= 0
        for k, i in enumerate(coverable):
            elig = np.flatnonzero(cost_arr[i] <= float(threshold))
            rows.append(r_idx)
            cols.append(n_fac + k)
            vals.append(1.0)
            for j in elig:
                rows.append(r_idx)
                cols.append(int(j))
                vals.append(-1.0)
            lb.append(-np.inf)
            ub.append(0.0)
            r_idx += 1
        mat = coo_matrix((vals, (rows, cols)), shape=(r_idx, n_vars)).tocsc()
        res = milp(
            c=c_vec,
            integrality=np.ones(n_vars, dtype=int),
            bounds=Bounds(0.0, 1.0),
            constraints=LinearConstraint(mat, lb, ub),
            options=options,
        )
        if not res.success:
            raise ValueError(f"MILP failed for maximum_coverage: {res.message}")
        sites = [int(j) for j in range(n_fac) if res.x[j] > 0.5]
        sites, dist = _post_evaluate(cost_arr, sites, weight_arr)
        covered_val = float(weight_arr[np.isfinite(dist) & (dist <= float(threshold))].sum())
        return {
            "sites": sites,
            "objective": obj,
            "value": covered_val,
            "distance": [float(x) if np.isfinite(x) else None for x in dist],
            "unreachable_rows": np.flatnonzero(~np.isfinite(dist)).tolist(),
            "assignments": {int(i): int(sites[int(np.argmin(cost_arr[i, sites]))]) for i in range(n_dem) if np.isfinite(dist[i])},
            "solver": "milp",
            "status": int(res.status),
        }

    # General assignment MILP over sparse finite/eligible pairs (i, j)
    pair_list = []
    pairs_by_row = {int(i): [] for i in active}
    pairs_by_col = {j: [] for j in range(n_fac)}
    for i in active:
        if obj == "maximum_coverage":
            js = np.flatnonzero(cost_arr[i] <= float(threshold))
        else:
            js = np.flatnonzero(np.isfinite(cost_arr[i]))
        if obj in {"p_median", "p_center"} and len(js) == 0:
            raise ValueError("No feasible selection covers positive-weight demands")
        for j in js:
            idx = len(pair_list)
            pair_list.append((int(i), int(j)))
            pairs_by_row[int(i)].append(idx)
            pairs_by_col[int(j)].append(idx)

    n_pairs = len(pair_list)
    has_z = 1 if obj == "p_center" else 0
    n_vars = n_fac + n_pairs + has_z
    z_col = n_fac + n_pairs

    c_vec = np.zeros(n_vars, dtype=float)
    integrality = np.zeros(n_vars, dtype=int)
    integrality[:n_fac] = 1
    if obj == "p_center":
        integrality[n_fac : n_fac + n_pairs] = 1
        c_vec[z_col] = 1.0
    elif obj == "p_median":
        for idx, (i, j) in enumerate(pair_list):
            c_vec[n_fac + idx] = float(weight_arr[i] * cost_arr[i, j])
    else:  # capacitated maximum_coverage
        for idx, (i, _j) in enumerate(pair_list):
            c_vec[n_fac + idx] = -float(weight_arr[i])

    lb_var = np.zeros(n_vars, dtype=float)
    ub_var = np.ones(n_vars, dtype=float)
    if has_z:
        ub_var[z_col] = np.inf

    rows, cols, vals = [], [], []
    lb, ub = [], []
    r_idx = 0

    # 1. Exact p sites constraint
    for j in range(n_fac):
        rows.append(r_idx)
        cols.append(j)
        vals.append(1.0)
    lb.append(float(p))
    ub.append(float(p))
    r_idx += 1

    # 2. Required sites
    for r in req:
        rows.append(r_idx)
        cols.append(r)
        vals.append(1.0)
        lb.append(1.0)
        ub.append(1.0)
        r_idx += 1

    # 3. Row assignment / coverage constraints
    for i in active:
        pidxs = pairs_by_row[int(i)]
        if not pidxs:
            continue
        for idx in pidxs:
            rows.append(r_idx)
            cols.append(n_fac + idx)
            vals.append(1.0)
        if obj == "maximum_coverage":
            lb.append(-np.inf)
            ub.append(1.0)
        else:
            lb.append(1.0)
            ub.append(1.0)
        r_idx += 1

    # 4. Linking x_ij <= y_j
    for idx, (_i, j) in enumerate(pair_list):
        rows.extend([r_idx, r_idx])
        cols.extend([n_fac + idx, j])
        vals.extend([1.0, -1.0])
        lb.append(-np.inf)
        ub.append(0.0)
        r_idx += 1

    # 5. Optional capacities: sum_i w_i x_ij - cap_j y_j <= 0
    if cap_arr is not None:
        for j in range(n_fac):
            pidxs = pairs_by_col[j]
            if not pidxs:
                continue
            for idx in pidxs:
                i, _ = pair_list[idx]
                rows.append(r_idx)
                cols.append(n_fac + idx)
                vals.append(float(weight_arr[i]))
            rows.append(r_idx)
            cols.append(j)
            vals.append(-float(cap_arr[j]))
            lb.append(-np.inf)
            ub.append(0.0)
            r_idx += 1

    # 6. Minimax bottleneck z for p_center
    if obj == "p_center":
        for i in active:
            for idx in pairs_by_row[int(i)]:
                _ii, j = pair_list[idx]
                rows.append(r_idx)
                cols.append(n_fac + idx)
                vals.append(float(cost_arr[i, j]))
            rows.append(r_idx)
            cols.append(z_col)
            vals.append(-1.0)
            lb.append(-np.inf)
            ub.append(0.0)
            r_idx += 1

    mat = coo_matrix((vals, (rows, cols)), shape=(r_idx, n_vars)).tocsc()
    res = milp(
        c=c_vec,
        integrality=integrality,
        bounds=Bounds(lb_var, ub_var),
        constraints=LinearConstraint(mat, lb, ub),
        options=options,
    )
    if not res.success:
        raise ValueError(f"No feasible selection satisfies objective/capacities: {res.message}")

    sites = [int(j) for j in range(n_fac) if res.x[j] > 0.5]
    sites, dist = _post_evaluate(cost_arr, sites, weight_arr)
    if obj == "p_median":
        val = float(res.fun)
    elif obj == "p_center":
        val = float(dist[active].max()) if len(active) else 0.0
    else:
        val = float(-res.fun)

    assignments = {}
    for idx, (i, j) in enumerate(pair_list):
        if res.x[n_fac + idx] > 1e-6:
            assignments.setdefault(i, []).append({"facility_col": j, "fraction": round(float(res.x[n_fac + idx]), 6)})

    return {
        "sites": sites,
        "objective": obj,
        "value": val,
        "distance": [float(x) if np.isfinite(x) else None for x in dist],
        "unreachable_rows": np.flatnonzero(~np.isfinite(dist)).tolist(),
        "assignments": assignments,
        "solver": "milp",
        "status": int(res.status),
    }


def locate(
    costs,
    weights,
    p,
    objective="p_median",
    threshold=None,
    *,
    solver="auto",
    capacities=None,
    required_sites=None,
    time_limit=30.0,
):
    """Unified facility location entrypoint with tiny enumeration and HiGHS MILP."""
    cost_arr, weight_arr, req = _prepare_location_inputs(costs, weights, required_sites)
    obj = str(objective).strip().lower()
    solver_norm = str(solver).strip().lower()
    if solver_norm not in {"auto", "enumerate", "milp"}:
        raise ValueError("solver must be 'auto', 'enumerate', or 'milp'")

    use_enum = (
        solver_norm == "enumerate"
        or (
            solver_norm == "auto"
            and capacities is None
            and not req
            and obj in {"p_median", "p_center", "maximum_coverage"}
            and type(p) is int
            and 1 <= p <= cost_arr.shape[1]
            and math.comb(cost_arr.shape[1], p) <= 100000
        )
    )
    if not use_enum:
        return locate_milp(
            cost_arr,
            weight_arr,
            p=p,
            objective=obj,
            threshold=threshold,
            capacities=capacities,
            required_sites=required_sites,
            time_limit=time_limit,
        )

    if capacities is not None or req:
        raise ValueError("Exhaustive enumeration does not support capacities or required_sites; use solver='milp'")
    if type(p) is not int or not 1 <= p <= cost_arr.shape[1] or math.comb(cost_arr.shape[1], p) > 100000:
        raise ValueError("Invalid p or enumeration budget exceeded")
    if obj not in {"p_median", "p_center", "maximum_coverage"}:
        raise ValueError("Unknown objective")
    if obj == "maximum_coverage" and (threshold is None or not math.isfinite(threshold) or threshold < 0):
        raise ValueError("Coverage needs a finite nonnegative threshold")
    best = None
    active = weight_arr > 0
    for sites in itertools.combinations(range(cost_arr.shape[1]), p):
        distance = cost_arr[:, sites].min(axis=1)
        if obj == "maximum_coverage":
            score = -float(weight_arr[distance <= threshold].sum())
        elif not np.isfinite(distance[active]).all():
            continue
        elif obj == "p_median":
            score = float(np.dot(weight_arr[active], distance[active]))
        else:
            score = float(distance[active].max()) if active.any() else 0.0
        if best is None or score < best[0]:
            best = score, sites, distance
    if best is None:
        raise ValueError("No feasible selection covers positive-weight demands")
    score, sites, distance = best
    return {
        "sites": list(sites),
        "objective": obj,
        "value": -score if obj == "maximum_coverage" else score,
        "distance": [float(x) if np.isfinite(x) else None for x in distance],
        "unreachable_rows": np.flatnonzero(~np.isfinite(distance)).tolist(),
    }


def huff_market_share(
    costs,
    attractiveness,
    *,
    beta=2.0,
    demand_weights=None,
    threshold=None,
    min_cost=1e-6,
):
    """Huff probabilistic gravity model P_ij = (A_j / d_ij^beta) / sum_k(A_k / d_ik^beta)."""
    cost_arr = np.array([[np.inf if v is None else v for v in row] for row in costs], dtype=float)
    if cost_arr.ndim != 2 or cost_arr.shape[0] == 0 or cost_arr.shape[1] == 0:
        raise ValueError("Nonempty 2D cost matrix required")
    if np.isnan(cost_arr).any() or (cost_arr < 0).any():
        raise ValueError("Costs must be nonnegative; unreachable entries may be inf/null")
    attr = np.asarray(attractiveness, dtype=float)
    if attr.shape != (cost_arr.shape[1],) or not np.isfinite(attr).all() or (attr < 0).any():
        raise ValueError("attractiveness must align with candidate columns and be finite nonnegative")
    if not math.isfinite(beta) or beta <= 0:
        raise ValueError("Distance decay beta must be finite and positive")
    if not math.isfinite(min_cost) or min_cost <= 0:
        raise ValueError("min_cost must be finite and positive")

    n_dem, n_fac = cost_arr.shape
    w = np.ones(n_dem, dtype=float) if demand_weights is None else np.asarray(demand_weights, dtype=float)
    if w.shape != (n_dem,) or not np.isfinite(w).all() or (w < 0).any():
        raise ValueError("demand_weights must align with demand rows and be finite nonnegative")

    elig = np.isfinite(cost_arr)
    if threshold is not None:
        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError("threshold must be finite and nonnegative")
        elig = elig & (cost_arr <= float(threshold))

    util = np.zeros_like(cost_arr, dtype=float)
    eff_cost = np.maximum(cost_arr[elig], float(min_cost))
    col_idx = np.broadcast_to(np.arange(n_fac), cost_arr.shape)[elig]
    util[elig] = attr[col_idx] / (eff_cost ** float(beta))

    row_sums = util.sum(axis=1, keepdims=True)
    probs = np.divide(util, row_sums, out=np.zeros_like(util), where=row_sums > 0)
    capture = (probs.T @ w).astype(float)
    total_captured = float(capture.sum())
    shares = (capture / total_captured).tolist() if total_captured > 0 else [0.0] * n_fac
    unserved = np.flatnonzero(row_sums[:, 0] <= 0).tolist()
    return {
        "probabilities": [[float(x) for x in row] for row in probs],
        "facility_capture": [float(x) for x in capture],
        "facility_share": shares,
        "total_captured_demand": total_captured,
        "unserved_rows": unserved,
    }


if __name__ == "__main__":
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if "attractiveness" in cfg:
        result = huff_market_share(**cfg)
    else:
        result = locate(**cfg)
    text = json.dumps(result, allow_nan=False)
    if os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(text, encoding="utf-8")
    print(text)
