"""
Shared test fixtures for ComfyUI-Custom-Batchbox test suite.
"""

import os
import sys
import io
import tempfile
from unittest.mock import MagicMock

import pytest
from PIL import Image

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ──────────────────────────────────────────────────────────────────────────────
# Mock ComfyUI dependencies that are not available in test environment
# ──────────────────────────────────────────────────────────────────────────────

# Must inject folder_paths at module level (before test collection)
# because save_settings.py, independent_generator.py, etc. do
# `import folder_paths` at the top level.
if "folder_paths" not in sys.modules:
    _mock_fp = MagicMock()
    _tmp_base = tempfile.mkdtemp(prefix="batchbox_test_")
    _mock_fp.get_output_directory.return_value = os.path.join(_tmp_base, "output")
    _mock_fp.get_temp_directory.return_value = os.path.join(_tmp_base, "temp")
    _mock_fp.get_input_directory.return_value = os.path.join(_tmp_base, "input")
    for sub in ("output", "temp", "input"):
        os.makedirs(os.path.join(_tmp_base, sub), exist_ok=True)
    sys.modules["folder_paths"] = _mock_fp

# ──────────────────────────────────────────────────────────────────────────────
# Fake package hierarchy for relative imports
# ──────────────────────────────────────────────────────────────────────────────
# Modules like volcengine.py use `from ..batchbox_logger import ...` and
# independent_generator.py uses `from .config_manager import ...`.
# We register the project root as a package in sys.modules so these resolve.

from types import ModuleType

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_pkg_name = os.path.basename(_project_root)

if _pkg_name not in sys.modules:
    _fake_pkg = ModuleType(_pkg_name)
    _fake_pkg.__path__ = [_project_root]
    sys.modules[_pkg_name] = _fake_pkg

# Register sub-packages and key modules under the fake package
_adapters_dir = os.path.join(_project_root, "adapters")
_adapters_pkg = f"{_pkg_name}.adapters"
if _adapters_pkg not in sys.modules:
    _fake_adapters = ModuleType(_adapters_pkg)
    _fake_adapters.__path__ = [_adapters_dir]
    sys.modules[_adapters_pkg] = _fake_adapters

# Import and register modules that are used via relative imports
import batchbox_logger as _bl  # noqa: E402
import config_manager as _cm  # noqa: E402

sys.modules.setdefault(f"{_pkg_name}.batchbox_logger", _bl)
sys.modules.setdefault(f"{_pkg_name}.config_manager", _cm)

# Register adapter sub-modules
from adapters import base as _ab, generic as _ag, template_engine as _ate  # noqa: E402
sys.modules.setdefault(f"{_adapters_pkg}.base", _ab)
sys.modules.setdefault(f"{_adapters_pkg}.generic", _ag)
sys.modules.setdefault(f"{_adapters_pkg}.template_engine", _ate)

# Register account sub-package
_account_dir = os.path.join(_project_root, "account")
_account_pkg = f"{_pkg_name}.account"
if _account_pkg not in sys.modules:
    _fake_account = ModuleType(_account_pkg)
    _fake_account.__path__ = [_account_dir]
    sys.modules[_account_pkg] = _fake_account

# Register account sub-modules (they use relative imports like from .network)
from account import exceptions as _ae, network as _an, url_config as _auc  # noqa: E402
from account import task_history as _ath  # noqa: E402
sys.modules.setdefault(f"{_account_pkg}.exceptions", _ae)
sys.modules.setdefault(f"{_account_pkg}.network", _an)
sys.modules.setdefault(f"{_account_pkg}.url_config", _auc)
sys.modules.setdefault(f"{_account_pkg}.task_history", _ath)

# Register modules that are lazily imported via relative paths
# (volcengine, cache modules, etc. — registered on demand by tests)


# ──────────────────────────────────────────────────────────────────────────────
# PIL Image fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def pil_rgb_image():
    """64x64 RGB test image with a gradient pattern."""
    img = Image.new("RGB", (64, 64))
    pixels = img.load()
    for x in range(64):
        for y in range(64):
            pixels[x, y] = (x * 4, y * 4, 128)
    return img


@pytest.fixture
def pil_rgba_image():
    """64x64 RGBA test image with a semi-transparent center."""
    img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
    pixels = img.load()
    # Make the center 32x32 region semi-transparent
    for x in range(16, 48):
        for y in range(16, 48):
            pixels[x, y] = (0, 255, 0, 128)
    return img


@pytest.fixture
def sample_image_bytes_png(pil_rgb_image):
    """PNG-encoded bytes from a test image."""
    buf = io.BytesIO()
    pil_rgb_image.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sample_image_bytes_jpeg(pil_rgb_image):
    """JPEG-encoded bytes from a test image."""
    buf = io.BytesIO()
    pil_rgb_image.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# Adapter config fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_provider_config():
    return {
        "name": "test_provider",
        "base_url": "https://api.test.com",
        "api_key": "test-api-key-123",
    }


@pytest.fixture
def mock_endpoint_config():
    return {
        "provider": "test_provider",
        "model_name": "test-model-v1",
        "api_format": "openai",
        "modes": {
            "text2img": {
                "endpoint": "/v1/images/generations",
                "method": "POST",
                "content_type": "application/json",
            }
        },
    }


@pytest.fixture
def mock_mode_config():
    return {
        "endpoint": "/v1/images/generations",
        "method": "POST",
        "content_type": "application/json",
        "response_type": "url",
        "response_path": "data.0.url",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Temp database path for cache tests
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db_path(tmp_path):
    """Temporary SQLite database path for cache tests."""
    return str(tmp_path / "test_cache.db")
