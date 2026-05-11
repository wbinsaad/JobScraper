from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from aggregator_service.api.state import get_con_factory
from aggregator_service.db import rows_to_dicts

router = APIRouter()


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1)
    cv_markdown: str = Field(...)


class ProfileUpdate(BaseModel):
    name: str | None = None
    cv_markdown: str | None = None


@router.get("/profiles")
def list_profiles(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    con = get_con_factory(request)()
    try:
        total_row = con.execute("SELECT COUNT(*) AS total FROM profiles").fetchone()
        rows = con.execute(
            """
            SELECT id, name, cv_markdown, created_at, updated_at
            FROM profiles
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return {
            "total": int(total_row["total"] if total_row else 0),
            "limit": limit,
            "offset": offset,
            "items": rows_to_dicts(rows),
        }
    finally:
        con.close()


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: int, request: Request):
    con = get_con_factory(request)()
    try:
        row = con.execute(
            """
            SELECT id, name, cv_markdown, created_at, updated_at
            FROM profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="profile not found")
        return dict(row)
    finally:
        con.close()


@router.get("/profiles/{profile_id}/jobs")
def list_profile_jobs(
    profile_id: int,
    request: Request,
    first_seen: str | None = Query(default=None),
    min_score: int | None = Query(default=None, ge=0, le=9),
    max_score: int | None = Query(default=None, ge=0, le=9),
    job_title: str | None = Query(default=None),
    company_name: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(status_code=400, detail="min_score cannot be greater than max_score")

    con = get_con_factory(request)()
    try:
        profile_row = con.execute("SELECT 1 FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not profile_row:
            raise HTTPException(status_code=404, detail="profile not found")

        params: list = [profile_id, profile_id]
        where_parts: list[str] = []

        if min_score is not None:
            where_parts.append("s.score >= ?")
            params.append(min_score)
        if max_score is not None:
            where_parts.append("s.score <= ?")
            params.append(max_score)
        if first_seen:
            where_parts.append("(c.first_seen_at >= ? OR c.first_seen_at IS NULL)")
            params.append(first_seen)
        if job_title:
            where_parts.append("c.title IS NOT NULL AND lower(c.title) LIKE ?")
            params.append(f"%{job_title.lower()}%")
        if company_name:
            where_parts.append("lower(COALESCE(c.company, '')) LIKE ?")
            params.append(f"%{company_name.lower()}%")

        where_clause = " AND " + " AND ".join(where_parts) if where_parts else ""

        base_from = f"""
        FROM profile_job_scores s
        JOIN jobs_canonical c ON c.id = s.canonical_job_id
        WHERE s.profile_id = ?
          AND s.id IN (
              SELECT MAX(id)
              FROM profile_job_scores
              WHERE profile_id = ?
              GROUP BY canonical_job_id
          )
          {where_clause}
        """

        total_row = con.execute(f"SELECT COUNT(*) AS total {base_from}", params).fetchone()

        rows = con.execute(
            f"""
            SELECT
                c.id AS canonical_job_id,
                c.normalized_job_url,
                c.title,
                c.company,
                c.location,
                c.first_seen_at,
                s.score AS relevance_score,
                s.request_id
            {base_from}
            ORDER BY s.score DESC, s.scored_at DESC
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


@router.post("/profiles")
def create_profile(payload: ProfileCreate, request: Request):
    con = get_con_factory(request)()
    try:
        now = _now_utc_iso()
        row = con.execute(
            """
            INSERT INTO profiles(name, cv_markdown, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            RETURNING id, name, cv_markdown, created_at, updated_at
            """,
            (payload.name, payload.cv_markdown, now, now),
        ).fetchone()
        con.commit()
        return dict(row)
    finally:
        con.close()


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: int, payload: ProfileUpdate, request: Request):
    if payload.name is None and payload.cv_markdown is None:
        raise HTTPException(status_code=400, detail="no fields provided")

    con = get_con_factory(request)()
    try:
        existing = con.execute("SELECT 1 FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="profile not found")

        now = _now_utc_iso()
        con.execute(
            """
            UPDATE profiles
            SET name = COALESCE(?, name),
                cv_markdown = COALESCE(?, cv_markdown),
                updated_at = ?
            WHERE id = ?
            """,
            (payload.name, payload.cv_markdown, now, profile_id),
        )
        con.commit()

        row = con.execute(
            """
            SELECT id, name, cv_markdown, created_at, updated_at
            FROM profiles
            WHERE id = ?
            """,
            (profile_id,),
        ).fetchone()
        return dict(row)
    finally:
        con.close()


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: int, request: Request):
    con = get_con_factory(request)()
    try:
        row = con.execute("SELECT 1 FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="profile not found")
        con.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        con.commit()
        return {"deleted": True, "profile_id": profile_id}
    finally:
        con.close()
