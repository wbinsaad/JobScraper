from datetime import datetime, timezone

from aggregator_service.services.sync_service import run_sync
from aggregator_service.sources.base import FetchPageResult
from aggregator_service.utils import normalize_job_url, parse_dt


class FakeConnector:
    source_name = "fake"

    def __init__(self, pages):
        self._pages = pages

    def fetch_page(self, *, since_ts, offset, run_id, task_id, con):
        page = self._pages[offset]
        if isinstance(page, Exception):
            raise page
        return page

    def to_canonical(self, item):
        normalized_url = normalize_job_url(item.get("job_url"))
        if not normalized_url:
            return None
        return {
            "normalized_job_url": normalized_url,
            "title": item.get("title"),
            "company": item.get("company"),
            "location": item.get("location"),
            "description": item.get("description"),
            "job_type": item.get("job_type"),
            "pay_range_text": item.get("pay_range_text"),
        }

    def source_job_id(self, item):
        return str(item["id"])

    def source_updated_at(self, item):
        return parse_dt(item.get("updated_at"))


def test_sync_deduplicates_tracking_variants_and_preserves_insert_change(aggregator_db):
    seen_at = datetime(2026, 7, 10, 1, 0, tzinfo=timezone.utc)
    connector = FakeConnector(
        {
            0: FetchPageResult(
                items=[
                    {
                        "id": 1,
                        "job_url": "https://Jobs.Example.com/roles/42/?utm_source=linkedin#apply",
                        "title": "Software Engineer",
                        "company": "Example Pty Ltd",
                        "updated_at": seen_at.isoformat(),
                    },
                    {
                        "id": 2,
                        "job_url": "https://jobs.example.com/roles/42?fbclid=tracking",
                        "title": "Senior Software Engineer",
                        "company": "Example Pty Ltd",
                        "updated_at": seen_at.isoformat(),
                    },
                ],
                total=2,
                next_offset=None,
                max_seen_ts=seen_at,
            )
        }
    )

    result = run_sync(
        con=aggregator_db,
        connectors={"fake": connector},
        task_id="test_sync",
        trigger_type="manual",
    )

    canonical_rows = aggregator_db.execute(
        "SELECT id, normalized_job_url, title FROM jobs_canonical"
    ).fetchall()
    snapshots = aggregator_db.execute(
        "SELECT source_updated_at FROM jobs_source_snapshot ORDER BY id"
    ).fetchall()
    change = aggregator_db.execute(
        "SELECT change_type FROM job_run_changes WHERE run_id = ?",
        (result["run_id"],),
    ).fetchone()

    assert result["status"] == "success"
    assert result["sources"]["fake"]["inserted_count"] == 1
    assert result["sources"]["fake"]["updated_count"] == 1
    assert len(canonical_rows) == 1
    assert canonical_rows[0]["normalized_job_url"] == "https://jobs.example.com/roles/42"
    assert canonical_rows[0]["title"] == "Senior Software Engineer"
    assert [row["source_updated_at"] for row in snapshots] == [
        seen_at.isoformat(),
        seen_at.isoformat(),
    ]
    assert change["change_type"] == "insert"


def test_failed_later_page_does_not_advance_last_success_checkpoint(aggregator_db):
    original_checkpoint = "2026-07-09T00:00:00+00:00"
    newer_seen_at = datetime(2026, 7, 10, 1, 0, tzinfo=timezone.utc)
    aggregator_db.execute(
        """
        INSERT INTO source_checkpoints(source_name, last_success_ts, updated_at)
        VALUES (?, ?, ?)
        """,
        ("fake", original_checkpoint, original_checkpoint),
    )
    aggregator_db.commit()

    connector = FakeConnector(
        {
            0: FetchPageResult(
                items=[
                    {
                        "id": 1,
                        "job_url": "https://jobs.example.com/roles/99",
                        "title": "Backend Engineer",
                        "updated_at": newer_seen_at.isoformat(),
                    }
                ],
                total=2,
                next_offset=1,
                max_seen_ts=newer_seen_at,
            ),
            1: RuntimeError("upstream unavailable"),
        }
    )

    result = run_sync(
        con=aggregator_db,
        connectors={"fake": connector},
        task_id="test_sync",
        trigger_type="manual",
    )

    checkpoint = aggregator_db.execute(
        "SELECT last_success_ts FROM source_checkpoints WHERE source_name = ?",
        ("fake",),
    ).fetchone()["last_success_ts"]
    detail = aggregator_db.execute(
        """
        SELECT source_status, checkpoint_before, checkpoint_after, error_text
        FROM source_run_details
        WHERE run_id = ? AND source_name = ?
        """,
        (result["run_id"], "fake"),
    ).fetchone()

    assert result["status"] == "failed"
    assert checkpoint == original_checkpoint
    assert detail["source_status"] == "failed"
    assert detail["checkpoint_before"] == original_checkpoint
    assert detail["checkpoint_after"] == original_checkpoint
    assert "upstream unavailable" in detail["error_text"]
