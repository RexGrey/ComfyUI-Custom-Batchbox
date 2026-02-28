"""
Task sync service for Account system.

Handles async task status polling, result downloading, and history updates.
Ported from BlenderAIStudio src/studio/account/task_sync.py
"""

import mimetypes
import time
import logging
import tempfile
from pathlib import Path
from datetime import datetime
from queue import Queue
from threading import Thread, Lock
from typing import Callable, Optional, TYPE_CHECKING

from .task_history import (
    TaskStatus,
    TaskStatusData,
    TaskHistoryData,
    AccountTaskHistory,
)
from .network import get_session

if TYPE_CHECKING:
    from .core import Account

logger = logging.getLogger("batchbox.account")


def save_mime_typed_datas_to_temp_files(mime_typed_datas: list) -> list:
    """Save MIME-typed data to temporary files.

    Args:
        mime_typed_datas: List of (mime_type, data) tuples

    Returns:
        List of (mime_type, file_path) tuples
    """
    temp_folder = Path(tempfile.gettempdir(), "batchbox_account")
    temp_folder.mkdir(parents=True, exist_ok=True)

    timestamp = time.time()
    time_str = datetime.fromtimestamp(timestamp).strftime("%Y%m%d%H%M%S")
    saved_files = []

    for idx, (mime_type, data) in enumerate(mime_typed_datas):
        ext = mimetypes.guess_extension(mime_type) or ""
        if len(mime_typed_datas) > 1:
            save_file = Path(temp_folder, f"Gen_{time_str}_{idx}{ext}")
        else:
            save_file = Path(temp_folder, f"Gen_{time_str}{ext}")

        if isinstance(data, bytes):
            save_file.write_bytes(data)
        elif isinstance(data, str):
            save_file.write_text(data, encoding="utf-8")

        logger.info(f"Result saved to: {save_file.as_posix()}")
        saved_files.append((mime_type, save_file.as_posix()))

    return saved_files


class StatusResponseParser:
    """Status query response parser.

    Handles backend status API format:
    {
        "responseId": "...",
        "code": 1000,
        "data": {
            "taskId": {
                "state": "completed",
                "urls": ["https://...", ...]
            }
        }
    }
    """

    def parse_batch_response(self, response_json: dict) -> dict:
        result = {}
        data = response_json.get("data", {})
        for task_id, task_info in data.items():
            state = TaskStatus(task_info.get("state", TaskStatus.UNKNOWN.value))
            urls = task_info.get("urls") or []
            progress = 1.0 if state == TaskStatus.SUCCESS else 0.0
            error_message = task_info.get("msg")

            result[task_id] = TaskStatusData(
                task_id=task_id,
                state=state,
                urls=urls,
                progress=progress,
                error_message=error_message,
            )

        return result

    def download_result(self, urls: list) -> list:
        results = []
        for url in urls:
            logger.info(f"Downloading result from: {url}")
            session = get_session()
            response = session.get(url)
            response.raise_for_status()
            results.append((url, response.content))
        return results

    def convert_to_unified_format(self, parsed_data: list) -> list:
        results = []
        for url, data in parsed_data:
            mime_type = self._detect_mime_type(url, data)
            results.append((mime_type, data))
        return results

    def _detect_mime_type(self, url: str, data: bytes) -> str:
        # 1. Try from URL extension
        mime_type = mimetypes.guess_type(url)[0]
        if mime_type:
            return mime_type

        # 2. Try from data header (magic bytes)
        if data.startswith(b"\x89PNG"):
            return "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        elif data.startswith(b"RIFF") and b"WEBP" in data[:12]:
            return "image/webp"

        # 3. Default to PNG
        return "image/png"


class TaskSyncService:
    """Task synchronization service.

    Responsibilities:
    - Batch query backend task status
    - Parse status responses
    - Download and save result files
    - Update history records
    - Notify upper layer via callback (decoupled from platform)
    - Prevent concurrent duplicate syncs
    """

    def __init__(self, account: "Account", task_history: "AccountTaskHistory"):
        self.account = account
        self.task_history = task_history
        self.parser = StatusResponseParser()
        self.result_callback: Optional[Callable] = None

        self._syncing_task_ids: set = set()
        self._sync_lock = Lock()

    def set_result_callback(self, callback: Callable):
        """Set result callback function.

        When a task completes download, this callback is invoked.
        """
        self.result_callback = callback

    def sync_tasks(self, task_ids: list) -> int:
        if not task_ids:
            return 0

        # Filter out tasks already being synced
        with self._sync_lock:
            available_task_ids = [
                tid for tid in task_ids if tid not in self._syncing_task_ids
            ]
            if not available_task_ids:
                return 0
            self._syncing_task_ids.update(available_task_ids)

        try:
            # 1. Query backend status
            logger.info(f"Querying status of {len(available_task_ids)} tasks...")
            response_json = self.account._fetch_task_status(available_task_ids)

            # 2. Parse response
            status_map = self.parser.parse_batch_response(response_json)

            # 3. Update each task
            success_count = 0
            for task_id in available_task_ids:
                task_history = self.task_history.ensure_task_history(task_id)
                if task_id in status_map:
                    if self._update_single_task(task_history, status_map[task_id]):
                        success_count += 1
                else:
                    self._mark_task_not_found(task_history)

            logger.info(
                f"Successfully synced {success_count}/{len(available_task_ids)} tasks"
            )
            return success_count

        except Exception as e:
            logger.error(f"Failed to sync task status: {e}")
            return 0

        finally:
            with self._sync_lock:
                self._syncing_task_ids.difference_update(available_task_ids)

    def sync_single_task(self, task_id: str) -> bool:
        return self.sync_tasks([task_id]) > 0

    def _update_single_task(
        self, task_history: TaskHistoryData, status: TaskStatusData
    ) -> bool:
        try:
            if status.state.is_success():
                self._handle_completed_task(task_history, status)
            elif status.state.is_running():
                self._handle_processing_task(task_history, status)
            elif status.state.is_failed():
                self._handle_failed_task(task_history, status)
            elif status.state.is_unknown():
                self._handle_not_found_task(task_history, status)
            return True
        except Exception as e:
            logger.error(f"Failed to update task {task_history.task_id}: {e}")
            task_history.error_message = f"Status sync failed: {str(e)}"
            task_history.finished_at = time.time()
            task_history.state = TaskStatus.ERROR
            task_history.progress = 0.0
            return False

    def _handle_completed_task(
        self, task_history: TaskHistoryData, status: TaskStatusData
    ):
        # Skip if already downloaded
        if task_history.state == TaskStatus.SUCCESS and task_history.outputs:
            logger.info(
                f"Task {task_history.task_id} already downloaded, skip re-download"
            )
            return
        logger.info(f"Task {task_history.task_id} completed, downloading result...")

        # Download result
        data = self.parser.download_result(status.urls)

        # Convert to unified format
        parsed_data = self.parser.convert_to_unified_format(data)

        # Save files
        outputs = save_mime_typed_datas_to_temp_files(parsed_data)

        # Update history
        task_history.state = TaskStatus.SUCCESS
        task_history.outputs = outputs
        task_history.result = parsed_data
        task_history.error_message = ""
        task_history.finished_at = time.time()
        task_history.progress = 1.0

        logger.info(f"Task {task_history.task_id} result synchronized")

        # Notify upper layer
        if self.result_callback:
            self.result_callback(task_history)

    def _handle_processing_task(
        self, task_history: TaskHistoryData, status: TaskStatusData
    ):
        logger.info(f"Task {task_history.task_id} is running")
        task_history.state = TaskStatus.RUNNING
        task_history.error_message = ""
        task_history.progress = status.progress

    def _handle_failed_task(
        self, task_history: TaskHistoryData, status: TaskStatusData
    ):
        logger.warning(f"Task {task_history.task_id} failed in backend")
        task_history.state = TaskStatus.FAILED
        task_history.error_message = status.error_message
        task_history.finished_at = time.time()
        task_history.progress = 0.0

    def _handle_not_found_task(
        self, task_history: TaskHistoryData, status: TaskStatusData
    ):
        logger.warning(f"Task {task_history.task_id} not found in backend")
        task_history.state = TaskStatus.UNKNOWN
        task_history.error_message = status.error_message
        task_history.progress = 0.0

    def _mark_task_not_found(self, task_history: TaskHistoryData):
        pass  # Reserved


class TaskStatusPoller:
    """Task status poller.

    Periodically scans pending tasks and calls sync service to update status.
    """

    def __init__(
        self,
        account: "Account",
        sync_service: "TaskSyncService",
        interval: float = 10.0,
    ):
        self.account = account
        self.sync_service = sync_service
        self.interval = interval
        self.running = False
        self.thread = None
        self.pending_task_ids: Queue = Queue()

    def add_pending_task_ids(self, task_ids: list):
        for task_id in task_ids:
            self.pending_task_ids.put(task_id)

    def get_pending_task_ids(self) -> list:
        ids = []
        if self.pending_task_ids.empty():
            return []
        while not self.pending_task_ids.empty():
            ids.append(self.pending_task_ids.get())
        return list(set(ids))

    def start(self):
        if self.running:
            logger.warning("Poller is already running")
            return

        self.running = True
        self.thread = Thread(
            target=self._polling_loop, daemon=True, name="TaskStatusPoller"
        )
        self.thread.start()
        logger.info(f"Task status poller started (interval: {self.interval} seconds)")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        logger.info("Task status poller stopped")

    def _polling_loop(self):
        while self.running:
            try:
                self._poll_once()
            except Exception as e:
                logger.error(f"Error during polling: {e}")

            # Segmented sleep for quick stop response
            for _ in range(int(self.interval * 4)):
                if not self.running:
                    break
                time.sleep(0.25)

    def _poll_once(self):
        task_ids = self.get_pending_task_ids()
        if not task_ids:
            return
        logger.info(f"{len(task_ids)} tasks to sync")
        self.sync_service.sync_tasks(task_ids)
