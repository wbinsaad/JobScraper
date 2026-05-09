from datetime import datetime, timezone

from aggregator_service.utils import parse_dt, to_json_text


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_sync(
    *,
    con,
    connectors: dict,
    task_id: str,
    trigger_type: str,
    selected_sources: list[str] | None = None,
    scoring_service=None,
) -> dict:
    run_row = con.execute(
        """
        INSERT INTO source_sync_runs(started_at, overall_status, trigger_type)
        VALUES (?, 'running', ?)
        RETURNING run_id
        """,
        (now_utc_iso(), trigger_type),
    ).fetchone()
    run_id = int(run_row["run_id"])
    con.commit()

    source_names = selected_sources or list(connectors.keys())
    statuses: list[str] = []
    summary: dict[str, dict] = {}

    for source_name in source_names:
        connector = connectors[source_name]
        detail = _sync_single_source(con=con, connector=connector, run_id=run_id, task_id=task_id)
        statuses.append(detail["source_status"])
        summary[source_name] = detail

    if statuses and all(status == "success" for status in statuses):
        overall = "success"
    elif any(status == "success" for status in statuses):
        overall = "partial_success"
    else:
        overall = "failed"

    con.execute(
        """
        UPDATE source_sync_runs
        SET ended_at=?, overall_status=?, error_summary=?
        WHERE run_id=?
        """,
        (now_utc_iso(), overall, None if overall != "failed" else "All sources failed", run_id),
    )
    con.commit()
    result: dict = {"run_id": run_id, "status": overall, "sources": summary}

    if scoring_service is not None:
        try:
            result["scoring"] = scoring_service.score_run(run_id=run_id)
        except Exception as exc:
            result["scoring"] = {"status": "error", "error": str(exc)}

    return result


def _sync_single_source(*, con, connector, run_id: int, task_id: str) -> dict:
    source_name = connector.source_name
    cp_row = con.execute(
        "SELECT last_success_ts FROM source_checkpoints WHERE source_name=?",
        (source_name,),
    ).fetchone()
    checkpoint_before = cp_row["last_success_ts"] if cp_row else None
    since_ts = parse_dt(checkpoint_before)

    detail_row = con.execute(
        """
        INSERT INTO source_run_details(
            run_id, source_name, source_status, fetched_count, inserted_count, updated_count,
            checkpoint_before, checkpoint_after, source_max_seen_ts
        ) VALUES (?, ?, 'running', 0, 0, 0, ?, ?, ?)
        RETURNING id
        """,
        (run_id, source_name, checkpoint_before, checkpoint_before, checkpoint_before),
    ).fetchone()
    detail_id = int(detail_row["id"])
    con.commit()

    fetched_count = 0
    inserted_count = 0
    updated_count = 0
    source_max_seen_ts = since_ts
    offset = 0

    try:
        while True:
            page = connector.fetch_page(
                since_ts=since_ts,
                offset=offset,
                run_id=run_id,
                task_id=task_id,
                con=con,
            )
            items = page.items
            fetched_count += len(items)
            if page.max_seen_ts and (source_max_seen_ts is None or page.max_seen_ts > source_max_seen_ts):
                source_max_seen_ts = page.max_seen_ts

            for item in items:
                canonical = connector.to_canonical(item)
                if not canonical:
                    continue
                upserted_id, was_insert = _upsert_canonical(con=con, canonical=canonical, run_id=run_id)
                if was_insert:
                    inserted_count += 1
                else:
                    updated_count += 1

                con.execute(
                    """
                    INSERT INTO jobs_source_snapshot(
                        canonical_job_id, source_name, source_job_id, source_payload_json,
                        source_posted_at, source_updated_at, observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        upserted_id,
                        source_name,
                        connector.source_job_id(item),
                        to_json_text(item),
                        item.get("posted_date"),
                        (connector.source_updated_at(item) or None),
                        now_utc_iso(),
                    ),
                )
                con.execute(
                    """
                    INSERT INTO job_presence(canonical_job_id, source_name, first_seen_at, last_seen_at, last_status)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_job_id, source_name)
                    DO UPDATE SET last_seen_at=excluded.last_seen_at, last_status=excluded.last_status
                    """,
                    (upserted_id, source_name, now_utc_iso(), now_utc_iso(), "seen"),
                )

            if source_max_seen_ts:
                con.execute(
                    """
                    INSERT INTO source_checkpoints(source_name, last_success_ts, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(source_name)
                    DO UPDATE SET last_success_ts=excluded.last_success_ts, updated_at=excluded.updated_at
                    """,
                    (source_name, source_max_seen_ts.isoformat(), now_utc_iso()),
                )
            con.commit()

            if page.next_offset is None:
                break
            offset = page.next_offset

        con.execute(
            """
            UPDATE source_run_details
            SET source_status='success', fetched_count=?, inserted_count=?, updated_count=?,
                checkpoint_after=?, source_max_seen_ts=?, error_text=NULL
            WHERE id=?
            """,
            (
                fetched_count,
                inserted_count,
                updated_count,
                source_max_seen_ts.isoformat() if source_max_seen_ts else checkpoint_before,
                source_max_seen_ts.isoformat() if source_max_seen_ts else checkpoint_before,
                detail_id,
            ),
        )
        con.commit()
        return {
            "source_status": "success",
            "fetched_count": fetched_count,
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "checkpoint_after": source_max_seen_ts.isoformat() if source_max_seen_ts else checkpoint_before,
        }
    except Exception as exc:
        con.execute(
            """
            UPDATE source_run_details
            SET source_status='failed', fetched_count=?, inserted_count=?, updated_count=?,
                checkpoint_after=?, source_max_seen_ts=?, error_text=?
            WHERE id=?
            """,
            (
                fetched_count,
                inserted_count,
                updated_count,
                checkpoint_before,
                source_max_seen_ts.isoformat() if source_max_seen_ts else checkpoint_before,
                str(exc)[:500],
                detail_id,
            ),
        )
        con.commit()
        return {
            "source_status": "failed",
            "fetched_count": fetched_count,
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "checkpoint_after": checkpoint_before,
            "error": str(exc),
        }


def _upsert_canonical(*, con, canonical: dict, run_id: int) -> tuple[int, bool]:
    row = con.execute(
        "SELECT id FROM jobs_canonical WHERE normalized_job_url=?",
        (canonical["normalized_job_url"],),
    ).fetchone()
    if row:
        con.execute(
            """
            UPDATE jobs_canonical
            SET title=?, company=?, location=?, description=?, job_type=?, pay_range_text=?,
                last_seen_at=?, active_flag=1
            WHERE id=?
            """,
            (
                canonical.get("title"),
                canonical.get("company"),
                canonical.get("location"),
                canonical.get("description"),
                canonical.get("job_type"),
                canonical.get("pay_range_text"),
                now_utc_iso(),
                int(row["id"]),
            ),
        )
        _record_job_change(con=con, run_id=run_id, canonical_job_id=int(row["id"]), change_type="update")
        return int(row["id"]), False

    new_row = con.execute(
        """
        INSERT INTO jobs_canonical(
            normalized_job_url, title, company, location, description, job_type,
            pay_range_text, first_seen_at, last_seen_at, active_flag
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        RETURNING id
        """,
        (
            canonical.get("normalized_job_url"),
            canonical.get("title"),
            canonical.get("company"),
            canonical.get("location"),
            canonical.get("description"),
            canonical.get("job_type"),
            canonical.get("pay_range_text"),
            now_utc_iso(),
            now_utc_iso(),
        ),
    ).fetchone()
    _record_job_change(con=con, run_id=run_id, canonical_job_id=int(new_row["id"]), change_type="insert")
    return int(new_row["id"]), True


def _record_job_change(*, con, run_id: int, canonical_job_id: int, change_type: str) -> None:
    con.execute(
        """
        INSERT INTO job_run_changes(run_id, canonical_job_id, change_type, changed_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(run_id, canonical_job_id)
        DO UPDATE SET
            change_type = CASE
                WHEN job_run_changes.change_type = 'insert' THEN 'insert'
                ELSE excluded.change_type
            END,
            changed_at = excluded.changed_at
        """,
        (run_id, canonical_job_id, change_type, now_utc_iso()),
    )
