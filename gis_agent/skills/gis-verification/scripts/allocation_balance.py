"""Objective allocation facts, not a universal business-policy validator.

Requires pandas/NumPy. Import allocation_balance(expected_by_zone, allocations,
zone_key=..., value=..., unit=..., excluded_by_zone=None). Expected/excluded are
Series indexed by unique nonnull zone keys; allocations is a DataFrame. Nulls
and unknown zones remain explicit. Duplicate allocation rows are not removed.
CLI accepts settings JSON: expected CSV (zone/value), allocations CSV, optional
excluded CSV, zone_key/value/unit/output. CSV business keys are read as strings.
Output JSON includes balances and bounded counterexamples, no generic PASS.
Errors propagate; existing output raises. No changes to input files.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def allocation_balance(expected_by_zone, allocations, *, zone_key, value, unit, excluded_by_zone=None):
    if not unit:
        raise ValueError('Declare quantity units')
    for series in [expected_by_zone, *([] if excluded_by_zone is None else [excluded_by_zone])]:
        if not series.index.is_unique or series.index.hasnans:
            raise ValueError('Expected/excluded keys must be unique and nonnull')
    if excluded_by_zone is not None and not excluded_by_zone.index.isin(expected_by_zone.index).all():
        raise ValueError('Excluded totals contain unknown zones')
    data = allocations[[zone_key, value]].copy()
    data[value] = pd.to_numeric(data[value], errors='raise')
    known = data[zone_key].isin(expected_by_zone.index)
    rows = []
    for key, expected in expected_by_zone.items():
        values = data.loc[known & data[zone_key].eq(key), value]
        finite = np.isfinite(values.to_numpy(dtype=float, na_value=np.nan))
        unknown = int((~finite).sum())
        allocated = float(values[finite].sum())
        excluded = 0. if excluded_by_zone is None else excluded_by_zone.get(key, np.nan)
        complete = not unknown and pd.notna(expected) and np.isfinite(expected) and pd.notna(excluded) and np.isfinite(excluded)
        rows.append({'zone': str(key), 'expected': float(expected) if pd.notna(expected) and np.isfinite(expected) else None,
                     'allocated_known': allocated, 'allocation_rows': int(len(values)),
                     'excluded': float(excluded) if pd.notna(excluded) and np.isfinite(excluded) else None,
                     'unknown_count': unknown, 'residual': float(expected-allocated-excluded) if complete else None})
    residuals = [row['residual'] for row in rows]
    return {'unit': unit, 'zones': rows, 'zone_count': len(rows),
            'known_allocated_total': sum(row['allocated_known'] for row in rows),
            'residual_total': sum(residuals) if all(x is not None for x in residuals) else None,
            'zones_without_allocations': [row['zone'] for row in rows if not row['allocation_rows']][:10],
            'unknown_zone_rows': int((~known).sum()),
            'unknown_zone_examples': data.loc[~known, zone_key].astype(str).head(10).tolist(),
            'incomplete_zones': sum(row['residual'] is None for row in rows)}


if __name__ == '__main__':
    settings = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    key, value = settings['zone_key'], settings['value']
    def read(path):
        return pd.read_csv(path, dtype={key: str})
    expected = read(settings['expected']).set_index(key)[value]
    excluded = read(settings['excluded']).set_index(key)[value] if settings.get('excluded') else None
    result = allocation_balance(expected, read(settings['allocations']), zone_key=key, value=value,
                                unit=settings['unit'], excluded_by_zone=excluded)
    path = Path(settings['output'])
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(result, allow_nan=False, indent=2), encoding='utf-8')
    if os.environ.get('GIS_AGENT_RESULT_PATH'):
        Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
