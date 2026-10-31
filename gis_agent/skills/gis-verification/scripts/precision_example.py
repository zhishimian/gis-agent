"""Synthetic Float32 rounding counterexample; requires NumPy, no GIS files.

Run without arguments or import demonstrate(). JSON goes to GIS_AGENT_RESULT_PATH
when set, otherwise stdout. Failures propagate. The base's two decimals are an
explicit assumption of this example; real precision and units follow the task.
"""
import json
import os
from pathlib import Path

import numpy as np


def demonstrate() -> dict:
    stored = np.float32("12.345")
    base = 2.11
    raw = float(stored)
    early = float(np.round(stored, 2))
    distance = float(np.nextafter(np.float32(100), np.float32(np.inf)))
    return {
        "stored_float32": raw,
        "base": base,
        "early_rounded_maximum": early,
        "height_from_raw": round(raw - base, 2),
        "height_after_early_rounding": round(early - base, 2),
        "distance": distance,
        "threshold": 100,
        "raw_within": distance <= 100,
        "rounded_within": round(distance, 2) <= 100,
    }


if __name__ == "__main__":
    text = json.dumps(demonstrate(), allow_nan=False)
    if output := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(output).write_text(text, encoding="utf-8")
    else:
        print(text)
