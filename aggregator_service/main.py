from contextlib import asynccontextmanager

from fastapi import FastAPI

from aggregator_service.api.routes import build_router
from aggregator_service.config import get_settings
from aggregator_service.db import apply_migrations, connect
from aggregator_service.sources.http_client import LoggedHttpClient
from aggregator_service.sources.jobspy import JobSpyConnector
from aggregator_service.sources.seek import SeekConnector
from aggregator_service.tasks.scheduler import IntervalScheduler
from aggregator_service.tasks.sync_jobs import SyncJobsTask


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
    return SyncJobsTask(con_factory=_con_factory, connectors=connectors)


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
