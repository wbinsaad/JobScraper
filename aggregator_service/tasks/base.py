from typing import Protocol


class Task(Protocol):
    task_id: str

    def run(self, *, trigger_type: str, selected_sources: list[str] | None = None) -> dict:
        ...
