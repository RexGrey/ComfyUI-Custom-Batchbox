import importlib.util
import json
import os
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NODES_PATH = PROJECT_ROOT / "nodes.py"


class FakeTensor:
    def __init__(self, shape=(1, 4, 4, 3)):
        self.shape = shape

    def __getitem__(self, key):
        if isinstance(key, int):
            if key < 0 or key >= self.shape[0]:
                raise IndexError
            return FakeTensor(shape=(1,) + tuple(self.shape[1:]))
        return self

    def unsqueeze(self, _dim):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return FakeNDArray()


class FakeNDArray:
    def astype(self, _dtype):
        return self

    def __mul__(self, _other):
        return self

    def __truediv__(self, _other):
        return self


class FakePILImage:
    size = (4, 4)

    def save(self, fp, format=None):
        if hasattr(fp, "write"):
            fp.write(b"fake-image-bytes")

    def resize(self, _size, _resample=None):
        return self


class FakeImageBatch:
    shape = (1, 4, 4, 3)

    def __getitem__(self, _idx):
        return FakeTensor()


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
    torch_mod.from_numpy = lambda _arr: FakeTensor()
    torch_mod.stack = lambda tensors, dim=0: FakeTensor(shape=(len(tensors), 4, 4, 3))
    torch_mod.cat = lambda tensors, dim=0: FakeTensor(shape=(sum(t.shape[0] for t in tensors), 4, 4, 3))
    sys.modules["torch"] = torch_mod

    np_mod = types.ModuleType("numpy")
    np_mod.array = lambda value: FakeNDArray()
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

    comfy_mod = types.ModuleType("comfy")
    comfy_utils_mod = types.ModuleType("comfy.utils")

    class ProgressBar:
        def __init__(self, _total):
            pass

        def update_absolute(self, _value, _total):
            pass

    comfy_utils_mod.ProgressBar = ProgressBar
    comfy_mod.utils = comfy_utils_mod
    sys.modules["comfy"] = comfy_mod
    sys.modules["comfy.utils"] = comfy_utils_mod

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
    image_utils_mod.prepare_for_comfyui = lambda image, preserve_alpha=True: (image, "PNG")
    image_utils_mod.pil_to_tensor_rgba = lambda image: image
    image_utils_mod.get_image_info = lambda image: {}
    image_utils_mod.apply_gaussian_blur_tensor = lambda image, sigma: image
    image_utils_mod.apply_masked_gaussian_blur_tensor = lambda image, mask, sigma: image
    image_utils_mod.apply_selection_boxes_blur = lambda image, boxes: image
    image_utils_mod.apply_gaussian_blur = lambda image, sigma: image
    image_utils_mod.split_image_tiles = lambda image, tile_mode, overlap: [{"col": 0, "row": 0, "image": FakePILImage()}]
    image_utils_mod.merge_image_tiles = lambda *args, **kwargs: FakePILImage()
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
    def test_queue_prompt_bypass_returns_cached_images_for_dynamic_image_node(self):
        nodes_mod = _load_nodes_module()
        node = nodes_mod.DynamicImageGenerationNode()
        image = nodes_mod.torch.Tensor()

        node._load_persisted_images = Mock(
            return_value=(image, image, [{"filename": "cached.png", "subfolder": "", "type": "output"}])
        )
        node.process_batch = Mock()

        result = node.generate(
            "model-a",
            "prompt-a",
            1,
            seed=123,
            extra_params='{"style":"cinematic"}',
            _last_images=json.dumps([{"filename": "cached.png", "subfolder": "", "type": "output"}]),
            _cached_hash="stale-hash",
            _bypass_queue_prompt="true",
            _selected_image_index=0,
            _all_images_connected="true",
        )

        node.process_batch.assert_not_called()
        self.assertEqual(result["result"][2], "Loaded from cache (no API call)")

    def test_queue_prompt_bypass_returns_cached_images_for_blur_node(self):
        nodes_mod = _load_nodes_module()
        node = nodes_mod.GaussianBlurUpscaleNode()
        image = nodes_mod.torch.Tensor()

        nodes_mod.save_preview_images = Mock(
            return_value=[{"filename": "blur_input.png", "subfolder": "", "type": "output"}]
        )
        nodes_mod.tensor2pil = Mock(return_value=[FakePILImage()])
        node._get_upscale_model = Mock(return_value=("upscale-model", ""))
        node._load_persisted_images = Mock(
            return_value=(image, image, [{"filename": "cached.png", "subfolder": "", "type": "output"}])
        )
        node.process_batch = Mock()

        result = node.upscale(
            "重 (σ6-10)",
            "直出",
            image1=image,
            custom_sigma=0.0,
            style_prompt="new style",
            batch_count=1,
            seed=123,
            aspect_ratio="1:1",
            extra_params="{}",
            _last_images=json.dumps([{"filename": "cached.png", "subfolder": "", "type": "output"}]),
            _cached_hash="stale-hash",
            _bypass_queue_prompt="true",
            _selected_image_index=0,
            _all_images_connected="true",
        )

        node.process_batch.assert_not_called()
        self.assertEqual(result["result"][3], "Loaded from cache")

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
                    "blur_mask": "",
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
                    "blur_mask": "",
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

    def test_load_persisted_images_rejects_path_traversal(self):
        nodes_mod = _load_nodes_module()
        node = nodes_mod.DynamicImageGenerationNode()

        with patch.object(nodes_mod.os.path, "exists", side_effect=lambda path: path == "/safe/output/ok.png"):
            with patch.object(nodes_mod.Image, "open", return_value=FakePILImage()) as image_open:
                with patch.object(nodes_mod.folder_paths, "get_output_directory", return_value="/safe/output"):
                    selected, all_images, previews = node._load_persisted_images(
                        json.dumps([{"filename": "../secret.png", "subfolder": "", "type": "output"}]),
                        selected_index=0,
                        load_all=False,
                    )

        self.assertIsNone(selected)
        self.assertIsNone(all_images)
        self.assertEqual(previews, [])
        image_open.assert_not_called()




if __name__ == "__main__":
    unittest.main()
