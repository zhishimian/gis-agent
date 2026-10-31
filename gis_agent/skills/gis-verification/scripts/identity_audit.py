"""Measure stable-key coverage and multiplicities across two vector versions.

Requires GeoPandas/pandas. Accepts one JSON settings path; emits structured JSON.
No geometry comparison, join policy or pass/fail verdict is inferred. Errors
propagate. IDs keep their stored types; strings are never coerced to numbers.
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

import geopandas as gpd


def audit(source: str, result: str, key: str, *, source_layer: str | None = None,
          result_layer: str | None = None, result_key: str | None = None,
          examples: int = 5) -> dict:
    if not 0 <= examples <= 50:
        raise ValueError("examples must be between 0 and 50")
    before = gpd.read_file(source, layer=source_layer, ignore_geometry=True)[key]
    after = gpd.read_file(result, layer=result_layer, ignore_geometry=True)[result_key or key]
    left, right = Counter(before.dropna()), Counter(after.dropna())
    lost, added = set(left) - set(right), set(right) - set(left)
    shared = set(left) & set(right)

    def sample(keys: set) -> list:
        return sorted(keys, key=repr)[:examples]

    return {"source_rows": len(before), "result_rows": len(after),
            "source_key_type": str(before.dtype), "result_key_type": str(after.dtype),
            "source_null_rows": int(before.isna().sum()), "result_null_rows": int(after.isna().sum()),
            "source_distinct": len(left), "result_distinct": len(right),
            "source_duplicate_rows": sum(n - 1 for n in left.values()),
            "result_duplicate_rows": sum(n - 1 for n in right.values()),
            "source_duplicate_examples": sample({k for k in left if left[k] > 1}),
            "result_duplicate_examples": sample({k for k in right if right[k] > 1}),
            "lost_ids": {"count": len(lost), "examples": sample(lost)},
            "added_ids": {"count": len(added), "examples": sample(added)},
            "shared_multiplicities": dict(Counter(f"{left[k]}:{right[k]}" for k in shared)),
            "changed_multiplicities": [
                {"id": k, "source_rows": left[k], "result_rows": right[k]}
                for k in sample({k for k in shared if left[k] != right[k]})],
            "coverage": "Full key columns; bounded examples; no spatial or attribute proof"}


if __name__ == "__main__":
    value = audit(**json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    Path(os.environ["GIS_AGENT_RESULT_PATH"]).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str), encoding="utf-8")
