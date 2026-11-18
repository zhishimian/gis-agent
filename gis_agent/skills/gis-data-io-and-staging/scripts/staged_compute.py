"""One editable JSON-job example for ordinary and controlled Python execution.

Requires NumPy. CLI: python staged_compute.py job.json. Job has inputs,
parameters, outputs (same shape as local_replay). mode=prepare computes and
persists NPY (outputs.prepared); mode=summarize reads inputs.prepared and writes
outputs.statistics JSON. Parameters: size (default 1000), rounds (default 3).
Prepare is deliberately separate from summarize/export. No implicit cache or
file-existence resume; existing destinations raise. All side effects are in
declared outputs. Errors propagate nonzero; partial files remain diagnostic.
"""
import json
import os
import sys
from pathlib import Path
from time import perf_counter

import numpy as np


def main(job):
    started = perf_counter()
    parameters, outputs = job['parameters'], job['outputs']
    mode = parameters['mode']
    paths = {key: Path(value) for key, value in outputs.items()}
    if any(path.exists() for path in paths.values()):
        raise FileExistsError('Choose fresh versioned output paths')
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    if mode == 'prepare':
        size, rounds = parameters.get('size', 1000), parameters.get('rounds', 3)
        if type(size) is not int or not 0 < size <= 10000000 or type(rounds) is not int or not 0 <= rounds <= 10000:
            raise ValueError('Explicit bounded size and rounds required')
        values = np.linspace(0, 1, size, dtype='float64')
        for _ in range(rounds):
            values = np.sin(values) + .1
        with paths['prepared'].open('xb') as stream:
            np.save(stream, values, allow_pickle=False)
        metrics = {'count': size, 'rounds': rounds}
    elif mode == 'summarize':
        values = np.load(job['inputs']['prepared'], allow_pickle=False)
        if not np.isfinite(values).all():
            raise ValueError('Resolve missing/nonfinite observations explicitly')
        metrics = {'count': int(values.size), 'sum': float(values.sum(dtype='float64'))}
        paths['statistics'].write_text(json.dumps(metrics, allow_nan=False), encoding='utf-8')
    else:
        raise ValueError('mode must be prepare or summarize')
    return {'outputs': {k: str(p.resolve()) for k, p in paths.items()},
            'metrics': metrics | {'elapsed_seconds': perf_counter()-started}, 'warnings': [], 'assumptions': []}


if __name__ == '__main__':
    result = main(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
    text = json.dumps(result, allow_nan=False)
    if os.environ.get('GIS_AGENT_RESULT_PATH'):
        Path(os.environ['GIS_AGENT_RESULT_PATH']).write_text(text, encoding='utf-8')
    print(text)
