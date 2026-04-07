from fastapi import APIRouter, HTTPException, Query, Request

from aggregator_service.api.state import get_con_factory
from aggregator_service.db import rows_to_dicts

router = APIRouter(prefix="/debug")


@router.get("/api-requests")
def list_api_requests(
    request: Request,
    source_name: str | None = Query(default=None),
    run_id: int | None = Query(default=None),
    success_flag: bool | None = Query(default=None),
    status_code: int | None = Query(default=None),
    from_ts: str | None = Query(default=None),
    to_ts: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    con = get_con_factory(request)()
    try:
        where_parts = []
        params = []

        if source_name:
            where_parts.append("r.source_name = ?")
            params.append(source_name)
        if run_id is not None:
            where_parts.append("r.run_id = ?")
            params.append(run_id)
        if success_flag is not None:
            where_parts.append("resp.success_flag = ?")
            params.append(1 if success_flag else 0)
        if status_code is not None:
            where_parts.append("resp.status_code = ?")
            params.append(status_code)
        if from_ts:
            where_parts.append("r.requested_at >= ?")
            params.append(from_ts)
        if to_ts:
            where_parts.append("r.requested_at <= ?")
            params.append(to_ts)

        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        total_row = con.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM api_request_log r
            LEFT JOIN api_response_log resp ON resp.request_id = r.request_id
            {where}
            """,
            params,
        ).fetchone()

        rows = con.execute(
            f"""
            SELECT
                r.request_id,
                r.run_id,
                r.task_id,
                r.source_name,
                r.method,
                r.url,
                r.query_json,
                r.requested_at,
                r.timeout_ms,
                r.retry_no,
                resp.responded_at,
                resp.duration_ms,
                resp.status_code,
                resp.success_flag,
                resp.error_type,
                resp.error_message
            FROM api_request_log r
            LEFT JOIN api_response_log resp ON resp.request_id = r.request_id
            {where}
            ORDER BY r.requested_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

        return {
            "total": int(total_row["total"] if total_row else 0),
            "limit": limit,
            "offset": offset,
            "items": rows_to_dicts(rows),
        }
    finally:
        con.close()


@router.get("/api-requests/{request_id}")
def get_api_request_detail(request_id: int, request: Request):
    con = get_con_factory(request)()
    try:
        row = con.execute(
            """
            SELECT
                r.request_id,
                r.run_id,
                r.task_id,
                r.source_name,
                r.method,
                r.url,
                r.query_json,
                r.headers_json_masked,
                r.request_body_json,
                r.requested_at,
                r.timeout_ms,
                r.retry_no,
                resp.responded_at,
                resp.duration_ms,
                resp.status_code,
                resp.response_headers_json,
                resp.response_body_excerpt,
                resp.body_sha256,
                resp.success_flag,
                resp.error_type,
                resp.error_message
            FROM api_request_log r
            LEFT JOIN api_response_log resp ON resp.request_id = r.request_id
            WHERE r.request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="request_id not found")
        return dict(row)
    finally:
        con.close()
