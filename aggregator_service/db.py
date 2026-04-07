import glob
import os
import sqlite3
from pathlib import Path
from typing import Iterable


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=5000;")
    return con


def apply_migrations(con: sqlite3.Connection, migrate_dir: str) -> list[str]:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    pattern = str(Path(migrate_dir) / "*.sql")
    files = sorted(glob.glob(pattern))
    if not files:
        raise RuntimeError(f"No migration files found in {migrate_dir}")

    applied: list[str] = []
    for path in files:
        name = os.path.basename(path)
        row = con.execute("SELECT 1 FROM schema_migrations WHERE filename=?", (name,)).fetchone()
        if row:
            continue
        with open(path, "r", encoding="utf-8") as handle:
            sql = handle.read()
        con.executescript(sql)
        con.execute("INSERT INTO schema_migrations(filename) VALUES (?)", (name,))
        applied.append(name)
    con.commit()
    return applied


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]
