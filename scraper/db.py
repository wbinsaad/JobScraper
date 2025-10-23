import json
import sqlite3
from pathlib import Path
from typing import Iterable, Tuple, Dict, Any
from datetime import date, datetime
import numpy as np


def connect(sqlite_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(sqlite_path, timeout=5, isolation_level=None)  # autocommit off unless BEGIN
    con.row_factory = sqlite3.Row
    # Apply pragmas at connection level
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=5000;")
    return con

def begin(con: sqlite3.Connection):
    con.execute("BEGIN IMMEDIATE;")  # grab write lock only when needed

def commit(con: sqlite3.Connection):
    con.commit()

def rollback(con: sqlite3.Connection):
    con.rollback()

def start_run(con: sqlite3.Connection, params: Dict[str, Any]) -> int:
    cur = con.cursor()
    cur.execute(
        "INSERT INTO scrape_runs(started_at, status, params_json) VALUES (datetime('now'), 'running', ?)",
        (json.dumps(params, ensure_ascii=False),),
    )
    return int(cur.lastrowid)

def finish_run(con: sqlite3.Connection, run_id: int, *, status: str, total_requests: int, total_rows: int, new_rows: int, error_count: int) -> None:
    con.execute(
        "UPDATE scrape_runs SET finished_at=datetime('now'), status=?, total_requests=?, total_rows=?, new_rows=?, error_count=? WHERE id=?",
        (status, total_requests, total_rows, new_rows, error_count, run_id),
    )

def log_error(con: sqlite3.Connection, run_id: int, scope: str, error_type: str, message: str, context: Dict[str, Any] | None = None):
    con.execute(
        "INSERT INTO scrape_errors(run_id, scope, error_type, message, context_json) VALUES (?, ?, ?, ?, ?)",
        (run_id, scope, error_type, message[:2000], json.dumps(context or {}, ensure_ascii=False)),
    )

def insert_payloads(con: sqlite3.Connection, payloads: Iterable[Dict[str, Any]], *, source: str = "linkedin", run_id: int | None = None) -> int:
    """
    Inserts raw payload rows into the raw_jobs table.

    - Uses INSERT OR IGNORE to honor unique constraints (e.g., generated job_url).
    - Adapts to schema differences (payload vs payload_json column, optional run_id/source).
    Returns count of actually inserted rows.
    """
    cur = con.cursor()

    # Introspect table to match the current schema
    cols_info = list(cur.execute("PRAGMA table_info(raw_jobs)"))
    col_names = {row["name"] for row in cols_info}
    notnull = {row["name"]: bool(row["notnull"]) for row in cols_info}

    # Determine payload column name
    payload_col = "payload" if "payload" in col_names else ("payload_json" if "payload_json" in col_names else None)
    if payload_col is None:
        raise RuntimeError("raw_jobs table must have a 'payload' or 'payload_json' column")

    insert_cols = [payload_col]
    if "source" in col_names:
        insert_cols.append("source")
    if "run_id" in col_names:
        if notnull.get("run_id") and run_id is None:
            raise ValueError("run_id is required by the raw_jobs schema but was not provided")
        insert_cols.append("run_id")

    def to_row(p: Dict[str, Any]):
        payload_str = json.dumps(p, ensure_ascii=False, default=_json_default, allow_nan=False)
        values = [payload_str]
        if "source" in insert_cols:
            values.append(source)
        if "run_id" in insert_cols:
            values.append(run_id)
        return tuple(values)

    rows = [to_row(p) for p in payloads]
    if not rows:
        return 0

    placeholders = ", ".join("?" for _ in insert_cols)
    columns_sql = ", ".join(insert_cols)

    total_before = con.total_changes
    cur.executemany(
        f"INSERT OR IGNORE INTO raw_jobs({columns_sql}) VALUES ({placeholders})",
        rows,
    )
    return int(con.total_changes - total_before)

def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, np.generic):
        return o.item()
    return str(o)