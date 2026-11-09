"""Fisher-Jenks encoding shared by colors, class counts and legend labels.

Requires NumPy and jenkspy==0.4.1. Import classify_values or run with a JSON
settings path (values, k, optional sample_size/seed/max_fit_values). Nulls become
missing labels -1. No silent log transform or fallback algorithm. Exact fitting
above the explicit budget raises; opt-in sampling is reported as approximate.
Outputs JSON via stdout and optional GIS_AGENT_RESULT_PATH. Invalid settings
raise and exit nonzero. Plot labels positionally on the SAME row ordering.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np


def classify_values(values, *, method='fisher_jenks', k=5, sample_size=None, seed=0, max_fit_values=20000):
    if method != 'fisher_jenks':
        raise ValueError('Only original-domain fisher_jenks is implemented; choose other methods explicitly elsewhere')
    if type(k) is not int or k < 1 or type(max_fit_values) is not int or max_fit_values < 1:
        raise ValueError('k and max_fit_values must be positive integers')
    raw = np.asarray(values)
    if raw.dtype.kind in 'iu' and ((raw > 2**53) | (raw < -2**53)).any():
        raise ValueError('Integer values exceed exact Float64 precision; choose an explicit scaling/precision policy')
    if raw.dtype.kind == 'O' and any(isinstance(v, (int, np.integer)) and abs(int(v)) > 2**53 for v in raw.flat):
        raise ValueError('Integer values exceed exact Float64 precision')
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError('One-dimensional values required')
    valid = np.isfinite(array)
    observed = array[valid]
    labels = np.full(array.shape, -1, dtype=int)
    if not observed.size:
        return dict(lower=None, upper_bounds=[], labels=labels.tolist(), counts=[], requested_k=k,
                    effective_k=0, missing_count=int(array.size), method=method, approximate=False, fit_count=0, seed=seed)
    fit = observed
    if sample_size is not None:
        if type(sample_size) is not int or not 1 <= sample_size <= max_fit_values:
            raise ValueError('sample_size must be within the explicit fitting budget')
        if observed.size > sample_size:
            fit = np.random.default_rng(seed).choice(observed, size=sample_size, replace=False)
    if fit.size > max_fit_values:
        raise ValueError('Exact fitting budget exceeded; explicitly choose sampling or a suitable exact method')
    effective = min(k, int(np.unique(fit).size))
    if effective == 1:
        upper = [float(observed.max())]
    else:
        try:
            import jenkspy
        except ImportError as error:
            raise ImportError('Install the pinned jenkspy==0.4.1 in the actual GIS interpreter; no algorithm fallback') from error
        breaks = jenkspy.jenks_breaks(fit, n_classes=effective)
        upper = list(map(float, breaks[1:]))
        upper[-1] = float(observed.max())
    # Search INNER upper bounds, preserving a singleton minimum class.
    labels[valid] = np.searchsorted(upper[:-1], observed, side='left')
    counts = np.bincount(labels[valid], minlength=effective).tolist()
    return dict(lower=float(observed.min()), upper_bounds=upper, labels=labels.tolist(), counts=counts,
                requested_k=k, effective_k=effective, missing_count=int((~valid).sum()),
                method=method, approximate=fit.size < observed.size, fit_count=int(fit.size), seed=seed)


def legend_labels(encoding):
    """Same closed-first/right-closed intervals as classify_values labels."""
    upper = encoding['upper_bounds']
    lower = encoding['lower']
    return [f"{'[' if i == 0 else '('}{lower if i == 0 else upper[i-1]:g}, {end:g}]"
            for i, end in enumerate(upper)]


if __name__ == '__main__':
    result = classify_values(**json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
    text = json.dumps(result, allow_nan=False)
    if os.environ.get('GIS_AGENT_RESULT_PATH'):
        Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(text, encoding='utf-8')
    print(text)
