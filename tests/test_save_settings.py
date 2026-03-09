"""
Tests for save_settings.py

Covers: SaveSettings class (init, properties, generate_filename,
        get_save_path, save_image, preview_filename), global functions.
"""

import os
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

from save_settings import SaveSettings, get_save_settings, init_save_settings
import save_settings as save_settings_module


# ──────────────────────────────────────────────────────────────────────────────
# Init & Properties
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveSettingsInit:

    def test_defaults(self):
        s = SaveSettings()
        assert s.enabled is True
        assert s.output_dir == "output/batchbox"
        assert s.format == "original"
        assert s.quality == 95
        assert s.create_date_subfolder is True
        assert s.include_prompt is False
        assert s.fallback_format == "png"

    def test_custom_settings(self):
        s = SaveSettings({"enabled": False, "quality": 80, "format": "jpg"})
        assert s.enabled is False
        assert s.quality == 80
        assert s.format == "jpg"

    def test_update(self):
        s = SaveSettings()
        s.update({"quality": 50})
        assert s.quality == 50

    def test_to_dict_returns_copy(self):
        s = SaveSettings()
        d = s.to_dict()
        d["quality"] = 1
        assert s.quality == 95  # Original unchanged


# ──────────────────────────────────────────────────────────────────────────────
# generate_filename
# ──────────────────────────────────────────────────────────────────────────────

class TestGenerateFilename:

    def test_basic_pattern(self):
        s = SaveSettings({"naming_pattern": "{model}_{seed}"})
        name = s.generate_filename({"model": "test_model", "seed": 12345})
        assert name == "test_model_12345"

    def test_timestamp_included(self):
        s = SaveSettings({"naming_pattern": "{model}_{timestamp}"})
        name = s.generate_filename({"model": "m"})
        # Timestamp format: YYYYMMDD_HHMMSS
        assert re.search(r'\d{8}_\d{6}', name)

    def test_prompt_included(self):
        s = SaveSettings({
            "naming_pattern": "{model}_{prompt}",
            "include_prompt": True,
        })
        name = s.generate_filename({"model": "m", "prompt": "hello world"})
        assert "hello_world" in name

    def test_prompt_truncated(self):
        s = SaveSettings({
            "naming_pattern": "{prompt}",
            "include_prompt": True,
            "prompt_max_length": 5,
        })
        name = s.generate_filename({"prompt": "abcdefghij"})
        # Prompt limited to 5 chars
        assert len(name) <= 10  # sanitized prompt chars

    def test_prompt_excluded_when_disabled(self):
        s = SaveSettings({
            "naming_pattern": "{model}_{prompt}_{seed}",
            "include_prompt": False,
        })
        name = s.generate_filename({"model": "m", "prompt": "hello", "seed": 1})
        # prompt replaced with empty string, double underscores cleaned
        assert "hello" not in name

    def test_unknown_placeholder_removed(self):
        s = SaveSettings({"naming_pattern": "{model}_{nonexistent}_{seed}"})
        name = s.generate_filename({"model": "m", "seed": 1})
        assert "{nonexistent}" not in name
        # Should not have double underscores
        assert "__" not in name

    def test_sanitize_special_chars(self):
        s = SaveSettings({"naming_pattern": "{model}"})
        name = s.generate_filename({"model": "my/model with spaces!"})
        assert "/" not in name
        assert "!" not in name
        assert " " not in name


# ──────────────────────────────────────────────────────────────────────────────
# get_save_path
# ──────────────────────────────────────────────────────────────────────────────

class TestGetSavePath:

    def test_creates_directory(self, tmp_path):
        s = SaveSettings({
            "output_dir": "output/test_out",
            "format": "png",
            "create_date_subfolder": False,
            "naming_pattern": "{seed}",
        })
        with patch("save_settings.folder_paths") as mock_fp:
            mock_fp.get_output_directory.return_value = str(tmp_path)
            path = s.get_save_path({"seed": 1})
        assert path.parent.exists()

    def test_date_subfolder(self, tmp_path):
        s = SaveSettings({
            "output_dir": "output/batchbox",
            "format": "png",
            "create_date_subfolder": True,
            "naming_pattern": "{seed}",
        })
        with patch("save_settings.folder_paths") as mock_fp:
            mock_fp.get_output_directory.return_value = str(tmp_path)
            path = s.get_save_path({"seed": 1})
        # Path should contain a date folder like 2026-03-09
        assert re.search(r'\d{4}-\d{2}-\d{2}', str(path))

    def test_no_date_subfolder(self, tmp_path):
        s = SaveSettings({
            "output_dir": "output/batchbox",
            "format": "png",
            "create_date_subfolder": False,
            "naming_pattern": "{seed}",
        })
        with patch("save_settings.folder_paths") as mock_fp:
            mock_fp.get_output_directory.return_value = str(tmp_path)
            path = s.get_save_path({"seed": 1})
        # No date folder in path
        parts = str(path).split(os.sep)
        assert not any(re.match(r'\d{4}-\d{2}-\d{2}$', p) for p in parts)


# ──────────────────────────────────────────────────────────────────────────────
# save_image
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveImage:

    def test_disabled_returns_none(self, pil_rgb_image):
        s = SaveSettings({"enabled": False})
        result = s.save_image(pil_rgb_image, {"seed": 1})
        assert result is None

    def test_saves_png(self, pil_rgb_image, tmp_path):
        s = SaveSettings({
            "format": "png",
            "output_dir": "output/test",
            "create_date_subfolder": False,
            "naming_pattern": "test_{seed}",
        })
        with patch("save_settings.folder_paths") as mock_fp:
            mock_fp.get_output_directory.return_value = str(tmp_path)
            result = s.save_image(pil_rgb_image, {"seed": 42})

        assert result is not None
        assert result["filepath"].endswith(".png")
        assert Path(result["filepath"]).exists()

    def test_saves_jpeg_from_rgba(self, pil_rgba_image, tmp_path):
        s = SaveSettings({
            "format": "jpg",
            "output_dir": "output/test",
            "create_date_subfolder": False,
            "naming_pattern": "test_{seed}",
        })
        with patch("save_settings.folder_paths") as mock_fp:
            mock_fp.get_output_directory.return_value = str(tmp_path)
            result = s.save_image(pil_rgba_image, {"seed": 1})

        assert result is not None
        assert result["filepath"].endswith(".jpg")
        # Verify it saved correctly (RGBA -> RGB conversion)
        saved = Image.open(result["filepath"])
        assert saved.mode == "RGB"

    def test_original_format_with_known(self, pil_rgb_image, tmp_path):
        s = SaveSettings({
            "format": "original",
            "output_dir": "output/test",
            "create_date_subfolder": False,
            "naming_pattern": "test_{seed}",
        })
        with patch("save_settings.folder_paths") as mock_fp:
            mock_fp.get_output_directory.return_value = str(tmp_path)
            result = s.save_image(pil_rgb_image, {"seed": 1}, original_format="png")

        assert result is not None
        assert result["filepath"].endswith(".png")

    def test_original_format_fallback(self, pil_rgb_image, tmp_path):
        s = SaveSettings({
            "format": "original",
            "fallback_format": "png",
            "output_dir": "output/test",
            "create_date_subfolder": False,
            "naming_pattern": "test_{seed}",
        })
        with patch("save_settings.folder_paths") as mock_fp:
            mock_fp.get_output_directory.return_value = str(tmp_path)
            result = s.save_image(pil_rgb_image, {"seed": 1})

        assert result is not None
        assert result["filepath"].endswith(".png")


# ──────────────────────────────────────────────────────────────────────────────
# preview_filename
# ──────────────────────────────────────────────────────────────────────────────

class TestPreviewFilename:

    def test_default_context(self):
        s = SaveSettings({"format": "png", "naming_pattern": "{model}_{seed}"})
        preview = s.preview_filename()
        assert "nano_banana_pro" in preview
        assert "1234567890" in preview
        assert preview.endswith(".png")

    def test_custom_context(self):
        s = SaveSettings({"format": "jpg", "naming_pattern": "{model}"})
        preview = s.preview_filename({"model": "custom_model"})
        assert "custom_model" in preview
        assert preview.endswith(".jpg")


# ──────────────────────────────────────────────────────────────────────────────
# Global functions
# ──────────────────────────────────────────────────────────────────────────────

class TestGlobalFunctions:

    def test_get_save_settings_creates_default(self):
        save_settings_module._save_settings = None
        s = get_save_settings()
        assert isinstance(s, SaveSettings)
        assert s.enabled is True

    def test_init_save_settings_replaces(self):
        old = get_save_settings()
        new = init_save_settings({"enabled": False})
        assert new is not old
        assert new.enabled is False
        assert get_save_settings() is new
        # Restore
        save_settings_module._save_settings = None
