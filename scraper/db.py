import json
import sqlite3
from pathlib import Path
from typing import Iterable, Tuple, Dict, Any
from datetime import date, datetime
import numpy as np


def connect(sqlite_path: str) -> sqlite3.Connection:
    print("DB path:", sqlite_path)
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

def insert_payloads(con: sqlite3.Connection, payloads: Iterable[Dict[str, Any]]) -> int:
    """
    Inserts payload JSON rows with INSERT OR IGNORE on unique job_url (generated).
    Returns count of actually inserted rows.
    """
    total_before = con.total_changes
    cur = con.cursor()
    for p in payloads:
        cur.execute(
            "INSERT OR IGNORE INTO raw_jobs(payload, source) VALUES (?, 'linkedin')",
            (json.dumps(p, ensure_ascii=False, default=_json_default, allow_nan=False),)
        )
    return int(con.total_changes - total_before)

def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, np.generic):
        return o.item()
    return str(o)