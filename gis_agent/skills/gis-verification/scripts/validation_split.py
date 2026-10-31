"""Synthetic model-selection counterexample; standard library, no arguments.

Run directly or import demonstrate(). JSON goes to GIS_AGENT_RESULT_PATH or
stdout. Errors propagate. Fixed predictions isolate selection leakage; this
does not implement interpolation or estimate spatial generalization error.
"""
import json
import math
import os
from pathlib import Path


def demonstrate() -> dict:
    train_ids, validation_ids, test_ids = [0, 1], [2, 3], [4, 5]
    candidates = {"low": 0.0, "high": 4.0}

    def rmse(prediction: float, observed: list[float]) -> float:
        return math.sqrt(sum((prediction - value) ** 2 for value in observed) / len(observed))

    validation = {name: rmse(value, [0.0, 1.0]) for name, value in candidates.items()}
    selected = min(validation, key=validation.get)
    final_scores = {name: rmse(value, [4.0, 5.0]) for name, value in candidates.items()}
    test_selected = min(final_scores, key=final_scores.get)
    return {
        "train_ids": train_ids, "validation_ids": validation_ids, "test_ids": test_ids,
        "selected_on_validation": selected, "final_test_rmse": final_scores[selected],
        "selected_on_test": test_selected, "test_selected_rmse": final_scores[test_selected],
        "validation_rmse": validation,
    }


if __name__ == "__main__":
    text = json.dumps(demonstrate(), allow_nan=False)
    if output := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(output).write_text(text, encoding="utf-8")
    else:
        print(text)
