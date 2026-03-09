"""
Tests for account/task_sync.py

Covers: StatusResponseParser (_normalize_state, parse_batch_response, _detect_mime_type),
        TaskStatusPoller (add/get pending), save_mime_typed_datas_to_temp_files.
"""

import importlib
import os
from unittest.mock import MagicMock

_pkg = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import via package path
_ts_mod = importlib.import_module(f"{_pkg}.account.task_sync")
_th_mod = importlib.import_module(f"{_pkg}.account.task_history")

StatusResponseParser = _ts_mod.StatusResponseParser
TaskStatusPoller = _ts_mod.TaskStatusPoller
save_mime_typed_datas_to_temp_files = _ts_mod.save_mime_typed_datas_to_temp_files
TaskStatus = _th_mod.TaskStatus


# ──────────────────────────────────────────────────────────────────────────────
# StatusResponseParser._normalize_state
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeState:

    def test_success_variants(self):
        p = StatusResponseParser
        assert p._normalize_state("SUCCESS") == TaskStatus.SUCCESS
        assert p._normalize_state("completed") == TaskStatus.SUCCESS
        assert p._normalize_state("succeeded") == TaskStatus.SUCCESS

    def test_running_variants(self):
        p = StatusResponseParser
        assert p._normalize_state("RUNNING") == TaskStatus.RUNNING
        assert p._normalize_state("processing") == TaskStatus.RUNNING
        assert p._normalize_state("pending") == TaskStatus.RUNNING
        assert p._normalize_state("in_progress") == TaskStatus.RUNNING

    def test_failed_variants(self):
        p = StatusResponseParser
        assert p._normalize_state("FAILED") == TaskStatus.FAILED
        assert p._normalize_state("failed") == TaskStatus.FAILED
        assert p._normalize_state("failure") == TaskStatus.FAILED

    def test_error(self):
        assert StatusResponseParser._normalize_state("error") == TaskStatus.ERROR

    def test_empty_string(self):
        assert StatusResponseParser._normalize_state("") == TaskStatus.UNKNOWN

    def test_none(self):
        assert StatusResponseParser._normalize_state(None) == TaskStatus.UNKNOWN

    def test_unknown_value(self):
        assert StatusResponseParser._normalize_state("xyz_garbage") == TaskStatus.UNKNOWN


# ──────────────────────────────────────────────────────────────────────────────
# StatusResponseParser.parse_batch_response
# ──────────────────────────────────────────────────────────────────────────────

class TestParseBatchResponse:

    def test_success_task(self):
        parser = StatusResponseParser()
        resp = {
            "data": {
                "task1": {
                    "state": "completed",
                    "urls": ["https://example.com/img.png"],
                }
            }
        }
        result = parser.parse_batch_response(resp)
        assert "task1" in result
        assert result["task1"].state == TaskStatus.SUCCESS
        assert result["task1"].urls == ["https://example.com/img.png"]
        assert result["task1"].progress == 1.0

    def test_running_with_progress(self):
        parser = StatusResponseParser()
        resp = {
            "data": {
                "task2": {
                    "state": "running",
                    "progress": 0.5,
                }
            }
        }
        result = parser.parse_batch_response(resp)
        assert result["task2"].state == TaskStatus.RUNNING
        assert result["task2"].progress == 0.5

    def test_empty_data(self):
        parser = StatusResponseParser()
        result = parser.parse_batch_response({"data": {}})
        assert result == {}

    def test_non_dict_data(self):
        parser = StatusResponseParser()
        result = parser.parse_batch_response({"data": "invalid"})
        assert result == {}


# ──────────────────────────────────────────────────────────────────────────────
# StatusResponseParser._detect_mime_type
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectMimeType:

    def test_from_url_extension(self):
        parser = StatusResponseParser()
        assert parser._detect_mime_type("https://example.com/img.png", b"") == "image/png"

    def test_from_magic_bytes_jpeg(self):
        parser = StatusResponseParser()
        assert parser._detect_mime_type("https://example.com/noext", b"\xff\xd8\xff\xe0") == "image/jpeg"

    def test_from_magic_bytes_png(self):
        parser = StatusResponseParser()
        assert parser._detect_mime_type("https://example.com/noext", b"\x89PNG\r\n") == "image/png"

    def test_default_png(self):
        parser = StatusResponseParser()
        assert parser._detect_mime_type("https://example.com/noext", b"unknown") == "image/png"


# ──────────────────────────────────────────────────────────────────────────────
# TaskStatusPoller
# ──────────────────────────────────────────────────────────────────────────────

class TestTaskStatusPoller:

    def test_add_and_get_pending(self):
        poller = TaskStatusPoller(MagicMock(), MagicMock(), interval=5)
        poller.add_pending_task_ids(["t1", "t2"])
        ids = poller.get_pending_task_ids()
        assert set(ids) == {"t1", "t2"}

    def test_get_pending_clears_queue(self):
        poller = TaskStatusPoller(MagicMock(), MagicMock())
        poller.add_pending_task_ids(["t1"])
        poller.get_pending_task_ids()
        assert poller.get_pending_task_ids() == []

    def test_dedup_pending(self):
        poller = TaskStatusPoller(MagicMock(), MagicMock())
        poller.add_pending_task_ids(["t1", "t1", "t1"])
        ids = poller.get_pending_task_ids()
        assert ids == ["t1"]

    def test_stop_sets_running_false(self):
        poller = TaskStatusPoller(MagicMock(), MagicMock())
        poller.running = True
        poller.thread = None
        poller.stop()
        assert poller.running is False


# ──────────────────────────────────────────────────────────────────────────────
# save_mime_typed_datas_to_temp_files
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveMimeTypedDatas:

    def test_saves_bytes(self):
        data = [("image/png", b"\x89PNG test data")]
        results = save_mime_typed_datas_to_temp_files(data)
        assert len(results) == 1
        mime, path = results[0]
        assert mime == "image/png"
        assert os.path.exists(path)

    def test_saves_text(self):
        data = [("text/plain", "hello world")]
        results = save_mime_typed_datas_to_temp_files(data)
        assert len(results) == 1
        assert os.path.exists(results[0][1])

    def test_multiple_files_indexed(self):
        data = [("image/png", b"img1"), ("image/jpeg", b"img2")]
        results = save_mime_typed_datas_to_temp_files(data)
        assert len(results) == 2
        # Filenames should contain index
        assert "_0" in results[0][1]
        assert "_1" in results[1][1]
