from pathlib import Path

import pytest

from aggregator_service.db import apply_migrations, connect


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "aggregator_service" / "migrations"


@pytest.fixture
def aggregator_db(tmp_path):
    """Return a migrated, per-test SQLite database connection."""
    con = connect(str(tmp_path / "aggregator.db"))
    apply_migrations(con, str(MIGRATIONS_DIR))
    try:
        yield con
    finally:
        con.close()


@pytest.fixture(autouse=True)
def block_live_http(monkeypatch):
    """Fail fast if an aggregator test accidentally reaches the network."""

    def _blocked_request(*args, **kwargs):
        raise AssertionError("Live HTTP is disabled in the test suite")

    monkeypatch.setattr("requests.sessions.Session.request", _blocked_request)
