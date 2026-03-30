# 前端安全检查清单

## XSS 防护
- [ ] 无 `innerHTML = 不可信变量` 的使用
- [ ] 无 `document.write()` 的使用
- [ ] 后端返回的字符串通过 `textContent` 展示
- [ ] API 错误信息展示时不使用 HTML 渲染

## DOM 安全
- [ ] 所有 DOM 元素获取后做 null guard
- [ ] 面板关闭后释放事件监听器
- [ ] 节点删除后无残留引用（WebSocket listener 清理）
- [ ] progressive preview 的 staging slots 在 finally 中清理

## 异步请求安全
- [ ] fetch 请求有 timeout 或 AbortController
- [ ] 生成按钮防重复点击（`_isGenerating` 守护）
- [ ] WebSocket 监听器在 finally 中移除
- [ ] 过期的 generation_token 响应被忽略
