from contextlib import asynccontextmanager

from fastapi import FastAPI

from aggregator_service.api.routes import build_router
from aggregator_service.config import get_settings
from aggregator_service.db import apply_migrations, connect
from aggregator_service.ai_client import GroqChatClient, RateLimiter
from aggregator_service.sources.http_client import LoggedHttpClient
from aggregator_service.sources.jobspy import JobSpyConnector
from aggregator_service.sources.seek import SeekConnector
from aggregator_service.tasks.scheduler import IntervalScheduler
from aggregator_service.tasks.sync_jobs import SyncJobsTask
from aggregator_service.services.scoring_service import RelevanceScoringService


settings = get_settings()


def _con_factory():
    return connect(settings.db_path)


def _build_sync_task() -> SyncJobsTask:
    http_client = LoggedHttpClient(
        timeout_seconds=settings.request_timeout_seconds,
        response_excerpt_max_bytes=settings.response_excerpt_max_bytes,
    )
    connectors = {
        "jobspy": JobSpyConnector(
            base_url=settings.jobspy_base_url,
            page_limit=settings.page_limit_jobspy,
            http_client=http_client,
        ),
        "seek": SeekConnector(
            base_url=settings.seek_base_url,
            page_limit=settings.page_limit_seek,
            http_client=http_client,
        ),
    }
    rate_limiter = RateLimiter(
        rpm=settings.ai_rpm,
        rpd=settings.ai_rpd,
        tpm=settings.ai_tpm,
        tpd=settings.ai_tpd,
        safety=settings.ai_safety_factor,
    )
    ai_client = GroqChatClient(
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        rate_limiter=rate_limiter,
        timeout_seconds=settings.ai_timeout_seconds,
        max_response_tokens=settings.ai_max_response_tokens,
    )
    scoring_service = RelevanceScoringService(
        con_factory=_con_factory,
        client=ai_client,
        system_prompt=settings.ai_system_prompt,
        max_request_tokens=settings.ai_max_request_tokens,
        max_response_tokens=settings.ai_max_response_tokens,
    )

    return SyncJobsTask(con_factory=_con_factory, connectors=connectors, scoring_service=scoring_service)


@asynccontextmanager
async def lifespan(app: FastAPI):
    con = _con_factory()
    apply_migrations(con, settings.migrate_dir)
    con.close()

    sync_task = _build_sync_task()
    app.state.con_factory = _con_factory
    app.state.sync_task = sync_task

    scheduler = None
    if settings.scheduler_enabled:
        scheduler = IntervalScheduler(settings.scheduler_interval_seconds, sync_task)
        scheduler.start()
    app.state.scheduler = scheduler

    yield

    if app.state.scheduler is not None:
        app.state.scheduler.stop()


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.include_router(build_router())
