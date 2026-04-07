from fastapi import APIRouter, Query, Request

from aggregator_service.api.state import get_con_factory
from aggregator_service.db import rows_to_dicts

router = APIRouter()


@router.get("/status")
def get_status(request: Request):
    con = get_con_factory(request)()
    try:
        latest = con.execute(
            """
            SELECT run_id, started_at, ended_at, overall_status, trigger_type, error_summary
            FROM source_sync_runs
            ORDER BY run_id DESC
            LIMIT 1
            """
        ).fetchone()
        checkpoints = rows_to_dicts(
            con.execute(
                "SELECT source_name, last_success_ts, updated_at FROM source_checkpoints ORDER BY source_name"
            ).fetchall()
        )
        return {"latest_run": dict(latest) if latest else None, "checkpoints": checkpoints}
    finally:
        con.close()


@router.get("/jobs")
def list_jobs(
    request: Request,
    source_name: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    con = get_con_factory(request)()
    try:
        params: list = []
        where = ""
        join = ""

        if source_name:
            join = "JOIN job_presence p ON p.canonical_job_id = c.id"
            where = "WHERE p.source_name = ?"
            params.append(source_name)

        total = con.execute(
            f"SELECT COUNT(*) AS total FROM jobs_canonical c {join} {where}",
            params,
        ).fetchone()["total"]

        rows = con.execute(
            f"""
            SELECT c.id, c.normalized_job_url, c.title, c.company, c.location, c.description,
                   c.job_type, c.pay_range_text, c.first_seen_at, c.last_seen_at, c.active_flag
            FROM jobs_canonical c
            {join}
            {where}
            ORDER BY c.last_seen_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return {"total": int(total), "limit": limit, "offset": offset, "items": rows_to_dicts(rows)}
    finally:
        con.close()
