# 并发稳定性检查清单

## 事件循环
- [ ] CPU 密集型任务（图片处理）使用 `asyncio.to_thread()` 不阻塞主循环
- [ ] 所有 `requests.*` 调用在 `to_thread` 中执行
- [ ] 无同步阻塞调用在 async 路由中

## 线程安全
- [ ] SQLite 连接使用 `threading.local()` —— `gcs_cache.py`, `oss_cache.py`, `gemini_files_cache.py`
- [ ] `IndependentGenerator` 无共享可变状态
- [ ] 上传锁 `_upload_locks` 使用 per-hash 粒度，不会全局阻塞

## 资源上限
- [ ] `batch_count` 硬上限 20
- [ ] 线程池使用 Python 默认 `ThreadPoolExecutor`（非无限）
- [ ] 图片数量上限：`max_images` 配置
- [ ] API 轮询有最大次数限制

## 取消与清理
- [ ] 前端生成按钮防重复点击
- [ ] WebSocket listener 在 finally 中清理
- [ ] timeout 后后台任务不会继续空跑
