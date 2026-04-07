from fastapi import APIRouter

from aggregator_service.api.routes.debug_requests import router as debug_requests_router
from aggregator_service.api.routes.health import router as health_router
from aggregator_service.api.routes.jobs import router as jobs_router
from aggregator_service.api.routes.sync import router as sync_router


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    router.include_router(health_router)
    router.include_router(sync_router)
    router.include_router(jobs_router)
    router.include_router(debug_requests_router)
    return router
