# 密钥管理检查清单

## 文件级保护
- [ ] `secrets.yaml` 在 `.gitignore` 中
- [ ] `.auth.json` 在 `.gitignore` 中
- [ ] `*_cache.db` 在 `.gitignore` 中 (gcs/oss/gemini_files)
- [ ] Service Account JSON 在 `.gitignore` 中
- [ ] `gateway_client.json` 在 `.gitignore` 中

## 密钥存储
- [ ] `config_manager.py` 使用 AES-256-GCM 加密存储 (`crypto_utils.py`)
- [ ] `BATCHBOX_KEY` 通过环境变量注入，不硬编码在代码中
- [ ] `Start_Client.bat` 中 `BATCHBOX_KEY` 只在运行时设置，不持久化
- [ ] 加密密钥 (`secrets.yaml`) 与解密密钥 (`BATCHBOX_KEY`) 分离存储

## 日志脱敏
- [ ] API Key 在日志中只打印尾号 (≤8 字符)，检查 `adapters/generic.py`
- [ ] Service Account token 在日志中只打印尾号，检查 `vertex_sa_auth.py`
- [ ] Files API key 在日志中只打印前 8 字符，检查 `gemini_files_cache.py`
- [ ] Account token 不在日志中出现，检查 `account/`

## 前端隔离
- [ ] `/api/batchbox/account/status` 不返回内部 Token
- [ ] `/api/batchbox/config` 不返回解密后的 API Key
- [ ] 前端 JS 不存储密钥到 localStorage/sessionStorage
- [ ] WebSocket 登录回调 (`55441`) 只接收不发送 Token

## Git 历史
- [ ] `git log --all -p -- secrets.yaml` 无明文密钥
- [ ] `git log --all -p -- .auth.json` 无明文 token
- [ ] 运行 `gitleaks detect` 无告警（如已安装）
