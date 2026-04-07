from datetime import datetime

from aggregator_service.sources.base import FetchPageResult
from aggregator_service.utils import normalize_job_url, parse_dt


class JobSpyConnector:
    source_name = "jobspy"

    def __init__(self, base_url: str, page_limit: int, http_client):
        self.base_url = base_url.rstrip("/")
        self.page_limit = min(max(page_limit, 1), 200)
        self.http = http_client

    def fetch_page(self, *, since_ts: datetime | None, offset: int, run_id: int, task_id: str, con) -> FetchPageResult:
        params = {
            "limit": self.page_limit,
            "offset": offset,
            "sort_by": "ingested_at",
            "sort_order": "asc",
        }
        if since_ts is not None:
            params["ingested_from"] = since_ts.isoformat()

        payload, _ = self.http.get_json(
            con=con,
            source_name=self.source_name,
            run_id=run_id,
            task_id=task_id,
            url=f"{self.base_url}/api/v1/jobs",
            params=params,
        )
        items = payload.get("items", [])
        max_seen = None
        for item in items:
            dt = parse_dt(item.get("ingested_at"))
            if dt and (max_seen is None or dt > max_seen):
                max_seen = dt

        next_offset = None
        total = int(payload.get("total", 0))
        if offset + len(items) < total:
            next_offset = offset + len(items)

        return FetchPageResult(items=items, total=total, next_offset=next_offset, max_seen_ts=max_seen)

    def to_canonical(self, item: dict) -> dict | None:
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
            "pay_range_text": None,
        }

    def source_job_id(self, item: dict) -> str | None:
        value = item.get("id")
        return str(value) if value is not None else None

    def source_updated_at(self, item: dict) -> datetime | None:
        return parse_dt(item.get("ingested_at"))
