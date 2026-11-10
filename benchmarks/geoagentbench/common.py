"""Experiment storage and accounting. Does not modify the GIS-Agent harness."""
import ast
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
MATERIALS = PROJECT / 'outputs/benchmark_materials_20261109'
SOURCE = PROJECT / 'timu暂存/gis-benchmarks/GABench'
HOST = Path('D:/ac/envs/gis-agent/python.exe')
TZ = timezone(timedelta(hours=8))


def now():
    return datetime.now(TZ).isoformat()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    temporary.replace(path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda: f.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def credentials(reference):
    """Read literal connection settings without executing or printing user code."""
    tree = ast.parse(Path(reference).read_text(encoding='utf-8-sig'))
    key = os.environ.get('DASHSCOPE_API_KEY') or os.environ.get('BAILIAN_API_KEY')
    url = model = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                if kw.arg == 'api_key' and not key:
                    key = kw.value.value
                elif kw.arg == 'base_url':
                    url = kw.value.value
                elif kw.arg == 'model':
                    model = kw.value.value
    if not key or not url or not model:
        raise ValueError('Missing credential or endpoint; set DASHSCOPE_API_KEY and check reference file')
    return key, url, model


def frozen_sources():
    return {str(p.relative_to(PROJECT)).replace('\\', '/'): digest(p)
            for p in sorted((PROJECT / 'gis_agent').rglob('*'))
            if p.is_file() and p.suffix in {'.py', '.md', '.j2', '.txt', '.yaml', '.json'} and '__pycache__' not in p.parts}


def peak_period(time):
    return 8 <= datetime.fromisoformat(time).astimezone(TZ).hour < 22


def costs(usage, start, end):
    """Alibaba Beijing rates: input 2/output 8 CNY/M; cached input 10%."""
    n, out = usage.get('prompt_tokens'), usage.get('completion_tokens')
    if type(n) is not int or type(out) is not int or n < 0 or out < 0:
        raise ValueError('Unreconciled token usage')
    details = usage.get('prompt_tokens_details') or {}
    hit = usage.get('prompt_cache_hit_tokens', details.get('cached_tokens', 0)) or 0
    if type(hit) is not int or not 0 <= hit <= n:
        raise ValueError('Invalid cached usage')
    upper = (n * 2 + out * 8) / 1e6
    peak = ((n - hit) * 2 + hit * .2 + out * 8) / 1e6
    return {'input_tokens': n, 'cached_tokens': hit, 'output_tokens': out,
            'reasoning_tokens': (usage.get('completion_tokens_details') or {}).get('reasoning_tokens', 0),
            'peak_cny': peak, 'no_cache_peak_cny': upper,
            'estimated_cny': peak if peak_period(start) or peak_period(end) else peak / 2}


class Protection(RuntimeError):
    pass


def retryable_transport(error):
    cause = error.__cause__
    return (type(cause).__name__ in {'APIConnectionError', 'APITimeoutError'} or
            getattr(cause, 'status_code', None) in {429, 500, 502, 503, 504})


class Ledger:
    """Shared experiment-only budget; reserve before send, retain unknown charges."""
    def __init__(self, path, limit=50):
        self.path, self.limit = Path(path), limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS charges (id INTEGER PRIMARY KEY, task TEXT, reserved REAL, settled REAL, metadata TEXT)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def total(self, task=None):
        with self.connect() as db:
            sql = 'SELECT COALESCE(SUM(COALESCE(settled,reserved)),0) FROM charges'
            return db.execute(sql + (' WHERE task=?' if task else ''), (task,) if task else ()).fetchone()[0]

    def reserve(self, task, amount, per_task=3):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            total = db.execute('SELECT COALESCE(SUM(COALESCE(settled,reserved)),0) FROM charges').fetchone()[0]
            local = db.execute('SELECT COALESCE(SUM(COALESCE(settled,reserved)),0) FROM charges WHERE task=?', (task,)).fetchone()[0]
            if total + amount > self.limit or local + amount > per_task:
                raise Protection('Next request exceeds reserved experiment or task budget')
            return db.execute('INSERT INTO charges(task,reserved) VALUES (?,?)', (task, amount)).lastrowid

    def settle(self, identifier, charge, metadata):
        with self.connect() as db:
            reservation = db.execute('SELECT reserved FROM charges WHERE id=?', (identifier,)).fetchone()[0]
            if charge > reservation + 1e-8:
                raise Protection('Provider usage exceeds reserved upper bound')
            db.execute('UPDATE charges SET settled=?,metadata=? WHERE id=?', (charge, json.dumps(metadata), identifier))
