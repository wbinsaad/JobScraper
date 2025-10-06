import os
import glob
import sqlite3
from pathlib import Path

DB = os.getenv("DB_PATH", "/app/data/jobs.db")
# Point to the correct directory inside the container:
MIG_DIR = os.getenv("MIG_DIR", "/app/infra/migrations")

def apply_file(conn: sqlite3.Connection, path: str) -> None:
    print(f"[migrate] applying: {path}")
    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()
    with conn:
        conn.executescript(sql)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(filename) VALUES (?)",
            (os.path.basename(path),),
        )

def main() -> None:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = sqlite3.connect(DB, timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   TEXT PRIMARY KEY,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Find .sql files
    pattern = str(Path(MIG_DIR) / "*.sql")
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"[migrate] no .sql files found in {MIG_DIR}. Check your path.")

    # Apply any new .sql once
    for path in files:
        fn = os.path.basename(path)
        already = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE filename=?",
            (fn,),
        ).fetchone()
        if already:
            print(f"[migrate] already applied: {fn}")
            continue
        apply_file(conn, path)

    print("[migrate] done.")

if __name__ == "__main__":
    main()
