"""
Tests for API routes registered in __init__.py.
"""

import json
import asyncio
import base64
import sys
import uuid
import importlib.util
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, MagicMock, AsyncMock

from PIL import Image

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INIT_PATH = PROJECT_ROOT / "__init__.py"


class FakeRoutes:
    def __init__(self):
        self.handlers = {}

    def get(self, path):
        def decorator(func):
            self.handlers[("GET", path)] = func
            return func

        return decorator

    def post(self, path):
        def decorator(func):
            self.handlers[("POST", path)] = func
            return func

        return decorator


class DummyLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyRequest:
    def __init__(self, query=None, match_info=None, json_data=None, body_chunks=None):
        self.query = query or {}
        self.match_info = match_info or {}
        self.rel_url = SimpleNamespace(query=self.query)
        self._json_data = json_data
        self.content = SimpleNamespace(iter_any=self._iter_any(body_chunks or []))

    async def json(self):
        return self._json_data

    @staticmethod
    def _iter_any(chunks):
        async def iterator():
            for chunk in chunks:
                yield chunk

        return iterator


def _response_json(response):
    return json.loads(response.text)


def _chunked_request(payload, split_at=24):
    raw = json.dumps(payload).encode("utf-8")
    chunks = [raw[i:i + split_at] for i in range(0, len(raw), split_at)]
    return DummyRequest(body_chunks=chunks)


def _png_base64(color=(255, 0, 0)):
    buf = BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _build_fake_server():
    routes = FakeRoutes()
    prompt_server = SimpleNamespace(
        routes=routes,
        app=SimpleNamespace(_client_max_size=1024),
        send_sync=Mock(),
        prompt_queue=SimpleNamespace(history={}, mutex=DummyLock()),
    )
    server_module = ModuleType("server")
    server_module.PromptServer = SimpleNamespace(instance=prompt_server)
    return server_module, prompt_server, routes


def _build_fake_aiohttp():
    aiohttp_module = ModuleType("aiohttp")
    web_module = ModuleType("aiohttp.web")

    def json_response(data, status=200):
        return SimpleNamespace(status=status, text=json.dumps(data))

    web_module.json_response = json_response
    aiohttp_module.web = web_module
    return aiohttp_module, web_module


def _build_nodes_module(module_name):
    nodes_module = ModuleType(f"{module_name}.nodes")
    dummy_cls = type("DummyNode", (), {})
    nodes_module.NanoBananaPro = dummy_cls
    nodes_module.DynamicImageGenerationNode = dummy_cls
    nodes_module.DynamicTextGenerationNode = dummy_cls
    nodes_module.DynamicVideoGenerationNode = dummy_cls
    nodes_module.DynamicAudioGenerationNode = dummy_cls
    nodes_module.DynamicImageEditorNode = dummy_cls
    nodes_module.GaussianBlurUpscaleNode = dummy_cls
    nodes_module.create_dynamic_node = Mock(
        return_value=("DynamicAlias", "Dynamic Alias", dummy_cls)
    )
    return nodes_module


def _build_config_manager():
    provider = SimpleNamespace(
        name="provider-a",
        display_name="Provider A",
        base_url="https://api.test",
        api_key="secret",
        rate_limit=60,
    )
    config_manager = MagicMock()
    config_manager.get_models.return_value = ["model-a"]
    config_manager.get_raw_config.return_value = {
        "models": {
            "model-a": {
                "display_name": "Model A",
                "category": "image",
                "description": "test model",
                "api_endpoints": [{"provider": "provider-a", "priority": 3}],
            }
        }
    }
    config_manager.get_model_config.return_value = {
        "display_name": "Model A",
        "category": "image",
        "description": "test model",
        "show_seed_widget": False,
        "api_endpoints": [{"provider": "provider-a", "priority": 3}],
    }
    config_manager.get_parameter_schema.return_value = {"prompt": {"type": "string"}}
    config_manager.get_parameter_schema_flat.return_value = {"prompt": "string"}
    config_manager.get_providers.return_value = ["provider-a"]
    config_manager.get_provider_config.return_value = provider
    config_manager.get_categories.return_value = ["image", "video"]
    config_manager.force_reload.return_value = True
    config_manager.get_config_mtime.return_value = 123.45
    config_manager.get_save_settings.return_value = {"enabled": True}
    config_manager.get_node_settings.return_value = {"default_width": 420}
    config_manager.get_model_order.return_value = ["model-a"]
    config_manager.get_style_presets.return_value = {"cinematic": "high contrast"}
    return config_manager


def _build_account_module(module_name):
    account_instance = Mock()
    account_instance.get_status.return_value = {
        "logged_in": True,
        "nickname": "Alice",
        "credits": 42,
    }
    account_instance.login.return_value = {"success": True}
    account_instance.logout.return_value = {"status": "logged_out"}
    account_instance.redeem_credits.return_value = {"success": True, "credits": 99}
    account_instance.price_table = [{"modelName": "Model A"}]

    account_module = ModuleType(f"{module_name}.account")

    class AccountProxy:
        @classmethod
        def get_instance(cls):
            return account_instance

    account_module.Account = AccountProxy
    return account_module, account_instance


@pytest.fixture
def api_module(monkeypatch):
    module_name = f"batchbox_api_testpkg_{uuid.uuid4().hex}"
    server_module, prompt_server, routes = _build_fake_server()
    aiohttp_module, web_module = _build_fake_aiohttp()
    config_manager = _build_config_manager()
    account_module, account_instance = _build_account_module(module_name)

    config_module = ModuleType(f"{module_name}.config_manager")
    config_module.config_manager = config_manager

    nodes_module = _build_nodes_module(module_name)

    monkeypatch.setitem(sys.modules, "server", server_module)
    monkeypatch.setitem(sys.modules, "aiohttp", aiohttp_module)
    monkeypatch.setitem(sys.modules, "aiohttp.web", web_module)
    monkeypatch.setitem(sys.modules, f"{module_name}.nodes", nodes_module)
    monkeypatch.setitem(sys.modules, f"{module_name}.config_manager", config_module)
    monkeypatch.setitem(sys.modules, f"{module_name}.account", account_module)

    spec = importlib.util.spec_from_file_location(
        module_name,
        INIT_PATH,
        submodule_search_locations=[str(PROJECT_ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    yield SimpleNamespace(
        module=module,
        routes=routes.handlers,
        prompt_server=prompt_server,
        config_manager=config_manager,
        account=account_instance,
        module_name=module_name,
    )

    sys.modules.pop(module_name, None)
    sys.modules.pop(f"{module_name}.nodes", None)
    sys.modules.pop(f"{module_name}.config_manager", None)
    sys.modules.pop(f"{module_name}.account", None)


class TestRouteRegistration:
    def test_import_registers_key_routes_and_increases_body_limit(self, api_module):
        assert api_module.prompt_server.app._client_max_size == 500 * 1024 * 1024
        assert ("GET", "/api/batchbox/models") in api_module.routes
        assert ("GET", "/api/batchbox/schema/{model_name}") in api_module.routes
        assert ("POST", "/api/batchbox/config") in api_module.routes
        assert ("GET", "/api/batchbox/account/status") in api_module.routes


class TestConfigRoutes:
    def test_get_models_returns_model_metadata(self, api_module):
        handler = api_module.routes[("GET", "/api/batchbox/models")]

        response = asyncio.run(handler(DummyRequest()))

        payload = _response_json(response)
        assert response.status == 200
        assert payload["models"] == [
            {
                "name": "model-a",
                "display_name": "Model A",
                "category": "image",
                "description": "test model",
            }
        ]

    def test_get_model_schema_builds_defaults_and_endpoint_options(self, api_module):
        handler = api_module.routes[("GET", "/api/batchbox/schema/{model_name}")]

        response = asyncio.run(handler(DummyRequest(match_info={"model_name": "model-a"})))

        payload = _response_json(response)
        assert response.status == 200
        assert payload["model"] == "model-a"
        assert payload["schema"] == {"prompt": {"type": "string"}}
        assert payload["flat_schema"] == {"prompt": "string"}
        assert payload["max_image_inputs"] == 9
        assert payload["show_seed_widget"] is False
        assert payload["endpoint_options"] == [
            {"name": "provider-a", "provider": "provider-a", "priority": 3}
        ]

    def test_get_model_schema_returns_404_for_unknown_model(self, api_module):
        api_module.config_manager.get_parameter_schema.return_value = None
        handler = api_module.routes[("GET", "/api/batchbox/schema/{model_name}")]

        response = asyncio.run(handler(DummyRequest(match_info={"model_name": "missing"})))

        payload = _response_json(response)
        assert response.status == 404
        assert payload["error"] == "Model 'missing' not found"

    def test_save_config_persists_and_reloads(self, api_module):
        handler = api_module.routes[("POST", "/api/batchbox/config")]
        request = DummyRequest(
            json_data={"providers": {"provider-a": {"api_key": "secret"}}, "models": {}}
        )

        response = asyncio.run(handler(request))

        payload = _response_json(response)
        assert response.status == 200
        assert payload == {"status": "success"}
        api_module.config_manager.save_providers.assert_called_once_with(
            {"provider-a": {"api_key": "secret"}}
        )
        api_module.config_manager.save_config_data.assert_called_once_with(
            {"providers": {"provider-a": {"api_key": "secret"}}, "models": {}}
        )
        api_module.config_manager.force_reload.assert_called_once()

    def test_reload_config_returns_success_and_mtime(self, api_module):
        handler = api_module.routes[("POST", "/api/batchbox/reload")]

        response = asyncio.run(handler(DummyRequest()))

        payload = _response_json(response)
        assert response.status == 200
        assert payload == {"success": True, "mtime": 123.45}


class TestAccountRoutes:
    def test_account_status_returns_singleton_status(self, api_module):
        handler = api_module.routes[("GET", "/api/batchbox/account/status")]

        response = asyncio.run(handler(DummyRequest()))

        payload = _response_json(response)
        assert response.status == 200
        assert payload == {"logged_in": True, "nickname": "Alice", "credits": 42}

    def test_account_redeem_requires_code(self, api_module):
        handler = api_module.routes[("POST", "/api/batchbox/account/redeem")]

        response = asyncio.run(handler(DummyRequest(json_data={"code": "   "})))

        payload = _response_json(response)
        assert response.status == 400
        assert payload == {"error": "Code is required"}


class TestGenerationRoutes:
    def test_blur_preview_uses_image_utils_helper(self, api_module, monkeypatch):
        image_utils_module = ModuleType(f"{api_module.module_name}.image_utils")
        image_utils_module.generate_blur_preview_base64 = Mock(return_value="data:image/png;base64,preview")
        monkeypatch.setitem(
            sys.modules,
            f"{api_module.module_name}.image_utils",
            image_utils_module,
        )

        handler = api_module.routes[("POST", "/api/batchbox/blur-preview")]
        request = DummyRequest(
            json_data={"image_base64": "data:image/png;base64,abc", "sigma": "3.5"}
        )

        response = asyncio.run(handler(request))

        payload = _response_json(response)
        assert response.status == 200
        assert payload == {"preview_base64": "data:image/png;base64,preview"}
        image_utils_module.generate_blur_preview_base64.assert_called_once_with(
            "data:image/png;base64,abc",
            3.5,
        )

    def test_generate_independent_reads_chunked_body_and_writes_history(self, api_module, monkeypatch):
        generator_instance = Mock()

        async def fake_generate(**kwargs):
            await kwargs["on_batch_complete"](0, 2, [{"filename": "preview-1.png", "subfolder": "", "type": "output"}])
            await kwargs["on_batch_complete"](1, 2, [{"filename": "preview-2.png", "subfolder": "", "type": "output"}])
            return {
                "success": True,
                "preview_images": [
                    {"filename": "preview-1.png", "subfolder": "", "type": "output"},
                    {"filename": "preview-2.png", "subfolder": "", "type": "output"},
                ],
                "params_hash": "hash-123",
            }

        generator_instance.generate = AsyncMock(side_effect=fake_generate)
        independent_module = ModuleType(f"{api_module.module_name}.independent_generator")
        independent_module.IndependentGenerator = Mock(return_value=generator_instance)
        monkeypatch.setitem(
            sys.modules,
            f"{api_module.module_name}.independent_generator",
            independent_module,
        )
        api_module.prompt_server.send_sync.reset_mock()

        handler = api_module.routes[("POST", "/api/batchbox/generate-independent")]
        request = _chunked_request(
            {
                "model": "model-a",
                "prompt": "draw a cat",
                "seed": 42,
                "batch_count": 2,
                "extra_params": {"steps": 20},
                "images_base64": ["data:image/png;base64,abc"],
                "endpoint_override": "manual-ep",
                "node_id": "node-1",
                "generation_token": "token-1",
            }
        )

        response = asyncio.run(handler(request))

        payload = _response_json(response)
        assert response.status == 200
        assert payload["success"] is True
        generator_instance.generate.assert_awaited_once()
        call_kwargs = generator_instance.generate.await_args.kwargs
        assert call_kwargs["model"] == "model-a"
        assert call_kwargs["prompt"] == "draw a cat"
        assert call_kwargs["seed"] == 42
        assert call_kwargs["batch_count"] == 2
        assert call_kwargs["endpoint_override"] == "manual-ep"

        send_calls = api_module.prompt_server.send_sync.call_args_list
        assert send_calls[0].args[0] == "batchbox:progress"
        assert send_calls[1].args[0] == "batchbox:progress"
        assert send_calls[2].args[0] == "executed"
        executed_payload = send_calls[2].args[1]
        assert executed_payload["node"] == "node-1"
        assert executed_payload["prompt_id"].startswith("independent_")
        assert executed_payload["output"]["_cached_hash"] == ["hash-123"]

        assert len(api_module.prompt_server.prompt_queue.history) == 1
        history_entry = next(iter(api_module.prompt_server.prompt_queue.history.values()))
        assert history_entry["outputs"]["node-1"]["images"][0]["filename"] == "preview-1.png"
        assert history_entry["status"]["completed"] is True

    def test_generate_blur_upscale_reads_chunked_body_and_records_history(self, api_module, monkeypatch):
        api_module.config_manager.get_upscale_settings.return_value = {
            "model": "upscale-model",
            "endpoint": "saved-ep",
            "default_params": {"steps": 30},
        }

        image_utils_module = ModuleType(f"{api_module.module_name}.image_utils")
        image_utils_module.apply_gaussian_blur = Mock(side_effect=lambda image, sigma: image)
        image_utils_module.generate_blur_preview_base64 = Mock(return_value="unused")
        monkeypatch.setitem(
            sys.modules,
            f"{api_module.module_name}.image_utils",
            image_utils_module,
        )

        generator_instance = Mock()

        async def fake_generate(**kwargs):
            await kwargs["on_batch_complete"](0, 1, [{"filename": "blur-upscale.png", "subfolder": "", "type": "output"}])
            return {
                "success": True,
                "preview_images": [{"filename": "blur-upscale.png", "subfolder": "", "type": "output"}],
                "params_hash": "blur-hash",
            }

        generator_instance.generate = AsyncMock(side_effect=fake_generate)
        independent_module = ModuleType(f"{api_module.module_name}.independent_generator")
        independent_module.IndependentGenerator = Mock(return_value=generator_instance)
        monkeypatch.setitem(
            sys.modules,
            f"{api_module.module_name}.independent_generator",
            independent_module,
        )
        api_module.prompt_server.send_sync.reset_mock()
        api_module.prompt_server.prompt_queue.history.clear()

        handler = api_module.routes[("POST", "/api/batchbox/generate-blur-upscale")]
        request = _chunked_request(
            {
                "node_id": "node-blur",
                "generation_token": "token-blur",
                "blur_intensity": "中 (σ3-6)",
                "repair_mode": "风格",
                "style_prompt": "胶片感",
                "seed": 7,
                "batch_count": 1,
                "image_base64": "data:image/png;base64," + _png_base64(),
                "endpoint_override": "manual-ep",
            }
        )

        response = asyncio.run(handler(request))

        payload = _response_json(response)
        assert response.status == 200
        assert payload["success"] is True
        image_utils_module.apply_gaussian_blur.assert_called_once()

        call_kwargs = generator_instance.generate.await_args.kwargs
        assert call_kwargs["model"] == "upscale-model"
        assert call_kwargs["seed"] == 7
        assert call_kwargs["batch_count"] == 1
        assert call_kwargs["extra_params"] == {"steps": 30}
        assert call_kwargs["endpoint_override"] == "manual-ep"
        assert call_kwargs["prompt"].endswith("胶片感")
        assert len(call_kwargs["images_base64"]) == 1

        send_calls = api_module.prompt_server.send_sync.call_args_list
        assert send_calls[0].args[0] == "batchbox:progress"
        assert send_calls[1].args[0] == "executed"
        executed_payload = send_calls[1].args[1]
        assert executed_payload["node"] == "node-blur"
        assert executed_payload["prompt_id"].startswith("blur_upscale_")

        history_entry = next(iter(api_module.prompt_server.prompt_queue.history.values()))
        assert history_entry["outputs"]["node-blur"]["_cached_hash"] == ["blur-hash"]
        assert history_entry["prompt"][2]["node-blur"]["class_type"] == "GaussianBlurUpscale"
