from fastapi import APIRouter, Request
from pydantic import BaseModel

from aggregator_service.api.state import get_sync_task

router = APIRouter()


class SyncRequest(BaseModel):
    sources: list[str] | None = None


@router.post("/sync")
def trigger_sync(payload: SyncRequest, request: Request):
    sync_task = get_sync_task(request)
    return sync_task.run(trigger_type="manual", selected_sources=payload.sources)
