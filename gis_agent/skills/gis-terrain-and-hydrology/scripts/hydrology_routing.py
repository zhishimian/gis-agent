from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
from typing import Any

import numpy as np

# Explicit D8 neighbor offsets for GRASS r.watershed directional encoding (1=NE .. 8=E counterclockwise).
GRASS_D8_OFFSETS: dict[int, tuple[int, int]] = {
    1: (-1, 1),   # NE
    2: (-1, 0),   # N
    3: (-1, -1),  # NW
    4: (0, -1),   # W
    5: (1, -1),   # SW
    6: (1, 0),    # S
    7: (1, 1),    # SE
    8: (0, 1),    # E
}

# ESRI / TauDEM power-of-two encoding (1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE).
ESRI_TO_GRASS: dict[int, int] = {
    1: 8,
    2: 7,
    4: 6,
    8: 5,
    16: 4,
    32: 3,
    64: 2,
    128: 1,
}


def grass_flow_accumulation(direction: np.ndarray, *, include_self: bool = True) -> np.ndarray:
    """Compute O(N) D8 flow accumulation via Kahn topological ordering on directional grid."""
    rows, cols = direction.shape
    in_degree = np.zeros((rows, cols), dtype=np.int32)
    downstream_r = np.full((rows, cols), -1, dtype=np.int32)
    downstream_c = np.full((rows, cols), -1, dtype=np.int32)

    for r in range(rows):
        for c in range(cols):
            code = int(direction[r, c])
            if code in GRASS_D8_OFFSETS:
                dr, dc = GRASS_D8_OFFSETS[code]
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    downstream_r[r, c] = nr
                    downstream_c[r, c] = nc
                    in_degree[nr, nc] += 1

    acc = np.ones((rows, cols), dtype=np.int64) if include_self else np.zeros((rows, cols), dtype=np.int64)
    queue: deque[tuple[int, int]] = deque(
        (int(r), int(c)) for r, c in zip(*np.where(in_degree == 0), strict=True)
    )
    while queue:
        r, c = queue.popleft()
        nr = int(downstream_r[r, c])
        nc = int(downstream_c[r, c])
        if nr >= 0:
            acc[nr, nc] += acc[r, c] + (0 if include_self else 1)
            in_degree[nr, nc] -= 1
            if in_degree[nr, nc] == 0:
                queue.append((nr, nc))
    return acc


def upstream_catchment(direction: np.ndarray, outlet: tuple[int, int]) -> np.ndarray:
    """Trace complete upstream contributing mask for one single outlet cell."""
    rows, cols = direction.shape
    reverse: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for r in range(rows):
        for c in range(cols):
            code = int(direction[r, c])
            if code in GRASS_D8_OFFSETS:
                dr, dc = GRASS_D8_OFFSETS[code]
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    reverse.setdefault((nr, nc), []).append((r, c))

    mask = np.zeros((rows, cols), dtype=bool)
    queue: deque[tuple[int, int]] = deque([outlet])
    mask[outlet] = True
    while queue:
        cur = queue.popleft()
        for src in reverse.get(cur, ()):
            if not mask[src]:
                mask[src] = True
                queue.append(src)
    return mask


def connected_inundation_volume(
    dem: np.ndarray,
    seed: tuple[int, int],
    water_level: float,
    cell_area: float,
) -> dict[str, Any]:
    """Compute hydraulically connected flood volume vs naive elevation threshold."""
    rows, cols = dem.shape
    valid = np.isfinite(dem)
    naive_mask = valid & (dem <= water_level)

    connected = np.zeros_like(naive_mask)
    if valid[seed] and dem[seed] <= water_level:
        queue: deque[tuple[int, int]] = deque([seed])
        connected[seed] = True
        while queue:
            r, c = queue.popleft()
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols and not connected[nr, nc] and naive_mask[nr, nc]:
                        connected[nr, nc] = True
                        queue.append((nr, nc))

    conn_vol = float(np.sum(np.maximum(0.0, water_level - dem[connected])) * cell_area)
    naive_vol = float(np.sum(np.maximum(0.0, water_level - dem[naive_mask])) * cell_area)
    return {
        "connected_cells": int(connected.sum()),
        "naive_cells": int(naive_mask.sum()),
        "connected_volume_m3": round(conn_vol, 3),
        "naive_volume_m3": round(naive_vol, 3),
    }


def run_demo() -> dict[str, Any]:
    # Linear channel draining down column 1 from row 0..3 into downstream outlet at (3, 1), with side tributaries.
    flow_dir = np.array(
        [
            [7, 6, 5],
            [8, 6, 4],
            [8, 6, 4],
            [8, 0, 4],
        ],
        dtype=np.int32,
    )
    acc = grass_flow_accumulation(flow_dir, include_self=True)
    upper_outlet = (1, 1)
    lower_outlet = (3, 1)
    upper_mask = upstream_catchment(flow_dir, upper_outlet)
    lower_mask = upstream_catchment(flow_dir, lower_outlet)

    # Disconnected low pocket at (0, 2) separated by ridge (12.0m) shows why flood inundation requires connectivity.
    dem = np.array(
        [
            [9.0, 8.0, 2.0],
            [9.0, 12.0, 12.0],
            [7.0, 6.0, 8.0],
            [6.0, 4.0, 6.0],
        ],
        dtype=np.float64,
    )
    flood = connected_inundation_volume(dem, seed=(3, 1), water_level=7.5, cell_area=100.0)
    return {
        "ok": True,
        "upper_accumulation_cells": int(acc[upper_outlet]),
        "lower_accumulation_cells": int(acc[lower_outlet]),
        "upper_mask_cells": int(upper_mask.sum()),
        "lower_mask_cells": int(lower_mask.sum()),
        "nested_overlap_cells": int((upper_mask & lower_mask).sum()),
        "flood": flood,
    }


if __name__ == "__main__":
    payload = run_demo()
    text = json.dumps(payload, ensure_ascii=False)
    if result_path := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(result_path).write_text(text, encoding="utf-8")
    print(text)
