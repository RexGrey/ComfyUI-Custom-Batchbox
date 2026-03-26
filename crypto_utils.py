"""
Fernet symmetric encryption utilities for secrets.yaml.

Usage:
  - Admin generates a key with generate_key()
  - Admin encrypts secrets.yaml with encrypt_data()
  - ConfigManager decrypts at runtime with decrypt_data()
  - The Fernet key is delivered via BATCHBOX_KEY environment variable
"""

import os
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("batchbox")

ENV_KEY_NAME = "BATCHBOX_KEY"


def generate_key() -> bytes:
    """Generate a new Fernet key (URL-safe base64, 32 bytes)."""
    return Fernet.generate_key()


def encrypt_data(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt plaintext bytes using a Fernet key."""
    return Fernet(key).encrypt(plaintext)


def decrypt_data(ciphertext: bytes, key: bytes) -> bytes:
    """Decrypt ciphertext bytes using a Fernet key.
    
    Raises:
        InvalidToken: If the key is wrong or the ciphertext is corrupted.
    """
    return Fernet(key).decrypt(ciphertext)


def get_key_from_env() -> bytes | None:
    """Read the Fernet key from the BATCHBOX_KEY environment variable.
    
    Returns the key as bytes, or None if not set.
    """
    raw = os.environ.get(ENV_KEY_NAME)
    if not raw:
        return None
    return raw.strip().encode("ascii")


def encrypt_secrets_file(secrets_path: str, key: bytes) -> str:
    """Encrypt a secrets.yaml file and write the .enc version.
    
    Args:
        secrets_path: Path to the plaintext secrets.yaml
        key: Fernet key bytes
        
    Returns:
        Path to the generated .enc file
    """
    with open(secrets_path, "r", encoding="utf-8") as f:
        plaintext = f.read()

    encrypted = encrypt_data(plaintext.encode("utf-8"), key)

    enc_path = secrets_path + ".enc"
    with open(enc_path, "wb") as f:
        f.write(encrypted)

    return enc_path


def decrypt_secrets_file(enc_path: str, key: bytes) -> str:
    """Decrypt a secrets.yaml.enc file and return the plaintext content.
    
    Args:
        enc_path: Path to the encrypted .enc file
        key: Fernet key bytes
        
    Returns:
        Decrypted YAML content as string
        
    Raises:
        FileNotFoundError: If .enc file doesn't exist
        InvalidToken: If key is wrong or file is corrupted
    """
    with open(enc_path, "rb") as f:
        ciphertext = f.read()

    return decrypt_data(ciphertext, key).decode("utf-8")
