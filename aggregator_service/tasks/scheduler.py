import threading
import time


class IntervalScheduler:
    def __init__(self, interval_seconds: int, task):
        self.interval_seconds = interval_seconds
        self.task = task
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="aggregator-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.task.run(trigger_type="scheduled", selected_sources=None)
            except Exception:
                pass
            self._stop_event.wait(self.interval_seconds)
