import os
import sqlite3
import json

DB_PATH = os.getenv("SQLITE_PATH", "/app/data/jobs.db")

def connect(sqlite_path: str= DB_PATH):
    con = sqlite3.connect(sqlite_path, timeout=5, isolation_level=None)  # autocommit off unless BEGIN
    con.row_factory = sqlite3.Row
    # Apply pragmas at connection level
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=5000;")
    return con

class tx:
    def __init__(self, con): self.con = con
    def __enter__(self): self.con.execute("BEGIN IMMEDIATE;"); return self.con
    def __exit__(self, exc_type, *_): self.con.commit() if exc_type is None else self.con.rollback()

def ai_audit_start(req_id: str, provider: str, model: str, endpoint: str, request_payload: dict):
    payload = json.dumps(request_payload, ensure_ascii=False)
    with connect() as con:
        con.execute(
            """INSERT OR IGNORE INTO ai_audit
               (req_id, provider, model, endpoint, request_payload)
               VALUES (?, ?, ?, ?, ?)""",
            (req_id, provider, model, endpoint, payload),
        )

def ai_audit_finish(req_id: str, response_payload: str | dict | None,
                    status_code: int | None, latency_ms: int, error: str | None = None):
    payload = (json.dumps(response_payload, ensure_ascii=False)
               if isinstance(response_payload, (dict, list)) else response_payload)
    with connect() as con:
        con.execute(
            """UPDATE ai_audit
               SET response_payload = ?, status_code = ?, latency_ms = ?, error = ?
               WHERE req_id = ?""",
            (payload, status_code, latency_ms, error, req_id),
        )