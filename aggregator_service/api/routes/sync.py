from fastapi import APIRouter, Request
from pydantic import BaseModel

from aggregator_service.api.state import get_sync_task

router = APIRouter()


class SyncRequest(BaseModel):
    sources: list[str] | None = None


@router.post("/sync")
def trigger_sync(request: Request, payload: SyncRequest | None = None):
    sync_task = get_sync_task(request)
    sources = payload.sources if payload is not None else None
    return sync_task.run(trigger_type="manual", selected_sources=sources)
