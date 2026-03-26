#!/usr/bin/env python
"""
管理员工具：加密 secrets.yaml → secrets.yaml.enc

用法:
  python encrypt_secrets.py              # 加密（自动生成密钥如不存在）
  python encrypt_secrets.py --verify     # 验证 .enc 文件可正常解密

密钥文件: .secrets_key（同目录，不要同步到 Z 盘）
加密文件: secrets.yaml.enc（同步到 Z 盘）
"""

import os
import sys

# Add parent directory to path so we can import crypto_utils
sys.path.insert(0, os.path.dirname(__file__))

from crypto_utils import generate_key, encrypt_secrets_file, decrypt_secrets_file


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SECRETS_PATH = os.path.join(SCRIPT_DIR, "secrets.yaml")
KEY_PATH = os.path.join(SCRIPT_DIR, ".secrets_key")
ENC_PATH = SECRETS_PATH + ".enc"


def load_or_create_key() -> bytes:
    """Load existing key or generate a new one."""
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            key = f.read().strip()
        print(f"[✓] 已读取密钥文件: {KEY_PATH}")
        return key

    key = generate_key()
    with open(KEY_PATH, "wb") as f:
        f.write(key)
    print(f"[✓] 已生成新密钥并保存到: {KEY_PATH}")
    print(f"[!] 请将以下字符串复制到 ComfyUI 启动脚本的 BATCHBOX_KEY 环境变量中:")
    print(f"    set BATCHBOX_KEY={key.decode('ascii')}")
    return key


def cmd_encrypt():
    if not os.path.exists(SECRETS_PATH):
        print(f"[✗] 找不到 {SECRETS_PATH}")
        print(f"    请确保在插件目录下运行此脚本")
        sys.exit(1)

    key = load_or_create_key()
    enc_path = encrypt_secrets_file(SECRETS_PATH, key)

    enc_size = os.path.getsize(enc_path)
    orig_size = os.path.getsize(SECRETS_PATH)
    print(f"[✓] 加密完成: {enc_path}")
    print(f"    原文件: {orig_size:,} 字节 → 加密后: {enc_size:,} 字节")
    print()
    print(f"[同步到 Z 盘时请排除明文文件]:")
    print(f"    robocopy ... /XF secrets.yaml .secrets_key .auth.json")
    print()
    print(f"[启动脚本设置]:")
    print(f"    set BATCHBOX_KEY={key.decode('ascii')}")


def cmd_verify():
    if not os.path.exists(ENC_PATH):
        print(f"[✗] 找不到加密文件: {ENC_PATH}")
        print(f"    请先运行: python encrypt_secrets.py")
        sys.exit(1)

    if not os.path.exists(KEY_PATH):
        print(f"[✗] 找不到密钥文件: {KEY_PATH}")
        sys.exit(1)

    with open(KEY_PATH, "rb") as f:
        key = f.read().strip()

    try:
        content = decrypt_secrets_file(ENC_PATH, key)
        # Count providers as a sanity check
        import yaml
        data = yaml.safe_load(content) or {}
        providers = data.get("providers", {})
        print(f"[✓] 解密验证通过")
        print(f"    供应商数量: {len(providers)}")
        for name in providers:
            keys_count = len(providers[name].get("api_keys", []))
            sa_count = len(providers[name].get("service_account_files", []))
            has_single = bool(providers[name].get("api_key"))
            total = keys_count + sa_count + (1 if has_single else 0)
            print(f"    - {name}: {total} 个凭证")
    except Exception as e:
        print(f"[✗] 解密失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if "--verify" in sys.argv:
        cmd_verify()
    else:
        cmd_encrypt()
