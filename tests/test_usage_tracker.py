"""
Tests for usage_tracker module.
"""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure the package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock folder_paths (ComfyUI-specific module) before importing usage_tracker
_mock_folder_paths = MagicMock()
_mock_folder_paths.base_path = tempfile.gettempdir()
sys.modules["folder_paths"] = _mock_folder_paths


class TestGetMacLast6:
    """Test MAC address extraction."""

    def test_returns_6_chars(self):
        from usage_tracker import _get_mac_last6
        result = _get_mac_last6()
        assert len(result) == 6
        assert all(c in "0123456789ABCDEF" for c in result)


class TestGetMachineId:
    """Test machine ID generation."""

    def test_format(self):
        from usage_tracker import _get_machine_id
        mid = _get_machine_id()
        assert "_" in mid
        parts = mid.rsplit("_", 1)
        assert len(parts) == 2
        assert len(parts[1]) == 6  # MAC suffix

    @patch.dict(os.environ, {"COMPUTERNAME": "LAB-01"})
    def test_uses_computername(self):
        from usage_tracker import _get_machine_id
        mid = _get_machine_id()
        assert mid.startswith("LAB-01_")


class TestUsageTracker:
    """Test UsageTracker core functionality."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the singleton before each test and block real NAS writes."""
        from usage_tracker import UsageTracker
        UsageTracker._instance = None
        # Patch NAS detection to prevent test data leaking to real NAS
        with patch("usage_tracker._find_nas_dir", return_value=None):
            yield
        UsageTracker._instance = None

    @pytest.fixture
    def tracker_with_tmpdir(self, tmp_path):
        """Create a tracker with temp directories."""
        from usage_tracker import UsageTracker
        tracker = UsageTracker()
        tracker._local_base = str(tmp_path / "local")
        tracker._nas_base = str(tmp_path / "nas")
        tracker._machine_id = "TEST-PC_AABBCC"
        return tracker

    def test_singleton(self):
        from usage_tracker import UsageTracker
        a = UsageTracker()
        b = UsageTracker()
        assert a is b

    def test_record_creates_jsonl(self, tracker_with_tmpdir, tmp_path):
        """Test that record() creates a valid JSONL file."""
        tracker = tracker_with_tmpdir
        tracker.record(
            node_type="image",
            model="NanoBananaPro",
            batch_count=4,
            images_generated=4,
            images_saved=4,
            success=True,
            providers_tried=["Google"],
            duration_seconds=12.5,
        )

        # Wait a moment for NAS background thread
        import time
        time.sleep(0.5)

        # Check local file
        local_dir = tmp_path / "local"
        assert local_dir.exists()
        jsonl_files = list(local_dir.glob("usage_*.jsonl"))
        assert len(jsonl_files) == 1

        with open(jsonl_files[0], "r", encoding="utf-8") as f:
            line = f.readline().strip()
            record = json.loads(line)

        assert record["machine"] == "TEST-PC_AABBCC"
        assert record["node"] == "image"
        assert record["model"] == "NanoBananaPro"
        assert record["batch"] == 4
        assert record["gen"] == 4
        assert record["saved"] == 4
        assert record["ok"] is True
        assert record["providers"] == ["Google"]
        assert record["dur_s"] == 12.5
        assert "task_id" in record
        assert "ts" in record

    def test_record_nas_sync(self, tracker_with_tmpdir, tmp_path):
        """Test that NAS sync writes the same data."""
        tracker = tracker_with_tmpdir
        tracker.record(
            node_type="independent",
            model="TestModel",
            batch_count=1,
            images_generated=1,
            images_saved=1,
            success=True,
        )

        import time
        time.sleep(0.5)

        nas_dir = tmp_path / "nas"
        assert nas_dir.exists()
        jsonl_files = list(nas_dir.glob("usage_*.jsonl"))
        assert len(jsonl_files) == 1

    def test_record_failure(self, tracker_with_tmpdir, tmp_path):
        """Test recording a failed generation."""
        tracker = tracker_with_tmpdir
        tracker.record(
            node_type="text",
            model="SomeModel",
            batch_count=1,
            images_generated=0,
            images_saved=0,
            success=False,
            error_message="API timeout",
            providers_tried=["Google", "Vertex"],
        )

        import time
        time.sleep(0.2)

        local_dir = tmp_path / "local"
        jsonl_files = list(local_dir.glob("usage_*.jsonl"))
        with open(jsonl_files[0], "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert record["ok"] is False
        assert record["err"] == "API timeout"
        assert record["providers"] == ["Google", "Vertex"]
        assert record["gen"] == 0

    def test_record_provider_usage_appends_without_replacing_existing_fields(self, tracker_with_tmpdir, tmp_path):
        """Provider/key usage is additive and never stores full API keys."""
        tracker = tracker_with_tmpdir
        tracker.record(
            node_type="image",
            model="NanoBananaPro",
            batch_count=2,
            images_generated=2,
            images_saved=1,
            success=True,
            providers_tried=["google"],
            provider_usage=[
                {
                    "provider": "google",
                    "provider_label": "Google",
                    "key_label": "main · ****abcdef",
                    "key": "sk-full-secret-abcdef",
                    "gen": 2,
                },
            ],
            duration_seconds=3.4,
        )

        import time
        time.sleep(0.2)

        local_dir = tmp_path / "local"
        jsonl_files = list(local_dir.glob("usage_*.jsonl"))
        with open(jsonl_files[0], "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert record["machine"] == "TEST-PC_AABBCC"
        assert record["model"] == "NanoBananaPro"
        assert record["gen"] == 2
        assert record["saved"] == 1
        assert record["providers"] == ["google"]
        assert record["provider_usage"] == [
            {
                "provider": "google",
                "provider_label": "Google",
                "key_label": "main · ****abcdef",
                "gen": 2,
            }
        ]
        assert "sk-full-secret-abcdef" not in json.dumps(record, ensure_ascii=False)

    def test_nas_failure_graceful(self, tracker_with_tmpdir):
        """Test that NAS write failure doesn't crash."""
        tracker = tracker_with_tmpdir
        tracker._nas_base = "/nonexistent/path/that/will/fail"

        # Should not raise
        tracker.record(
            node_type="video",
            model="TestModel",
            batch_count=1,
            images_generated=0,
            images_saved=0,
            success=False,
        )

        import time
        time.sleep(0.5)
        # No assertion needed — just verify no exception

    def test_concurrent_writes(self, tracker_with_tmpdir, tmp_path):
        """Test thread safety with concurrent writes."""
        tracker = tracker_with_tmpdir
        errors = []

        def write_records(n):
            try:
                for _ in range(n):
                    tracker.record(
                        node_type="image",
                        model="TestModel",
                        batch_count=1,
                        images_generated=1,
                        images_saved=1,
                        success=True,
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_records, args=(10,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        import time
        time.sleep(1)

        assert len(errors) == 0

        # Verify all 50 records were written
        local_dir = tmp_path / "local"
        jsonl_files = list(local_dir.glob("usage_*.jsonl"))
        total_lines = 0
        for f in jsonl_files:
            with open(f, "r", encoding="utf-8") as fh:
                total_lines += sum(1 for line in fh if line.strip())
        assert total_lines == 50

    def test_daily_rotation_filename(self, tracker_with_tmpdir):
        """Test that filename contains today's date."""
        tracker = tracker_with_tmpdir
        filename = tracker._get_today_filename()
        assert filename.startswith("usage_")
        assert filename.endswith(".jsonl")
        # Should contain date in YYYY-MM-DD format
        from datetime import datetime, timezone, timedelta
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        assert today in filename

    def test_error_message_truncation(self, tracker_with_tmpdir, tmp_path):
        """Test that very long error messages are truncated."""
        tracker = tracker_with_tmpdir
        long_error = "x" * 500
        tracker.record(
            node_type="image",
            model="TestModel",
            batch_count=1,
            images_generated=0,
            images_saved=0,
            success=False,
            error_message=long_error,
        )

        import time
        time.sleep(0.2)

        local_dir = tmp_path / "local"
        jsonl_files = list(local_dir.glob("usage_*.jsonl"))
        with open(jsonl_files[0], "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert len(record["err"]) == 200  # Truncated to 200 chars


class TestGetTracker:
    """Test module-level convenience function."""

    @pytest.fixture(autouse=True)
    def reset(self):
        import usage_tracker
        usage_tracker._tracker = None
        usage_tracker.UsageTracker._instance = None
        yield
        usage_tracker._tracker = None
        usage_tracker.UsageTracker._instance = None

    def test_returns_singleton(self):
        from usage_tracker import get_tracker
        a = get_tracker()
        b = get_tracker()
        assert a is b


class TestFindNasDir:
    """Test NAS directory auto-detection."""

    @patch.dict(os.environ, {"BATCHBOX_SHARED_CACHE": ""}, clear=False)
    def test_no_env_no_nas(self):
        from usage_tracker import _find_nas_dir
        # With no env var and no NAS drive, should return None
        # (unless test machine actually has a NAS mounted)
        result = _find_nas_dir()
        # Just verify it returns str or None, doesn't crash
        assert result is None or isinstance(result, str)

    @patch.dict(os.environ, {"BATCHBOX_SHARED_CACHE": ""}, clear=False)
    def test_with_env_var(self, tmp_path):
        from usage_tracker import _find_nas_dir
        cache_dir = str(tmp_path / "shared_cache")
        os.makedirs(cache_dir)
        with patch.dict(os.environ, {"BATCHBOX_SHARED_CACHE": cache_dir}):
            result = _find_nas_dir()
            assert result is not None
            assert result.endswith("usage_logs")
