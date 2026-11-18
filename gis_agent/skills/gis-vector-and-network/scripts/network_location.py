"""Exact tiny facility-location examples over a declared OD cost matrix.

Requires NumPy. Import locate(costs, weights, p, objective, threshold).
Rows are demand, columns candidate facilities; units/direction belong to input.
Returns candidate column positions and objective, not construction coordinates.
Infinite costs mean unreachable. No routing, demand allocation policy or MILP.
CLI: python network_location.py settings.json (costs/weights/p/objective).
JSON null costs mean unreachable. Invalid/infeasible inputs raise, exit nonzero.
Enumeration is capped at 100000 combinations; use a mature solver beyond it.
"""
import itertools
import json
import math
import os
import sys
from pathlib import Path

import numpy as np


def locate(costs, weights, p, objective='p_median', threshold=None):
    costs = np.array([[np.inf if v is None else v for v in row] for row in costs], dtype=float)
    weights = np.asarray(weights, dtype=float)
    if costs.ndim != 2 or costs.shape[0] == 0 or weights.shape != (costs.shape[0],):
        raise ValueError('Demand rows, candidate columns and aligned weights required')
    if np.isnan(costs).any() or (costs < 0).any() or not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError('Nonnegative costs/weights; only costs may contain +infinity')
    if type(p) is not int or not 1 <= p <= costs.shape[1] or math.comb(costs.shape[1], p) > 100000:
        raise ValueError('Invalid p or enumeration budget exceeded')
    if objective not in {'p_median', 'p_center', 'maximum_coverage'}:
        raise ValueError('Unknown objective')
    if objective == 'maximum_coverage' and (threshold is None or not math.isfinite(threshold) or threshold < 0):
        raise ValueError('Coverage needs a finite nonnegative threshold')
    best = None
    active = weights > 0
    for sites in itertools.combinations(range(costs.shape[1]), p):
        distance = costs[:, sites].min(axis=1)
        if objective == 'maximum_coverage':
            score = -float(weights[distance <= threshold].sum())
        elif not np.isfinite(distance[active]).all():
            continue
        elif objective == 'p_median':
            score = float(np.dot(weights[active], distance[active]))
        else:
            score = float(distance[active].max()) if active.any() else 0.
        if best is None or score < best[0]:
            best = score, sites, distance
    if best is None:
        raise ValueError('No feasible selection covers positive-weight demands')
    score, sites, distance = best
    return {'sites': list(sites), 'objective': objective,
            'value': -score if objective == 'maximum_coverage' else score,
            'distance': [float(x) if np.isfinite(x) else None for x in distance],
            'unreachable_rows': np.flatnonzero(~np.isfinite(distance)).tolist()}


if __name__ == '__main__':
    result = locate(**json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
    text = json.dumps(result, allow_nan=False)
    if os.environ.get('GIS_AGENT_RESULT_PATH'):
        Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(text, encoding='utf-8')
    print(text)
