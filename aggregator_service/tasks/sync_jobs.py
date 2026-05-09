import threading

from aggregator_service.services.sync_service import run_sync


class SyncJobsTask:
    task_id = "sync_jobs"

    def __init__(self, con_factory, connectors: dict, scoring_service=None):
        self._con_factory = con_factory
        self._connectors = connectors
        self._scoring_service = scoring_service
        self._lock = threading.Lock()

    def run(self, *, trigger_type: str, selected_sources: list[str] | None = None) -> dict:
        if not self._lock.acquire(blocking=False):
            return {"status": "running", "message": "sync is already in progress"}

        con = self._con_factory()
        try:
            return run_sync(
                con=con,
                connectors=self._connectors,
                task_id=self.task_id,
                trigger_type=trigger_type,
                selected_sources=selected_sources,
                scoring_service=self._scoring_service,
            )
        finally:
            con.close()
            self._lock.release()
