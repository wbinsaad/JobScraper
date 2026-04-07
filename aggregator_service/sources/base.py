from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class FetchPageResult:
    items: list[dict]
    total: int
    next_offset: int | None
    max_seen_ts: datetime | None


class SourceConnector(Protocol):
    source_name: str

    def fetch_page(
        self,
        *,
        since_ts: datetime | None,
        offset: int,
        run_id: int,
        task_id: str,
        con,
    ) -> FetchPageResult:
        ...

    def to_canonical(self, item: dict) -> dict | None:
        ...

    def source_job_id(self, item: dict) -> str | None:
        ...

    def source_updated_at(self, item: dict) -> datetime | None:
        ...
