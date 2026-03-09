# ComfyUI-Custom-Batchbox

ComfyUI 自定义节点插件。动态参数面板 + 多 API 中转站 + 智能缓存 + Account 计费系统。
前后端分离：Python 后端（节点逻辑 + REST API）+ JavaScript 前端（动态 UI 渲染）。

详细架构参见 `ARCHITECTURE.md`，配置参考见 `YAML_CONFIG_REFERENCE.md`，版本历史见 `CHANGELOG.md`。

---

## 文件地图

### 后端核心
| 文件 | 职责 |
|------|------|
| `__init__.py` | 节点注册（NODE_CLASS_MAPPINGS）+ 20+ REST API 端点（`/api/batchbox/`） |
| `nodes.py` | 所有节点类：`DynamicImageNodeBase` 基类 + 6 种子类 + `GaussianBlurUpscaleNode` |
| `config_manager.py` | YAML 配置加载/缓存/热重载，单例 `config_manager`，TTL 5min |
| `adapters/generic.py` | API 请求构建，按 `api_format` 分发到 OpenAI/Gemini 路径 |
| `adapters/base.py` | `APIAdapter` 抽象基类 + `APIResponse` 数据类 |
| `adapters/template_engine.py` | Jinja2 风格的请求 payload 模板 |
| `adapters/volcengine.py` | 火山引擎专用适配器 |
| `independent_generator.py` | 独立并发生成引擎，绕过 ComfyUI 队列 |
| `batchbox_logger.py` | 日志 + 重试装饰器（指数退避） |
| `errors.py` | 结构化异常层级（BatchboxError → APIError/ConfigError/...） |
| `image_utils.py` | 图片处理工具（PIL↔tensor, 高斯模糊, base64） |
| `save_settings.py` | 自动保存文件命名模板 |
| `prompt_templates.py` | Prompt 模板管理 |
| `oss_cache.py` / `gcs_cache.py` / `gemini_files_cache.py` | 图片缓存（阿里 OSS / GCS / Gemini Files） |

### Account 系统（`account/`）
移植自 BlenderAIStudio。`Account.get_instance()` 单例。
- `core.py` — 登录流程 + Token 管理 + 积分查询
- `task_sync.py` — 任务状态轮询
- `network.py` — HTTP session
- `websocket_server.py` — 登录 WebSocket 回调

### 前端（`web/`）
| 文件 | 职责 |
|------|------|
| `dynamic_params.js` | 动态参数渲染 + schema 缓存 + 独立生成按钮 + 画布右键菜单 |
| `api_manager.js` | 配置管理 Modal UI（供应商/模型/设置 CRUD） |
| `dynamic_inputs.js` | 多图输入槽管理 + 紧凑策略 + 预览恢复 |
| `blur_upscale.js` | GaussianBlurUpscale 节点 UI（Canvas 绘制 + DOM 面板） |

### 配置文件
| 文件 | 说明 |
|------|------|
| `api_config.yaml` | 主配置：供应商/模型/参数 schema/端点/设置 |
| `secrets.yaml` | API 密钥（`.gitignore` 排除），模板见 `secrets.yaml.example` |

---

## 核心架构模式

### 配置驱动
所有 API 供应商和模型定义在 `api_config.yaml`，代码通过配置适配，不硬编码。

### 层级配置优先级
```
端点级(mode_config) > 端点级(endpoint) > 供应商级(provider) > 系统默认
```

### API 格式分发
`api_format` 字段决定请求构建路径：
- `openai`（默认）→ `_build_openai_request()`
- `gemini` → `_build_gemini_request()`

### 三通道认证
- Account: `X-Auth-T` header + 数字 model ID
- Google 官方: URL `?key={api_key}`（`auth_header_format: none`）
- 第三方代理: `Bearer` token

### 动态参数流程
```
模型选择 → GET /api/batchbox/schema/{model} → 前端动态渲染 widgets
```

### 独立生成
`IndependentGenerator` 通过 `/api/batchbox/generate-independent` 绕过 ComfyUI 队列，支持并发批处理 + WebSocket 进度推送。

### 智能缓存
MD5 哈希 = `model|prompt|batch_count|seed|extra_params_normalized`。前后端统一由后端计算，通过 `params_hash` 字段传递。

---

## 节点类型

| 节点 ID | 显示名 | 类别 |
|---------|--------|------|
| `NanoBananaPro` | 🍌 Nano Banana Pro (Universal) | image |
| `DynamicImageGeneration` | 🎨 Dynamic Image Generation | image |
| `DynamicTextGeneration` | 📝 Dynamic Text Generation | text |
| `DynamicVideoGeneration` | 🎬 Dynamic Video Generation | video |
| `DynamicAudioGeneration` | 🎵 Dynamic Audio Generation | audio |
| `DynamicImageEditor` | 🔧 Dynamic Image Editor | image |
| `GaussianBlurUpscale` | 🔍 Gaussian Blur Upscale | image |

节点注册在 `__init__.py` 的 `NODE_CLASS_MAPPINGS` / `NODE_DISPLAY_NAME_MAPPINGS`。
动态节点通过 `create_dynamic_node()` 工厂函数从配置生成。

---

## 开发规范

### Commit 信息
中文，带前缀：`feat:` / `fix:` / `refactor:` / `perf:` / `docs:`

### API 端点
所有端点以 `/api/batchbox/` 为前缀，在 `__init__.py` 中通过 `PromptServer.instance.routes` 注册。

### Widget 隐藏（前端）
```javascript
widget.hidden = true;
widget.computeSize = () => [0, -4];
widget.type = "hidden";
```

### 节点宽度保持（前端）
修改节点 UI 后调用 `resizeNodePreservingWidth(node)` 而非 `node.setSize()`，防止宽度被重置为 ~252px。

### 大请求体读取（后端）
```python
# 不要用 request.json()（有 ~1MB 限制）
chunks = []
async for chunk in request.content.iter_any():
    chunks.append(chunk)
data = json.loads(b''.join(chunks))
```

### JSON 哈希序列化（后端）
与前端比较哈希时必须使用紧凑格式：
```python
json.dumps(params, sort_keys=True, separators=(',', ':'))
```

### Multipart 字段过滤（后端）
排除内部字段用 `k.startswith("_")`。**不要**用 `k.startswith("image")`（会误删 `image_size` 等参数）。

### 密钥管理
密钥存入 `secrets.yaml`（已 .gitignore），**不要**写入 `api_config.yaml`。
`config_manager.py` 启动时自动合并 secrets 到内存配置。

### 节点类型识别（前端）
```javascript
const nodeType = node.comfyClass || node.type;  // 用 comfyClass，不要只用 type
```

---

## 常见陷阱

| 陷阱 | 说明 |
|------|------|
| `node.imgs = []` | 空数组是 truthy，ComfyUI 会分配空 image area 导致画布冻结。用 `null` 或不清除 |
| `control_after_generate` | 可能在 `onNodeCreated` 之后才添加，需 `setTimeout` 延迟检查 |
| `_isRestoring` 期间 resize | `resizeNodePreservingWidth()` 会被跳过，需标记 `_needsPostRestoreResize` 恢复后补做 |
| Monkey-patching `api.queuePrompt` | 执行后必须**立即恢复**原始方法，采用临时覆盖模式 |
| img2img 共享 base64 | 批量生成时预缓存 `(filename, bytes, mime, cached_b64)` 四元组，所有批次共享引用 |
| 端点选择 vs Account | Account 模式需通过 `Account.resolve_model_id()` 将显示名转为数字 ID |

---

## 测试

```bash
python -m pytest tests/
```

测试文件在 `tests/` 目录，使用 unittest 框架：
- `test_config_manager.py` — 配置加载/缓存
- `test_adapters.py` — 适配器请求构建
- `test_errors.py` — 异常类行为

---

## 热重载机制

配置保存后的刷新链路：
```
API Manager 保存 → POST /api/batchbox/config
                 → POST /api/batchbox/reload（强制后端刷新）
                 → dispatchEvent("batchbox:config-changed")（通知前端）
                 → clearSchemaCache() + 更新 widget options + forceRefresh
```

---

## 关键 API 端点

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/batchbox/config` | GET/POST | 读取/保存完整配置 |
| `/api/batchbox/reload` | POST | 强制重载配置 |
| `/api/batchbox/models` | GET | 模型列表（支持 `?category=` 过滤） |
| `/api/batchbox/schema/{model}` | GET | 模型参数 Schema |
| `/api/batchbox/providers` | GET | 供应商列表 |
| `/api/batchbox/generate-independent` | POST | 独立并发生成 |
| `/api/batchbox/node-settings` | GET/POST | 节点显示设置 |
| `/api/batchbox/save-settings` | GET/POST | 自动保存设置 |
| `/api/batchbox/account/login` | POST | Account 登录 |
| `/api/batchbox/account/status` | GET | 登录状态/积分 |
