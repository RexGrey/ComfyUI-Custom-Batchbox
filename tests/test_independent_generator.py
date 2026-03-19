"""
Tests for independent_generator.py

Covers: parameter hashing, adapter routing, failover, and parallel generation.
"""

import os
import asyncio
import base64
import importlib
from io import BytesIO
from unittest.mock import patch, Mock, MagicMock

import pytest
from PIL import Image

# independent_generator.py uses relative imports (from .config_manager, etc.)
# so we import it via its package path.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_pkg = os.path.basename(_project_root)
_ig_mod = importlib.import_module(f"{_pkg}.independent_generator")
_volc_mod = importlib.import_module(f"{_pkg}.adapters.volcengine")
IndependentGenerator = _ig_mod.IndependentGenerator
APIResponse = importlib.import_module(f"{_pkg}.adapters.base").APIResponse


# ──────────────────────────────────────────────────────────────────────────────
# _compute_params_hash
# ──────────────────────────────────────────────────────────────────────────────

class TestComputeParamsHash:

    def setup_method(self):
        self.gen = IndependentGenerator()

    def test_deterministic(self):
        h1 = self.gen._compute_params_hash("model", "prompt", 1, 42, {"k": "v"})
        h2 = self.gen._compute_params_hash("model", "prompt", 1, 42, {"k": "v"})
        assert h1 == h2

    def test_different_prompt_different_hash(self):
        h1 = self.gen._compute_params_hash("model", "cat", 1, 42, {})
        h2 = self.gen._compute_params_hash("model", "dog", 1, 42, {})
        assert h1 != h2

    def test_different_seed_different_hash(self):
        h1 = self.gen._compute_params_hash("model", "prompt", 1, 1, {})
        h2 = self.gen._compute_params_hash("model", "prompt", 1, 2, {})
        assert h1 != h2

    def test_seed_excluded_from_extra_params(self):
        # seed in extra_params should be popped, not affect hash
        h1 = self.gen._compute_params_hash("model", "p", 1, 42, {"seed": 99, "k": "v"})
        h2 = self.gen._compute_params_hash("model", "p", 1, 42, {"seed": 100, "k": "v"})
        assert h1 == h2

    def test_images_included_in_hash(self):
        h1 = self.gen._compute_params_hash("model", "p", 1, 42, {})
        h2 = self.gen._compute_params_hash("model", "p", 1, 42, {},
                                            images_base64=["data:image/png;base64,abc123"])
        assert h1 != h2

    def test_compact_json_serialization(self):
        # Verify that the hash uses compact JSON (no spaces)
        h_ordered_1 = self.gen._compute_params_hash("m", "p", 1, 0, {"a": 1, "b": 2})
        h_ordered_2 = self.gen._compute_params_hash("m", "p", 1, 0, {"b": 2, "a": 1})
        # sort_keys=True should make these equal regardless of dict ordering
        assert h_ordered_1 == h_ordered_2

    def test_none_extra_params(self):
        # Should not crash with None extra_params
        h = self.gen._compute_params_hash("model", "p", 1, 42, None)
        assert isinstance(h, str)
        assert len(h) == 32  # MD5 hex digest


# ──────────────────────────────────────────────────────────────────────────────
# get_adapter
# ──────────────────────────────────────────────────────────────────────────────

class TestGetAdapter:

    def setup_method(self):
        self.gen = IndependentGenerator()
        # Reset round-robin counters
        IndependentGenerator._endpoint_index.clear()

    def _mock_provider(self, name="test"):
        p = MagicMock()
        p.name = name
        p.base_url = "https://api.test.com"
        p.api_key = "sk-test"
        p.access_key = "AK"
        p.secret_key = "SK"
        return p

    @patch.object(_ig_mod, "config_manager")
    def test_priority_mode(self, mock_cm):
        provider = self._mock_provider()
        mock_cm.get_node_settings.return_value = {"auto_endpoint_mode": "priority"}
        mock_cm.get_best_endpoint.return_value = {
            "provider": provider,
            "config": {"endpoint": "/v1/gen"},
            "endpoint_config": {"api_format": "openai"},
        }
        adapter = self.gen.get_adapter("model_a", "text2img")
        assert adapter is not None
        mock_cm.get_best_endpoint.assert_called_once_with("model_a", "text2img")

    @patch.object(_ig_mod, "config_manager")
    def test_round_robin_mode(self, mock_cm):
        provider = self._mock_provider()
        mock_cm.get_node_settings.return_value = {"auto_endpoint_mode": "round_robin"}
        mock_cm.get_api_endpoints.return_value = [{"ep1": {}}, {"ep2": {}}]
        mock_cm.get_endpoint_by_index.return_value = {
            "provider": provider,
            "config": {"endpoint": "/v1/gen"},
            "endpoint_config": {"api_format": "openai"},
        }

        # First call: index 0
        self.gen.get_adapter("model_a", "text2img")
        mock_cm.get_endpoint_by_index.assert_called_with("model_a", 0, "text2img")

        # Second call: index 1
        self.gen.get_adapter("model_a", "text2img")
        mock_cm.get_endpoint_by_index.assert_called_with("model_a", 1, "text2img")

    @patch.object(_ig_mod, "config_manager")
    def test_no_endpoints_returns_none(self, mock_cm):
        mock_cm.get_node_settings.return_value = {"auto_endpoint_mode": "round_robin"}
        mock_cm.get_api_endpoints.return_value = []
        result = self.gen.get_adapter("model_x", "text2img")
        assert result is None

    @patch.object(_ig_mod, "config_manager")
    def test_volcengine_dispatch(self, mock_cm):
        provider = self._mock_provider()
        mock_cm.get_node_settings.return_value = {"auto_endpoint_mode": "priority"}
        mock_cm.get_best_endpoint.return_value = {
            "provider": provider,
            "config": {"endpoint": "/"},
            "endpoint_config": {"api_format": "volcengine", "req_key": "jimeng_t2i"},
        }
        adapter = self.gen.get_adapter("model_a", "text2img")
        _volc_mod = importlib.import_module(f"{_pkg}.adapters.volcengine")
        assert isinstance(adapter, _volc_mod.VolcengineAdapter)

    @patch.object(_ig_mod, "config_manager")
    def test_manual_endpoint_override(self, mock_cm):
        provider = self._mock_provider()
        mock_cm.get_endpoint_by_name.return_value = {
            "provider": provider,
            "config": {"endpoint": "/v1/gen"},
            "endpoint_config": {"api_format": "openai"},
        }
        adapter = self.gen.get_adapter("model_a", "text2img", endpoint_override="my_ep")
        mock_cm.get_endpoint_by_name.assert_called_once_with("model_a", "my_ep", "text2img")
        assert adapter is not None


class TestExecuteWithFailover:

    def setup_method(self):
        self.gen = IndependentGenerator()

    def _mock_provider(self, name="test"):
        p = MagicMock()
        p.name = name
        p.base_url = "https://api.test.com"
        p.api_key = "sk-test"
        p.access_key = "AK"
        p.secret_key = "SK"
        return p

    @patch.object(_ig_mod, "config_manager")
    @patch.object(_volc_mod, "VolcengineAdapter")
    @patch.object(_ig_mod, "GenericAPIAdapter")
    def test_failover_uses_volcengine_adapter_for_volcengine_alternative(
        self,
        mock_generic_adapter,
        mock_volcengine_adapter,
        mock_cm,
    ):
        primary = Mock()
        primary.provider = {"name": "primary"}
        primary.execute.return_value = APIResponse(
            success=False,
            error_message="primary failed",
        )

        fallback = Mock()
        fallback.execute.return_value = APIResponse(success=True, images=[b"ok"])
        mock_volcengine_adapter.return_value = fallback

        mock_cm.get_settings.return_value = {"auto_failover": True}
        mock_cm.get_alternative_endpoints.return_value = [
            {
                "provider": self._mock_provider("fallback"),
                "endpoint_config": {"api_format": "volcengine", "req_key": "jimeng"},
                "config": {"endpoint": "/"},
            }
        ]

        with patch.object(self.gen, "get_adapter", return_value=primary):
            result = self.gen.execute_with_failover(
                "model_a",
                {"prompt": "cat"},
                "text2img",
            )

        assert result.success is True
        mock_volcengine_adapter.assert_called_once()
        mock_generic_adapter.assert_not_called()

    @patch.object(_ig_mod, "config_manager")
    def test_endpoint_override_disables_failover(self, mock_cm):
        primary = Mock()
        primary.provider = {"name": "primary"}
        primary.execute.return_value = APIResponse(
            success=False,
            error_message="primary failed",
        )

        mock_cm.get_settings.return_value = {"auto_failover": True}

        with patch.object(self.gen, "get_adapter", return_value=primary):
            result = self.gen.execute_with_failover(
                "model_a",
                {"prompt": "cat"},
                "text2img",
                endpoint_override="manual",
            )

        assert result.success is False
        assert result.error_message == "All providers failed"
        mock_cm.get_alternative_endpoints.assert_not_called()


class TestGenerate:

    def setup_method(self):
        self.gen = IndependentGenerator()

    @staticmethod
    def _png_bytes(color=(255, 0, 0)):
        buf = BytesIO()
        Image.new("RGB", (4, 4), color).save(buf, format="PNG")
        return buf.getvalue()

    def test_generate_reuses_shared_image_payload_and_increments_seed(self):
        png_bytes = self._png_bytes()
        image_b64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
        seen_seeds = []
        seen_upload_files = []
        callback_events = []

        def execute_side_effect(model, params, mode, endpoint_override):
            seen_seeds.append(params["seed"])
            seen_upload_files.append(params.get("_upload_files"))
            assert mode == "img2img"
            return APIResponse(success=True, images=[png_bytes])

        async def on_batch_complete(batch_idx, batch_count, previews):
            callback_events.append((batch_idx, batch_count, previews))

        with patch.object(self.gen, "execute_with_failover", side_effect=execute_side_effect):
            with patch.object(
                self.gen,
                "_save_single_image",
                side_effect=lambda pil_img, model, params, batch_idx: {
                    "filename": f"{params['seed']}.png",
                    "subfolder": "",
                    "type": "output",
                },
            ):
                result = asyncio.run(
                    self.gen.generate(
                        "model_a",
                        "prompt",
                        seed=10,
                        batch_count=2,
                        images_base64=[image_b64],
                        on_batch_complete=on_batch_complete,
                    )
                )

        assert result["success"] is True
        assert len(result["preview_images"]) == 2
        assert sorted(seen_seeds) == [10, 11]
        assert len(seen_upload_files) == 2
        assert seen_upload_files[0] is seen_upload_files[1]
        assert len(callback_events) == 2
        assert result["params_hash"]

    def test_generate_reports_failed_batches(self):
        with patch.object(
            self.gen,
            "execute_with_failover",
            return_value=APIResponse(success=False, error_message="no provider"),
        ):
            result = asyncio.run(
                self.gen.generate(
                    "model_a",
                    "prompt",
                    seed=1,
                    batch_count=2,
                )
            )

        assert result["success"] is False
        assert "Batch 1 failed: no provider" in result["error"]
        assert "Batch 2 failed: no provider" in result["error"]
