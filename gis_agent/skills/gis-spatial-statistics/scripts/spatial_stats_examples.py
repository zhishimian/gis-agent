from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.distance import cdist


def tier_a_moran_i(coords: np.ndarray, values: np.ndarray, k: int = 3) -> float:
    """Compute row-standardized K-NN Global Moran's I using SciPy cKDTree (Tier A core dependency)."""
    n = len(values)
    tree = cKDTree(coords)
    _, indices = tree.query(coords, k=k + 1)
    w = np.zeros((n, n), dtype=np.float64)
    for i in range(n):
        nbrs = [j for j in indices[i] if j != i][:k]
        w[i, nbrs] = 1.0 / len(nbrs)
    z = values - np.mean(values)
    s0 = float(w.sum())
    num = float(z @ (w @ z))
    den = float(z @ z)
    return float((n / s0) * (num / den))


def tier_a_ordinary_kriging(
    obs_xy: np.ndarray,
    obs_z: np.ndarray,
    target_xy: np.ndarray,
    *,
    sill: float = 1.0,
    vrange: float = 40.0,
    nugget: float = 0.05,
) -> np.ndarray:
    """Solve linear Ordinary Kriging system with exponential variogram via NumPy/SciPy (Tier A fallback)."""

    def gamma(d: np.ndarray) -> np.ndarray:
        cov = (sill - nugget) * np.exp(-d / vrange)
        res = np.where(d > 0.0, sill - cov, 0.0)
        return res

    n = len(obs_z)
    d_obs = cdist(obs_xy, obs_xy)
    mat = np.ones((n + 1, n + 1), dtype=np.float64)
    mat[:n, :n] = gamma(d_obs)
    mat[n, n] = 0.0
    np.fill_diagonal(mat[:n, :n], 0.0)

    d_tar = cdist(obs_xy, target_xy)
    rhs = np.ones((n + 1, len(target_xy)), dtype=np.float64)
    rhs[:n, :] = gamma(d_tar)

    sol = np.linalg.solve(mat, rhs)
    weights = sol[:n, :]
    return weights.T @ obs_z


def spatial_block_folds(coords: np.ndarray, n_blocks_x: int = 2, n_blocks_y: int = 2) -> np.ndarray:
    """Assign observations to non-overlapping rectangular spatial CV blocks to prevent autocorrelation leakage."""
    x, y = coords[:, 0], coords[:, 1]
    bx = np.minimum(n_blocks_x - 1, np.floor((x - x.min()) / max(1e-9, (x.max() - x.min()) / n_blocks_x)).astype(int))
    by = np.minimum(n_blocks_y - 1, np.floor((y - y.min()) / max(1e-9, (y.max() - y.min()) / n_blocks_y)).astype(int))
    return by * n_blocks_x + bx


def run_demo() -> dict[str, Any]:
    rng = np.random.default_rng(42)
    gx, gy = np.meshgrid(np.linspace(0, 100, 6), np.linspace(0, 100, 6))
    obs_xy = np.column_stack([gx.ravel(), gy.ravel()])
    # Strong smooth east-west/north-south spatial gradient plus minor noise.
    obs_z = 0.08 * obs_xy[:, 0] + 0.05 * obs_xy[:, 1] + rng.normal(0.0, 0.25, len(obs_xy))

    moran_a = tier_a_moran_i(obs_xy, obs_z, k=4)
    pred_xy = np.array([[25.0, 25.0], [75.0, 75.0]], dtype=np.float64)
    krig_a = tier_a_ordinary_kriging(obs_xy, obs_z, pred_xy, sill=6.0, vrange=60.0, nugget=0.1)
    folds = spatial_block_folds(obs_xy, 2, 2)

    tier_b_pkgs = {
        pkg: importlib.util.find_spec(mod) is not None
        for pkg, mod in (("esda", "esda"), ("libpysal", "libpysal"), ("pykrige", "pykrige"), ("scikit-learn", "sklearn"))
    }
    result: dict[str, Any] = {
        "ok": True,
        "tier_b_installed": tier_b_pkgs,
        "moran_i_tier_a": round(moran_a, 6),
        "kriging_tier_a": [round(float(v), 4) for v in krig_a],
        "spatial_block_counts": np.bincount(folds).tolist(),
    }

    if all(tier_b_pkgs.values()):
        from esda import Moran
        from libpysal.weights import KNN
        from pykrige.ok import OrdinaryKriging

        w = KNN.from_array(obs_xy, k=4)
        w.transform = "r"
        moran_b = Moran(obs_z, w, permutations=99)
        ok_model = OrdinaryKriging(
            obs_xy[:, 0],
            obs_xy[:, 1],
            obs_z,
            variogram_model="exponential",
            variogram_parameters={"sill": 6.0, "range": 60.0, "nugget": 0.1},
        )
        krig_b, _ = ok_model.execute("points", pred_xy[:, 0], pred_xy[:, 1])
        result["moran_i_tier_b"] = round(float(moran_b.I), 6)
        result["moran_p_sim_tier_b"] = round(float(moran_b.p_sim), 4)
        result["kriging_tier_b"] = [round(float(v), 4) for v in krig_b]
    return result


if __name__ == "__main__":
    payload = run_demo()
    text = json.dumps(payload, ensure_ascii=False)
    if result_path := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(result_path).write_text(text, encoding="utf-8")
    print(text)
