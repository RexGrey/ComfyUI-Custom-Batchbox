# 日志隐私检查清单

## 密钥脱敏
- [ ] API Key 日志只打印尾号（`key[-8:]` 或 `key[:8]...`）
- [ ] Authorization header 不出现在日志中
- [ ] Service Account 凭证不出现在日志中
- [ ] Account Token 不出现在日志中

## URL 脱敏
- [ ] Google API URL 中的 `?key=` 参数：需确认是否在日志中全文打印（当前已打印）
- [ ] OSS 签名 URL 不在日志中全文打印
- [ ] 内网 IP/hostname 不在面向用户的日志中

## 错误信息
- [ ] traceback 不回传前端（路由 try/except 返回脱敏 error）
- [ ] 上游 API 错误信息适度截断后返回前端
- [ ] 内部文件路径不出现在前端错误信息中

## 调试日志
- [ ] 生产环境无调试用 `print()` 残留
- [ ] `logger.debug()` 不在默认日志级别下输出敏感信息
