# API 安全检查清单

## 路由认证
- [ ] 所有 `/api/batchbox/*` 路由不需要外部认证（ComfyUI 本地运行）
- [ ] 网关模式下路由需要 client_id + secret 认证（未来）

## 输入校验
- [ ] `batch_count` 有硬上限 (`min(val, 20)`)，检查 `__init__.py`
- [ ] `prompt` 长度不触发内存问题（大模型自行截断）
- [ ] `images_base64` 数量有限制（`max_images` 配置）
- [ ] `endpoint_override` 只能从已配置端点列表中选择，不接受任意 URL
- [ ] `seed` 值为整数类型校验

## 请求边界
- [ ] 全局 body size limit 已设置（`client_max_size=500MB`），检查 `__init__.py`
- [ ] 每个 API 调用有 timeout（`requests.post(timeout=...)`)
- [ ] 异步 API 轮询有限次限频（poll_interval + max_polls）
- [ ] 重试有限次（`RetryConfig.max_retries`）

## SSRF 防护
- [ ] `adapters/generic.py` 中 URL 只从配置文件构建，不从用户输入拼接
- [ ] 下载代理（如有）限制域名白名单
- [ ] `endpoint_override` 映射到配置名称，不直接用作 URL

## 错误处理
- [ ] API 错误返回脱敏信息，不暴露内部路径
- [ ] HTTP 状态码映射正确（400/500 区分）
- [ ] traceback 不回传前端（`try/except` 包裹路由）
