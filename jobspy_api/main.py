import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel


def _resolve_db_path() -> str:
	env_path = os.getenv("SQLITE_PATH", "/app/data/jobs.db")
	candidate = Path(env_path)

	if candidate.exists():
		return str(candidate)

	project_root = Path(__file__).resolve().parents[1]
	local_default = project_root / "data" / "jobs.db"
	if local_default.exists():
		return str(local_default)

	return str(candidate)


def _connect() -> sqlite3.Connection:
	con = sqlite3.connect(_resolve_db_path(), timeout=5)
	con.row_factory = sqlite3.Row
	con.execute("PRAGMA busy_timeout=5000;")
	return con


class JobOut(BaseModel):
	id: int
	source: str
	title: str | None
	company: str | None
	description: str | None
	location: str | None
	job_type: str | None
	job_url: str | None
	status: str
	ingested_at: str


class JobsResponse(BaseModel):
	total: int
	limit: int
	offset: int
	items: list[JobOut]


app = FastAPI(title="JobSpy API", version="0.1.0")


@app.get("/health")
def health() -> dict:
	try:
		return {"status": "ok"}
	except Exception as exc:
		raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.get("/api/v1/jobs", response_model=JobsResponse)
def list_jobs(
	ingested_from: datetime | None = Query(
		default=None,
		description="Return jobs with ingested_at >= this datetime (ISO 8601)",
	),
	ingested_to: datetime | None = Query(
		default=None,
		description="Return jobs with ingested_at <= this datetime (ISO 8601)",
	),
	keyword: str | None = Query(
		default=None,
		description="Case-insensitive match on title/company/description",
	),
	location: str | None = Query(
		default=None,
		description="Case-insensitive match on location",
	),
	limit: int = Query(default=50, ge=1, le=200),
	offset: int = Query(default=0, ge=0),
	sort_by: Literal["ingested_at", "title", "company"] = "ingested_at",
	sort_order: Literal["asc", "desc"] = "desc",
):
	where_parts: list[str] = []
	params: list[object] = []

	if ingested_from is not None:
		where_parts.append("datetime(ingested_at) >= datetime(?)")
		params.append(ingested_from.isoformat(sep=" "))

	if ingested_to is not None:
		where_parts.append("datetime(ingested_at) <= datetime(?)")
		params.append(ingested_to.isoformat(sep=" "))

	if keyword:
		like_term = f"%{keyword.strip()}%"
		where_parts.append("(title LIKE ? COLLATE NOCASE OR company LIKE ? COLLATE NOCASE OR description LIKE ? COLLATE NOCASE)")
		params.extend([like_term, like_term, like_term])

	if location:
		where_parts.append("location LIKE ? COLLATE NOCASE")
		params.append(f"%{location.strip()}%")

	where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
	order_sql = f"ORDER BY {sort_by} {sort_order.upper()}"

	count_sql = f"SELECT COUNT(*) AS total FROM raw_jobs {where_sql}"
	data_sql = f"""
		SELECT
			id,
			source,
			title,
			company,
			description,
			location,
			job_type,
			job_url,
			status,
			ingested_at
		FROM raw_jobs
		{where_sql}
		{order_sql}
		LIMIT ? OFFSET ?
	"""

	try:
		con = _connect()
		total_row = con.execute(count_sql, params).fetchone()
		rows = con.execute(data_sql, [*params, limit, offset]).fetchall()
		con.close()
	except sqlite3.Error as exc:
		raise HTTPException(status_code=500, detail=f"Query failed: {exc}")

	return {
		"total": int(total_row["total"] if total_row else 0),
		"limit": limit,
		"offset": offset,
		"items": [dict(row) for row in rows],
	}
