import sqlite3, os, glob, pathlib

DB = os.getenv("DB_PATH", "/app/data/jobs.db")
MIG_DIR = "/app/migrations"

def has_column(conn, table, col):
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})"))

def apply_file(conn, path):
    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()
    with conn:
        conn.executescript(sql)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(filename) VALUES (?)",
            (os.path.basename(path),)
        )

def main():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = sqlite3.connect(DB, timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)")

    # Apply any new *.sql files once
    for path in sorted(glob.glob(os.path.join(MIG_DIR, "*.sql"))):
        fn = os.path.basename(path)
        if not conn.execute("SELECT 1 FROM schema_migrations WHERE filename=?", (fn,)).fetchone():
            apply_file(conn, path)

    # Safety: ensure stage2 columns exist even if DB predates 0001
    alters = [
        ("job_decisions","stage1_json","TEXT"),
        ("job_decisions","stage1_at","DATETIME"),
        ("job_decisions","stage2_json","TEXT"),
        ("job_decisions","stage2_status","TEXT NOT NULL DEFAULT 'pending'"),
        ("job_decisions","stage2_attempts","INTEGER NOT NULL DEFAULT 0"),
        ("job_decisions","stage2_last_error","TEXT"),
        ("job_decisions","reasons","TEXT"),
        ("job_decisions","label","TEXT"),
        ("job_decisions","score","INTEGER"),
        ("job_decisions","decided_at","DATETIME"),
        ("job_decisions","notified_at","DATETIME"),
    ]
    for tbl,col,typ in alters:
        if not has_column(conn, tbl, col):
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")

if __name__ == "__main__":
    main()
