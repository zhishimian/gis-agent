"""Tiny synthetic catchment, NoData and work/cache examples; standard library.

Run without arguments or import demonstrate(). JSON goes to
GIS_AGENT_RESULT_PATH or stdout. Errors propagate. The acyclic flow graph has
equal-area cells and single receivers. The stencil uses four equal weights;
no missing-data imputation is permitted. This is not a terrain engine or cache
manager; real grids require their own masks, transforms and method policies.
"""
import hashlib
import json
import os
from pathlib import Path


def upstream_cells(receivers: list[int], outlet: int) -> set[int]:
    reverse = [[] for _ in receivers]
    for cell, receiver in enumerate(receivers):
        if receiver >= 0:
            reverse[receiver].append(cell)
    found = {outlet}
    pending = [outlet]
    while pending:
        for cell in reverse[pending.pop()]:
            if cell not in found:
                found.add(cell)
                pending.append(cell)
    return found


def stencil_mean(values: list[float], valid: list[bool]) -> float | None:
    return sum(values) / 4 if all(valid) else None


def cache_key(source: bytes, parameters: dict, implementation: bytes) -> str:
    record = {
        "input": hashlib.sha256(source).hexdigest(), "parameters": parameters,
        "implementation": hashlib.sha256(implementation).hexdigest(),
    }
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def demonstrate() -> dict:
    receivers = [2, 2, 3, 4, -1]
    upper = upstream_cells(receivers, 2)
    lower = upstream_cells(receivers, 4)
    values = [10.0, 12.0, 14.0, -9999.0]
    source, implementation = b"synthetic input", b"method-v1"
    parameters = {"crs": "local_metric", "shape": [2, 2], "cell_size": 10}
    key = cache_key(source, parameters, implementation)
    return {
        "upper_catchment": sorted(upper), "lower_catchment": sorted(lower),
        "lower_partition": sorted(lower - upper),
        "unsafe_stencil_mean": sum(values) / 4,
        "masked_stencil_mean": stencil_mean(values, [True, True, True, False]),
        "valid_stencil_mean": stencil_mean([10, 12, 14, 16], [True] * 4),
        "valid_zero": stencil_mean([0, 0, 0, 0], [True] * 4),
        "all_pairs": 100_000 * 1_000_000, "bounded_pairs": 8 * 1_000_000,
        "cache_key": key,
        "same_key": cache_key(source, parameters, implementation),
        "changed_input": cache_key(b"changed", parameters, implementation),
        "changed_grid": cache_key(source, {**parameters, "cell_size": 20}, implementation),
        "changed_code": cache_key(source, parameters, b"method-v2"),
    }


if __name__ == "__main__":
    text = json.dumps(demonstrate(), allow_nan=False)
    if output := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(output).write_text(text, encoding="utf-8")
    else:
        print(text)
