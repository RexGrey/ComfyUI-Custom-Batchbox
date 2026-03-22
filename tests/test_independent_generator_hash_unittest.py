import importlib.util
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = PROJECT_ROOT / "independent_generator.py"


def _load_independent_generator_module():
    pkg_name = f"batchbox_independent_hash_testpkg_{uuid.uuid4().hex}"

    fake_pkg = types.ModuleType(pkg_name)
    fake_pkg.__path__ = [str(PROJECT_ROOT)]
    sys.modules[pkg_name] = fake_pkg

    adapters_pkg_name = f"{pkg_name}.adapters"
    fake_adapters_pkg = types.ModuleType(adapters_pkg_name)
    fake_adapters_pkg.__path__ = [str(PROJECT_ROOT / "adapters")]
    sys.modules[adapters_pkg_name] = fake_adapters_pkg

    folder_paths_mod = types.ModuleType("folder_paths")
    folder_paths_mod.get_temp_directory = lambda: "/tmp"
    sys.modules["folder_paths"] = folder_paths_mod

    pil_mod = types.ModuleType("PIL")
    image_mod = types.ModuleType("PIL.Image")
    image_mod.Image = object
    pil_mod.Image = image_mod
    sys.modules["PIL"] = pil_mod
    sys.modules["PIL.Image"] = image_mod

    config_mod = types.ModuleType(f"{pkg_name}.config_manager")
    config_mod.config_manager = MagicMock()
    sys.modules[f"{pkg_name}.config_manager"] = config_mod

    base_mod = types.ModuleType(f"{adapters_pkg_name}.base")

    class APIResponse:
        pass

    base_mod.APIResponse = APIResponse
    sys.modules[f"{adapters_pkg_name}.base"] = base_mod

    generic_mod = types.ModuleType(f"{adapters_pkg_name}.generic")
    generic_mod.GenericAPIAdapter = object
    sys.modules[f"{adapters_pkg_name}.generic"] = generic_mod

    spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.independent_generator",
        GENERATOR_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{pkg_name}.independent_generator"] = module
    spec.loader.exec_module(module)
    return module


class TestIndependentGeneratorHashSemantics(unittest.TestCase):
    def test_hash_extras_affect_params_hash(self):
        module = _load_independent_generator_module()
        gen = module.IndependentGenerator()

        h1 = gen._compute_params_hash(
            "model",
            "prompt",
            1,
            42,
            {"aspect_ratio": "1:1"},
            hash_extras={"endpoint_override": "A"},
        )
        h2 = gen._compute_params_hash(
            "model",
            "prompt",
            1,
            42,
            {"aspect_ratio": "1:1"},
            hash_extras={"endpoint_override": "B"},
        )

        self.assertNotEqual(h1, h2)

    def test_hash_images_base64_overrides_upload_images_for_hashing(self):
        module = _load_independent_generator_module()
        gen = module.IndependentGenerator()

        h1 = gen._compute_params_hash(
            "model",
            "prompt",
            1,
            42,
            {"aspect_ratio": "1:1"},
            images_base64=["blurred-image-a"],
            hash_images_base64=["original-image"],
        )
        h2 = gen._compute_params_hash(
            "model",
            "prompt",
            1,
            42,
            {"aspect_ratio": "1:1"},
            images_base64=["blurred-image-b"],
            hash_images_base64=["original-image"],
        )

        self.assertEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
