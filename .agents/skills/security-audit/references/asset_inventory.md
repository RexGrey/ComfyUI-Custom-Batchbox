# BatchBox 资产清单

## 密钥类型

| 类型 | 存储位置 | 保护方式 |
|:-----|:---------|:---------|
| Google API Key | `secrets.yaml` 加密 | AES-256-GCM + `BATCHBOX_KEY` |
| Vertex AI SA JSON | `secrets.yaml` 加密 | AES-256-GCM + `BATCHBOX_KEY` |
| 即梦 AK/SK | `secrets.yaml` 加密 | AES-256-GCM + `BATCHBOX_KEY` |
| OSS AK/SK | `secrets.yaml` 加密 | AES-256-GCM + `BATCHBOX_KEY` |
| GCS SA JSON | `secrets.yaml` 加密 | AES-256-GCM + `BATCHBOX_KEY` |
| Account Token | `.auth.json` | 本地文件 + .gitignore |
| `BATCHBOX_KEY` | `Start_Client.bat` | 运行时环境变量 |

## 第三方 API

| API | 用途 | 调用方 |
|:----|:-----|:-------|
| Google Gemini | 图片生成 | `adapters/generic.py` |
| Vertex AI | 图片生成 | `adapters/generic.py` |
| 即梦 Jimeng | 图片生成 | `adapters/generic.py` |
| Google Cloud Storage | 图片上传 | `gcs_cache.py` |
| 阿里云 OSS | 图片上传 | `oss_cache.py` |
| Google Files API | 文件上传 | `gemini_files_cache.py` |
| Account API | 用户认证 | `account/` |

## 本地落盘文件

| 文件 | 类型 | .gitignore |
|:-----|:-----|:----------:|
| `secrets.yaml` | 加密配置 | ✅ |
| `.auth.json` | 认证 Token | ✅ |
| `gcs_cache.db` | SQLite 缓存 | ✅ |
| `oss_cache.db` | SQLite 缓存 | ✅ |
| `gemini_files_cache.db` | SQLite 缓存 | ✅ |
| `api_config.yaml` | 端点配置 | ❌ 需要提交 |
| `output/batchbox/*.png` | 生成图片 | ✅ |

## HTTP 路由

| 路由 | 方法 | 用途 |
|:-----|:-----|:-----|
| `/api/batchbox/generate-independent` | POST | 独立生成 |
| `/api/batchbox/generate-blur-upscale` | POST | 模糊放大生成 |
| `/api/batchbox/apply-blur` | POST | 应用模糊预览 |
| `/api/batchbox/config` | GET | 获取配置 |
| `/api/batchbox/save-config` | POST | 保存配置 |
| `/api/batchbox/node-settings` | GET/POST | 节点设置 |
| `/api/batchbox/account/status` | GET | 账号状态 |
| `/api/batchbox/account/login` | POST | 账号登录 |
