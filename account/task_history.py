"""
Task history data models for Account system.

Pure data layer - no platform dependencies.
Ported from BlenderAIStudio src/studio/account/task_history.py
"""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TaskStatus(Enum):
    NONE = "NONE"
    SUCCESS = "SUCCESS"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"

    def is_success(self) -> bool:
        return self == self.SUCCESS

    def is_running(self) -> bool:
        return self == self.RUNNING

    def is_failed(self) -> bool:
        return self == self.FAILED

    def is_unknown(self) -> bool:
        return self == self.UNKNOWN

    def is_error(self) -> bool:
        return self == self.ERROR


@dataclass
class TaskStatusData:
    """Task status data (parsed from API response).

    Temporary DTO for passing data between network and business layers.
    """

    task_id: str
    state: TaskStatus = TaskStatus.NONE
    urls: Optional[list] = None  # Result download URLs
    progress: float = 0.0
    error_message: str = ""


@dataclass
class TaskHistoryData:
    """Task history data (persistence model)."""

    state: TaskStatus = TaskStatus.NONE
    outputs: list = field(default_factory=list)  # [(mime_type, file_path), ...]
    progress: float = 0.0
    error_message: str = ""
    finished_at: float = 0.0
    task_id: str = ""
    result: list = field(default_factory=list)  # Raw result data (optional)


class AccountTaskHistory:
    """Account task history manager.

    Responsibilities:
    - Store task history records
    - Provide query interface
    - No business logic (pure data layer)
    """

    def __init__(self):
        self.task_history_map: dict = {}

    def ensure_task_history(self, task_id: str) -> TaskHistoryData:
        if task_id not in self.task_history_map:
            self.task_history_map[task_id] = TaskHistoryData(
                state=TaskStatus.NONE,
                outputs=[],
                progress=0.0,
                error_message="",
                finished_at=0.0,
                task_id=task_id,
            )
        return self.task_history_map[task_id]

    def fetch_task_history(self, task_ids: list) -> dict:
        result = {}
        for task_id in task_ids:
            if task_id in self.task_history_map:
                result[task_id] = deepcopy(self.task_history_map[task_id])
        return result

    def get_task(self, task_id: str) -> Optional[TaskHistoryData]:
        return self.task_history_map.get(task_id)

    def find_needs_sync_tasks(self) -> list:
        return [
            t
            for t in self.task_history_map.values()
            if t.state in (TaskStatus.UNKNOWN, TaskStatus.RUNNING)
        ]
