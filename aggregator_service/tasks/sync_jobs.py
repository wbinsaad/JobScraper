from aggregator_service.services.sync_service import run_sync


class SyncJobsTask:
    task_id = "sync_jobs"

    def __init__(self, con_factory, connectors: dict):
        self._con_factory = con_factory
        self._connectors = connectors

    def run(self, *, trigger_type: str, selected_sources: list[str] | None = None) -> dict:
        con = self._con_factory()
        try:
            return run_sync(
                con=con,
                connectors=self._connectors,
                task_id=self.task_id,
                trigger_type=trigger_type,
                selected_sources=selected_sources,
            )
        finally:
            con.close()
