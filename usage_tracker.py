"""
Usage Tracker Module

Records API usage statistics for monitoring across student machines.
Data written locally first (JSONL), then synced to NAS in background.

Architecture:
  - Local: {ComfyUI_root}/usage_logs/{machine_id}/usage_YYYY-MM-DD.jsonl
  - NAS:   {BATCHBOX_SHARED_CACHE}/usage_logs/{machine_id}/usage_YYYY-MM-DD.jsonl
"""

import json
import os
import threading
import time
import uuid
import shutil
import shutil
import socket
import logging
import ctypes
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("batchbox.usage")

# Beijing timezone offset
_TZ_CST = timezone(timedelta(hours=8))


def _get_mac_last6() -> str:
    """Get last 6 hex chars of the primary MAC address."""
    try:
        import uuid as _uuid
        mac = _uuid.getnode()
        mac_hex = f"{mac:012x}".upper()
        return mac_hex[-6:]
    except Exception:
        return "000000"


def _get_machine_id() -> str:
    """
    Generate machine identifier: {COMPUTERNAME}_{MAC_last6}.
    Example: LAB-01_F5E4D3
    """
    hostname = os.environ.get("COMPUTERNAME", socket.gethostname())
    mac_suffix = _get_mac_last6()
    return f"{hostname}_{mac_suffix}"


def _get_comfyui_base_path() -> Optional[str]:
    """Get ComfyUI root directory dynamically."""
    try:
        import folder_paths
        return folder_paths.base_path
    except ImportError:
        return None


def _find_nas_dir() -> Optional[str]:
    """
    Find NAS usage_logs directory.
    Priority: BATCHBOX_SHARED_CACHE env → auto-detect NAS drive.
    """
    # 1. Environment variable (set by Start_Client.bat)
    shared_cache = os.environ.get("BATCHBOX_SHARED_CACHE")
    if shared_cache and os.path.isdir(shared_cache):
        return os.path.join(shared_cache, "usage_logs")

    # 2. Auto-detect NAS drive (same logic as Start_Client.bat)
    nas_folder = r"ComfyUI_Master\shared_cache"
    for letter in "ZYXWVUTSRQPONMLKJIHGF":
        candidate = f"{letter}:\\{nas_folder}"
        if os.path.isdir(candidate):
            return os.path.join(candidate, "usage_logs")

    return None


class UsageTracker:
    """
    Singleton usage tracker. Records API calls to local JSONL + NAS.

    Thread-safe. NAS writes are async (background thread).
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._write_lock = threading.Lock()
        self._machine_id = _get_machine_id()
        self._local_base = None
        self._nas_base = None
        self._daily_gen = 0
        self._last_warn_tier = 0
        self._init_paths()
        self._load_today_gen()
        logger.info("[UsageTracker] Machine ID: %s", self._machine_id)
        
        # Start background sync thread
        self._sync_loop_running = True
        threading.Thread(target=self._sync_loop, daemon=True).start()

    def _sync_loop(self):
        """Background thread that runs periodically to sync missing logs to NAS."""
        while self._sync_loop_running:
            try:
                # Attempt to find NAS dir (it might become available later)
                if not self._nas_base:
                    nas_dir = _find_nas_dir()
                    if nas_dir:
                        self._nas_base = os.path.join(nas_dir, self._machine_id)
                        logger.info("[UsageTracker] NAS discovered: %s", self._nas_base)
                
                if self._nas_base and self._local_base and os.path.exists(self._local_base):
                    self._sync_backlog_to_nas()
            except Exception as e:
                logger.debug("[UsageTracker] Sync loop error: %s", e)
            
            # Wait 5 minutes before next check
            time.sleep(300)

    def _sync_backlog_to_nas(self):
        """Cross-check local vs NAS files, push missing or larger files to NAS."""
        os.makedirs(self._nas_base, exist_ok=True)
        for filename in os.listdir(self._local_base):
            if not filename.endswith(".jsonl"):
                continue
            
            local_path = os.path.join(self._local_base, filename)
            nas_path = os.path.join(self._nas_base, filename)
            
            if not os.path.exists(local_path):
                continue
                
            local_size = os.path.getsize(local_path)
            
            sync_needed = False
            if not os.path.exists(nas_path):
                sync_needed = True
            else:
                nas_size = os.path.getsize(nas_path)
                if local_size > nas_size:
                    sync_needed = True
            
            if sync_needed:
                try:
                    with self._write_lock:
                        shutil.copy2(local_path, nas_path)
                    logger.debug("[UsageTracker] Synced %s to NAS (%d bytes)", filename, local_size)
                except Exception as e:
                    logger.debug("[UsageTracker] Failed to sync %s: %s", filename, e)

    def _init_paths(self):
        """Initialize local and NAS log directories."""
        # Local path: {ComfyUI_root}/usage_logs/{machine_id}/
        base = _get_comfyui_base_path()
        if base:
            self._local_base = os.path.join(base, "usage_logs", self._machine_id)
        else:
            # Fallback: %LOCALAPPDATA%\BatchBox\usage_logs\{machine_id}
            appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            self._local_base = os.path.join(appdata, "BatchBox", "usage_logs", self._machine_id)

        # NAS path
        nas_dir = _find_nas_dir()
        if nas_dir:
            self._nas_base = os.path.join(nas_dir, self._machine_id)

        logger.info("[UsageTracker] Local: %s", self._local_base)
        logger.info("[UsageTracker] NAS: %s", self._nas_base or "(not found)")

    def _load_today_gen(self):
        """Load today's tally from local file to survive ComfyUI restarts."""
        if not self._local_base:
            return
        filepath = os.path.join(self._local_base, self._get_today_filename())
        if not os.path.exists(filepath):
            return
        total = 0
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip(): continue
                    try:
                        total += json.loads(line).get("gen", 0)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("[UsageTracker] Failed to read today's gen: %s", e)
        self._daily_gen = total
        self._last_warn_tier = self._calc_tier(self._daily_gen)
        logger.info("[UsageTracker] Today's initial gen count loaded: %d", self._daily_gen)

    def _calc_tier(self, gen_count: int) -> int:
        if gen_count < 800:
            return 0
        return 1 + (gen_count - 800) // 200

    @property
    def machine_id(self) -> str:
        return self._machine_id

    def _get_today_filename(self) -> str:
        """Generate daily log filename: usage_YYYY-MM-DD.jsonl"""
        now = datetime.now(_TZ_CST)
        return f"usage_{now.strftime('%Y-%m-%d')}.jsonl"

    def record(
        self,
        node_type: str,
        model: str,
        batch_count: int,
        images_generated: int,
        images_saved: int,
        success: bool,
        providers_tried: Optional[List[str]] = None,
        error_message: str = "",
        duration_seconds: float = 0.0,
    ):
        """
        Record a single generation task.

        Args:
            node_type: "image", "independent", "editor", "blur_upscale",
                       "text", "video", "audio"
            model: Model name used
            batch_count: Number of batch items requested
            images_generated: Images actually returned by API
            images_saved: Images saved to output directory
            success: Whether the task succeeded
            providers_tried: List of provider names attempted
            error_message: Error message if failed
            duration_seconds: Time taken in seconds
        """
        record = {
            "task_id": uuid.uuid4().hex[:12],
            "ts": datetime.now(_TZ_CST).isoformat(timespec="seconds"),
            "dur_s": round(duration_seconds, 1),
            "machine": self._machine_id,
            "node": node_type,
            "model": model,
            "batch": batch_count,
            "gen": images_generated,
            "saved": images_saved,
            "ok": success,
            "providers": providers_tried or [],
            "err": error_message[:200] if error_message else "",
        }

        # Check and warn student
        if images_generated > 0:
            with self._write_lock:
                self._daily_gen += images_generated
                new_tier = self._calc_tier(self._daily_gen)
                if new_tier > self._last_warn_tier:
                    self._last_warn_tier = new_tier
                    warning_msg = f"⚠️警告：您今日生成的图片数量已达 {self._daily_gen} 张！\n过度使用会占用整个实验室的算力资源，请尽量节约喔。"
                    threading.Thread(
                        target=lambda: ctypes.windll.user32.MessageBoxW(0, warning_msg, "用量预警系统", 0x30 | 0x0),
                        daemon=True
                    ).start()

        json_line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))

        # Write local (synchronous, fast)
        try:
            self._write_local(json_line)
        except Exception as e:
            logger.warning("[UsageTracker] Local write failed: %s", e)

        # Write NAS (async, background thread)
        if self._nas_base:
            threading.Thread(
                target=self._write_nas,
                args=(json_line,),
                daemon=True,
            ).start()

    def _write_local(self, json_line: str):
        """Append a JSONL line to local log file."""
        with self._write_lock:
            os.makedirs(self._local_base, exist_ok=True)
            filepath = os.path.join(self._local_base, self._get_today_filename())
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json_line + "\n")

    def _write_nas(self, json_line: str):
        """Append a JSONL line to NAS log file (called in background thread)."""
        if not self._nas_base:
            return
        try:
            os.makedirs(self._nas_base, exist_ok=True)
            filepath = os.path.join(self._nas_base, self._get_today_filename())
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json_line + "\n")
        except Exception as e:
            # NAS write failure is non-fatal — local copy is the source of truth
            logger.debug("[UsageTracker] NAS write failed (non-fatal): %s", e)


# Module-level convenience function
_tracker: Optional[UsageTracker] = None


def get_tracker() -> UsageTracker:
    """Get or create the global UsageTracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker
