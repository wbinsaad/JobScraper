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
    ai_base_url: str
    ai_model: str
    ai_api_key: str | None
    ai_timeout_seconds: int
    ai_rpm: int
    ai_rpd: int
    ai_tpm: int
    ai_tpd: int
    ai_max_request_tokens: int
    ai_max_response_tokens: int
    ai_safety_factor: float
    ai_system_prompt: str


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
        scheduler_interval_seconds=int(os.getenv("AGG_SCHEDULER_INTERVAL_SECONDS", "900")),
        response_excerpt_max_bytes=int(os.getenv("AGG_RESPONSE_EXCERPT_MAX_BYTES", "4000")),
        ai_base_url=os.getenv("AGG_AI_BASE_URL", "https://api.groq.com/openai/v1"),
        ai_model=os.getenv("AGG_AI_MODEL", "llama-3.3-70b-versatile"),
        ai_api_key=os.getenv("AGG_AI_API_KEY") or os.getenv("GROQ_API_KEY"),
        ai_timeout_seconds=int(os.getenv("AGG_AI_TIMEOUT_SECONDS", "45")),
        ai_rpm=int(os.getenv("AGG_AI_RPM", "30")),
        ai_rpd=int(os.getenv("AGG_AI_RPD", "1000")),
        ai_tpm=int(os.getenv("AGG_AI_TPM", "12000")),
        ai_tpd=int(os.getenv("AGG_AI_TPD", "100000")),
        ai_max_request_tokens=int(os.getenv("AGG_AI_MAX_REQUEST_TOKENS", "6000")),
        ai_max_response_tokens=int(os.getenv("AGG_AI_MAX_RESPONSE_TOKENS", "256")),
        ai_safety_factor=float(os.getenv("AGG_AI_SAFETY_FACTOR", "0.9")),
        ai_system_prompt=os.getenv(
            "AGG_AI_SYSTEM_PROMPT",
            "You are a strict job-title relevance scorer. Use only the CV and job titles to score relevance. "
            "Return only a JSON array of objects: {\"job_id\": <id>, \"score\": <0-9>}. "
            "Score 0 means not relevant; 9 means perfect match. Use job_ids only for mapping.",
        ),
    )
