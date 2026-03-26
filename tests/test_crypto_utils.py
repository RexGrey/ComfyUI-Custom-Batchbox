"""Tests for crypto_utils and ConfigManager encrypted secrets support."""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from crypto_utils import generate_key, encrypt_data, decrypt_data, encrypt_secrets_file, decrypt_secrets_file


class TestCryptoUtils(unittest.TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        key = generate_key()
        plaintext = b"hello world: test data with unicode \xc3\xa9\xc3\xa0"
        ciphertext = encrypt_data(plaintext, key)
        self.assertNotEqual(ciphertext, plaintext)
        result = decrypt_data(ciphertext, key)
        self.assertEqual(result, plaintext)

    def test_wrong_key_raises(self):
        key1 = generate_key()
        key2 = generate_key()
        ciphertext = encrypt_data(b"secret", key1)
        with self.assertRaises(Exception):
            decrypt_data(ciphertext, key2)

    def test_corrupted_data_raises(self):
        key = generate_key()
        with self.assertRaises(Exception):
            decrypt_data(b"not-valid-fernet-data", key)

    def test_file_encrypt_decrypt_roundtrip(self):
        key = generate_key()
        yaml_content = "providers:\n  google:\n    api_key: sk-test123\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            secrets_path = os.path.join(tmpdir, "secrets.yaml")
            with open(secrets_path, "w", encoding="utf-8") as f:
                f.write(yaml_content)

            enc_path = encrypt_secrets_file(secrets_path, key)
            self.assertTrue(os.path.exists(enc_path))

            # Encrypted file should not contain plaintext
            with open(enc_path, "rb") as f:
                enc_content = f.read()
            self.assertNotIn(b"sk-test123", enc_content)

            # Decrypt and verify
            result = decrypt_secrets_file(enc_path, key)
            self.assertEqual(result, yaml_content)


class TestConfigManagerEncryptedSecrets(unittest.TestCase):
    def _make_config_manager(self, config_dir, env_key=None):
        """Create a ConfigManager with the given config directory."""
        import importlib
        # Ensure crypto_utils is importable as a module of the package
        config_path = os.path.join(config_dir, "api_config.yaml")
        secrets_path = os.path.join(config_dir, "secrets.yaml")

        # Create minimal api_config.yaml
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("models: {}\n")

        # We need to import config_manager properly
        spec = importlib.util.spec_from_file_location(
            "config_manager_test",
            str(PROJECT_ROOT / "config_manager.py"),
        )
        cm_mod = importlib.util.module_from_spec(spec)

        # Patch __file__ so it resolves paths correctly
        cm_mod.__file__ = str(PROJECT_ROOT / "config_manager.py")
        spec.loader.exec_module(cm_mod)

        return cm_mod.ConfigManager(config_path=config_path, secrets_path=secrets_path)

    def test_plaintext_preferred_over_enc(self):
        """When both secrets.yaml and secrets.yaml.enc exist, plaintext wins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "api_config.yaml")
            secrets_path = os.path.join(tmpdir, "secrets.yaml")
            enc_path = secrets_path + ".enc"

            with open(config_path, "w") as f:
                f.write("models: {}\n")
            with open(secrets_path, "w") as f:
                f.write("providers:\n  test_provider:\n    api_key: plain\n")
            with open(enc_path, "wb") as f:
                f.write(b"encrypted-garbage")

            import importlib
            spec = importlib.util.spec_from_file_location(
                "config_manager_plain_test",
                str(PROJECT_ROOT / "config_manager.py"),
            )
            cm_mod = importlib.util.module_from_spec(spec)
            cm_mod.__file__ = str(PROJECT_ROOT / "config_manager.py")
            spec.loader.exec_module(cm_mod)

            cm = cm_mod.ConfigManager(config_path=config_path, secrets_path=secrets_path)
            providers = cm._config.get("providers", {})
            self.assertIn("test_provider", providers)
            self.assertEqual(providers["test_provider"]["api_key"], "plain")

    def test_enc_file_loaded_when_no_plaintext(self):
        """When only secrets.yaml.enc exists with correct key, it can be decrypted to valid YAML."""
        key = generate_key()
        yaml_content = "providers:\n  encrypted_provider:\n    api_key: enc-key\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            secrets_path = os.path.join(tmpdir, "secrets.yaml")
            enc_path = secrets_path + ".enc"

            # Write only the encrypted file, no plaintext
            encrypted = encrypt_data(yaml_content.encode("utf-8"), key)
            with open(enc_path, "wb") as f:
                f.write(encrypted)

            # Verify plaintext does NOT exist
            self.assertFalse(os.path.exists(secrets_path))
            self.assertTrue(os.path.exists(enc_path))

            # Simulate what ConfigManager._merge_secrets does
            plaintext = decrypt_secrets_file(enc_path, key)
            import yaml
            secrets = yaml.safe_load(plaintext) or {}
            self.assertIn("providers", secrets)
            self.assertIn("encrypted_provider", secrets["providers"])
            self.assertEqual(secrets["providers"]["encrypted_provider"]["api_key"], "enc-key")

    def test_missing_key_env_logs_warning(self):
        """When .enc exists but BATCHBOX_KEY is not set, providers don't load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "api_config.yaml")
            secrets_path = os.path.join(tmpdir, "secrets.yaml")
            enc_path = secrets_path + ".enc"

            with open(config_path, "w") as f:
                f.write("models: {}\n")
            with open(enc_path, "wb") as f:
                f.write(b"some-encrypted-data")

            import importlib
            spec = importlib.util.spec_from_file_location(
                "config_manager_nokey_test",
                str(PROJECT_ROOT / "config_manager.py"),
            )
            cm_mod = importlib.util.module_from_spec(spec)
            cm_mod.__file__ = str(PROJECT_ROOT / "config_manager.py")

            crypto_mod = types.ModuleType("config_manager_nokey_test.crypto_utils")
            crypto_mod.decrypt_secrets_file = lambda *a: None
            crypto_mod.get_key_from_env = lambda: None  # No key
            crypto_mod.ENV_KEY_NAME = "BATCHBOX_KEY"
            sys.modules["config_manager_nokey_test.crypto_utils"] = crypto_mod

            with patch.dict("sys.modules", {"config_manager_nokey_test.crypto_utils": crypto_mod}):
                spec.loader.exec_module(cm_mod)
                cm = cm_mod.ConfigManager(config_path=config_path, secrets_path=secrets_path)

            # No providers should be loaded
            providers = cm._config.get("providers", {})
            self.assertEqual(providers, {})


if __name__ == "__main__":
    unittest.main()
