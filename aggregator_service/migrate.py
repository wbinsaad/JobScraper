from aggregator_service.config import get_settings
from aggregator_service.db import apply_migrations, connect


def main() -> None:
    settings = get_settings()
    con = connect(settings.db_path)
    applied = apply_migrations(con, settings.migrate_dir)
    con.close()
    if applied:
        print(f"[aggregator_migrate] applied: {', '.join(applied)}")
    else:
        print("[aggregator_migrate] no new migrations")


if __name__ == "__main__":
    main()
