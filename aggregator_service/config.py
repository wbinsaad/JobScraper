import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    db_path: str
    migrate_dir: str
    jobspy_base_url: str
    seek_base_url: str
    request_timeout_seconds: int
    page_limit_jobspy: int
    page_limit_seek: int
    scheduler_enabled: bool
    scheduler_interval_seconds: int
    response_excerpt_max_bytes: int


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("AGG_APP_NAME", "Jobs Aggregator API"),
        app_version=os.getenv("AGG_APP_VERSION", "0.1.0"),
        db_path=os.getenv("AGG_DB_PATH", "/app/data/aggregator.db"),
        migrate_dir=os.getenv("AGG_MIG_DIR", "/app/aggregator_service/migrations"),
        jobspy_base_url=os.getenv("JOBSPY_API_BASE_URL", "http://jobspy_api:8000"),
        seek_base_url=os.getenv("SEEK_API_BASE_URL", "http://seek_api:8000"),
        request_timeout_seconds=int(os.getenv("AGG_REQUEST_TIMEOUT_SECONDS", "20")),
        page_limit_jobspy=int(os.getenv("AGG_JOBSPY_LIMIT", "100")),
        page_limit_seek=int(os.getenv("AGG_SEEK_LIMIT", "100")),
        scheduler_enabled=_to_bool(os.getenv("AGG_SCHEDULER_ENABLED"), True),
        scheduler_interval_seconds=int(os.getenv("AGG_SCHEDULER_INTERVAL_SECONDS", "20")),
        response_excerpt_max_bytes=int(os.getenv("AGG_RESPONSE_EXCERPT_MAX_BYTES", "4000")),
    )
