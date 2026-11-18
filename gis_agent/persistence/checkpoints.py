from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from time import time
from typing import Any, Iterator


@dataclass(frozen=True)
class StateSnapshot:
    values: dict[str, Any]
    next: tuple[str, ...]
    pending_call: dict[str, Any] | None = None


class MemoryCheckpointer:
    def __init__(self, backing: dict[str, Any] | None = None) -> None:
        self._records: dict[str, StateSnapshot] = backing if backing is not None else {}

    def get(self, thread_id: str) -> StateSnapshot:
        return self._records.get(thread_id, StateSnapshot(values={}, next=()))

    def put(
        self,
        thread_id: str,
        values: dict[str, Any],
        next_nodes: tuple[str, ...],
        pending_call: dict[str, Any] | None = None,
    ) -> StateSnapshot:
        snap = StateSnapshot(values=dict(values), next=tuple(next_nodes), pending_call=pending_call)
        self._records[thread_id] = snap
        return snap


class SqliteCheckpointer:
    def __init__(self, conn: sqlite3.Connection, owns_connection: bool = False) -> None:
        self.conn = conn
        self._owns = owns_connection
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gis_agent_checkpoints (
                thread_id TEXT PRIMARY KEY,
                values_json TEXT NOT NULL,
                next_json TEXT NOT NULL,
                pending_call_json TEXT,
                updated_at REAL NOT NULL
            )
            """
        )
        self.conn.commit()

    @classmethod
    @contextmanager
    def from_conn_string(cls, path: str | Path) -> Iterator["SqliteCheckpointer"]:
        target = str(path)
        if target != ":memory:":
            Path(target).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target, timeout=30.0, check_same_thread=False)
        saver = cls(conn, owns_connection=True)
        try:
            yield saver
        finally:
            conn.close()

    def close(self) -> None:
        if self._owns:
            self.conn.close()

    def get(self, thread_id: str) -> StateSnapshot:
        row = self.conn.execute(
            "SELECT values_json, next_json, pending_call_json FROM gis_agent_checkpoints WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            return StateSnapshot(values={}, next=())
        return StateSnapshot(
            values=json.loads(row[0]),
            next=tuple(json.loads(row[1])),
            pending_call=json.loads(row[2]) if row[2] else None,
        )

    def put(
        self,
        thread_id: str,
        values: dict[str, Any],
        next_nodes: tuple[str, ...],
        pending_call: dict[str, Any] | None = None,
    ) -> StateSnapshot:
        values_copy = dict(values)
        self.conn.execute(
            """
            INSERT INTO gis_agent_checkpoints (thread_id, values_json, next_json, pending_call_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                values_json = excluded.values_json,
                next_json = excluded.next_json,
                pending_call_json = excluded.pending_call_json,
                updated_at = excluded.updated_at
            """,
            (
                thread_id,
                json.dumps(values_copy, ensure_ascii=False),
                json.dumps(list(next_nodes), ensure_ascii=False),
                json.dumps(pending_call, ensure_ascii=False) if pending_call is not None else None,
                time(),
            ),
        )
        self.conn.commit()
        return StateSnapshot(values=values_copy, next=tuple(next_nodes), pending_call=pending_call)


def coerce_checkpointer(saver: Any) -> MemoryCheckpointer | SqliteCheckpointer:
    if saver is None:
        return MemoryCheckpointer()
    if isinstance(saver, (MemoryCheckpointer, SqliteCheckpointer)):
        return saver
    if isinstance(getattr(saver, "conn", None), sqlite3.Connection):
        return SqliteCheckpointer(saver.conn, owns_connection=False)
    if hasattr(saver, "storage") and isinstance(saver.storage, dict):
        bucket = saver.storage.setdefault("__gis_agent_v9__", {})
        return MemoryCheckpointer(bucket)
    return MemoryCheckpointer()
