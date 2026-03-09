# Testing Summary

日期：2026-03-09

## 当前状态

- 命令：`python3 -m pytest tests -q`
- 结果：`334 collected, 327 passed, 7 skipped, 0 failed`
- 跳过项：7 个 `torch` 相关用例，需在带 `torch` 的环境中复验

## 当前测试分布

| 文件 | 用例数 | 覆盖范围 |
|------|-------:|----------|
| `test_account_core.py` | 16 | 单例、初始状态、错误队列、账号信息加载、登出、状态查询、模型 ID 解析、provider 计数 |
| `test_account_task_sync.py` | 22 | 状态归一化、批量响应解析、MIME 检测、poller 队列、临时文件保存 |
| `test_adapters.py` | 9 | GenericAPIAdapter 初始化、请求构建、执行成功/失败、响应解析、multipart 配置 |
| `test_api_endpoints.py` | 11 | 路由注册、`/models`、`/schema/{model_name}`、`/config`、`/reload`、account 基本路由、`blur-preview`、`generate-independent`、`generate-blur-upscale` |
| `test_base_adapter.py` | 22 | `APIResponse`、`APIError`、headers、api key 轮换、嵌套取值/设值、下载重试 |
| `test_batchbox_logger.py` | 33 | `RequestTimer`、`RetryConfig`、退避计算、`should_retry`、重试装饰器、日志函数、logging 配置 |
| `test_config_manager.py` | 18 | 配置加载、model/provider 查询、schema、template engine、provider config |
| `test_errors.py` | 20 | 自定义错误类型、重试判定、错误工厂函数 |
| `test_frontend_scripts.py` | 1 | `blur_upscale.js` 进度刷新走 RAF 合并，避免高频直接重绘 |
| `test_gcs_cache.py` | 13 | hash、扩展名推断、GCSCacheDB CRUD/stats、GCS disabled 行为 |
| `test_gemini_files_cache.py` | 17 | hash、TTL 过期、cleanup、stats、cache hit、上传流程 |
| `test_image_utils.py` | 46 | 格式识别、透明通道、ComfyUI 预处理、tensor、编码、信息提取、校验、高斯模糊、预览 |
| `test_independent_generator.py` | 16 | 参数哈希、adapter 路由、failover、并行 `generate()` 链路 |
| `test_oss_cache.py` | 20 | hash、扩展名推断、CacheDB CRUD/stats、OSS disabled 行为 |
| `test_prompt_templates.py` | 9 | 模板查询、registry 完整性、gemini/seedream 模板 |
| `test_save_settings.py` | 23 | 默认值/更新、文件名生成、保存路径、图片保存、预览、全局函数 |
| `test_template_engine.py` | 22 | render、chat content、映射值处理、变量提取 |
| `test_volcengine.py` | 16 | Signature V4、请求构建、响应解析、执行/轮询/下载链路 |

## 下一阶段：集成链路测试

优先级从高到低：

1. 深测 `__init__.py` 的复杂路由：
   - `/api/batchbox/generate-independent`
   - `/api/batchbox/generate-blur-upscale`
   - `/api/batchbox/blur-preview`
   - 重点覆盖分块 body、WebSocket 事件、history 写入
2. 在真实 ComfyUI 环境做一轮 smoke test，而不是只依赖 mock 的 `server` / `folder_paths`
3. 在带 `torch` 的环境中跑完当前 7 个跳过用例，确认 tensor 分支
4. 为 OSS / GCS / Gemini Files 缓存补一轮更接近真实依赖的集成测试，尤其是在这些能力会高频使用时

## 备注

- 当前单元测试和模块级测试已经形成稳定基线。
- 后续新增测试应优先覆盖真实运行链路，而不是继续堆叠低风险单元用例。
