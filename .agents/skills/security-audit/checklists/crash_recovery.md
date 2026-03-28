# 崩溃恢复检查清单

## 外部 API 故障隔离
- [ ] 所有 requests 调用有 timeout 参数
- [ ] API 429 不会导致无限重试（有 max_retries）
- [ ] API 返回畸形 JSON 被 try/except 捕获
- [ ] API 超时不会阻塞 ComfyUI 主线程

## 资源保护
- [ ] 大图 base64 解码前有大小检查
- [ ] 模糊处理有内存安全的实现（OpenCV/PIL）
- [ ] 批量处理不会一次性加载所有图片到内存

## 失败语义
- [ ] 全部失败时返回 `success: false`，不伪造黑图
- [ ] 局部失败时正确标记（返回成功的部分 + 错误信息）
- [ ] 前端收到 `success: false` 时显示明确错误提示

## 配置降级
- [ ] `secrets.yaml` 解密失败时有明确错误（不静默跳过）
- [ ] NAS 不可达时共享缓存静默降级到本地
- [ ] `api_config.yaml` 格式异常时有回退/报错
