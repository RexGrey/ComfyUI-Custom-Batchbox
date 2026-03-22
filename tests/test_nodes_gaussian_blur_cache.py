import importlib.util
import json
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NODES_PATH = PROJECT_ROOT / "nodes.py"


class FakeTensor:
    def __init__(self, shape=(1, 4, 4, 3)):
        self.shape = shape

    def __getitem__(self, _key):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return [[[[0, 0, 0]]]]


class FakePILImage:
    def save(self, fp, format=None):
        if hasattr(fp, "write"):
            fp.write(b"fake-image-bytes")


def _load_nodes_module():
    pkg_name = f"batchbox_nodes_testpkg_{uuid.uuid4().hex}"

    fake_pkg = types.ModuleType(pkg_name)
    fake_pkg.__path__ = [str(PROJECT_ROOT)]
    sys.modules[pkg_name] = fake_pkg

    adapters_pkg_name = f"{pkg_name}.adapters"
    fake_adapters_pkg = types.ModuleType(adapters_pkg_name)
    fake_adapters_pkg.__path__ = [str(PROJECT_ROOT / "adapters")]
    sys.modules[adapters_pkg_name] = fake_adapters_pkg

    torch_mod = types.ModuleType("torch")
    torch_mod.Tensor = FakeTensor
    torch_mod.zeros = lambda *shape: FakeTensor(shape=shape)
    sys.modules["torch"] = torch_mod

    np_mod = types.ModuleType("numpy")
    np_mod.array = lambda value: value
    np_mod.clip = lambda value, *_args, **_kwargs: value
    np_mod.uint8 = "uint8"
    np_mod.float32 = "float32"
    sys.modules["numpy"] = np_mod

    requests_mod = types.ModuleType("requests")
    sys.modules["requests"] = requests_mod

    pil_mod = types.ModuleType("PIL")
    image_mod = types.ModuleType("PIL.Image")
    image_mod.Image = FakePILImage
    image_mod.fromarray = lambda _arr: FakePILImage()
    pil_mod.Image = image_mod
    sys.modules["PIL"] = pil_mod
    sys.modules["PIL.Image"] = image_mod

    folder_paths_mod = types.ModuleType("folder_paths")
    folder_paths_mod.get_temp_directory = lambda: "/tmp"
    folder_paths_mod.get_output_directory = lambda: "/tmp"
    folder_paths_mod.get_input_directory = lambda: "/tmp"
    sys.modules["folder_paths"] = folder_paths_mod

    base_mod = types.ModuleType(f"{adapters_pkg_name}.base")

    class APIResponse:
        pass

    base_mod.APIResponse = APIResponse
    sys.modules[f"{adapters_pkg_name}.base"] = base_mod

    generic_mod = types.ModuleType(f"{adapters_pkg_name}.generic")
    generic_mod.GenericAPIAdapter = object
    sys.modules[f"{adapters_pkg_name}.generic"] = generic_mod

    config_mod = types.ModuleType(f"{pkg_name}.config_manager")
    config_mod.config_manager = MagicMock()
    config_mod.config_manager.get_upscale_settings.return_value = {"default_params": {}}
    config_mod.config_manager.get_save_settings.return_value = {"enabled": False}
    sys.modules[f"{pkg_name}.config_manager"] = config_mod

    image_utils_mod = types.ModuleType(f"{pkg_name}.image_utils")
    image_utils_mod.prepare_for_comfyui = lambda image: image
    image_utils_mod.pil_to_tensor_rgba = lambda image: image
    image_utils_mod.get_image_info = lambda image: {}
    image_utils_mod.apply_gaussian_blur_tensor = lambda image, sigma: image
    image_utils_mod.detect_aspect_ratio = lambda width, height: f"{width}:{height}"
    sys.modules[f"{pkg_name}.image_utils"] = image_utils_mod

    save_settings_mod = types.ModuleType(f"{pkg_name}.save_settings")

    class SaveSettings:
        def __init__(self, _config):
            self.enabled = False

    save_settings_mod.SaveSettings = SaveSettings
    sys.modules[f"{pkg_name}.save_settings"] = save_settings_mod

    spec = importlib.util.spec_from_file_location(f"{pkg_name}.nodes", NODES_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{pkg_name}.nodes"] = module
    spec.loader.exec_module(module)
    return module


class TestGaussianBlurUpscaleCache(unittest.TestCase):
    def test_blur_setting_change_invalidates_cache_and_updates_hash(self):
        nodes_mod = _load_nodes_module()
        node = nodes_mod.GaussianBlurUpscaleNode()
        image = nodes_mod.torch.Tensor()

        nodes_mod.save_preview_images = Mock(
            side_effect=lambda _images, prefix="batchbox": [
                {"filename": f"{prefix}.png", "subfolder": "", "type": "temp"}
            ]
        )
        nodes_mod.tensor2pil = Mock(return_value=[FakePILImage()])

        node._get_upscale_model = Mock(return_value=("upscale-model", ""))
        node._load_persisted_images = Mock(return_value=(image, image, [{"filename": "cached.png", "subfolder": "", "type": "temp"}]))
        node.process_batch = Mock(return_value=(image, "Success", "", [FakePILImage()]))

        prompt = node._build_prompt("直出", "")
        old_hash = node._compute_params_hash(
            "upscale-model",
            prompt,
            1,
            {
                "extra_params": "{}",
                "seed": 123,
                "image": image,
                "_hash_extras": {
                    "blur_intensity": "轻 (σ1-3)",
                    "custom_sigma": 0.0,
                    "repair_mode": "直出",
                    "style_prompt": "",
                    "aspect_ratio": "1:1",
                },
            },
        )
        expected_new_hash = node._compute_params_hash(
            "upscale-model",
            prompt,
            1,
            {
                "extra_params": "{}",
                "seed": 123,
                "image": image,
                "_hash_extras": {
                    "blur_intensity": "重 (σ6-10)",
                    "custom_sigma": 0.0,
                    "repair_mode": "直出",
                    "style_prompt": "",
                    "aspect_ratio": "1:1",
                },
            },
        )

        result = node.upscale(
            "重 (σ6-10)",
            "直出",
            image1=image,
            custom_sigma=0.0,
            style_prompt="",
            batch_count=1,
            seed=123,
            aspect_ratio="1:1",
            extra_params="{}",
            _last_images=json.dumps([{"filename": "cached.png", "subfolder": "", "type": "temp"}]),
            _cached_hash=old_hash,
            _selected_image_index=0,
            _all_images_connected="true",
        )

        node.process_batch.assert_called_once()
        self.assertEqual(result["ui"]["_cached_hash"], [expected_new_hash])
        self.assertNotEqual(old_hash, expected_new_hash)


if __name__ == "__main__":
    unittest.main()
