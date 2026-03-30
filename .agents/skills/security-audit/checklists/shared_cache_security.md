# 共享缓存安全检查清单 (BatchBox 特有)

## NAS 访问控制
- [ ] `BATCHBOX_SHARED_CACHE` 路径只通过环境变量设置
- [ ] 学生机对 NAS 共享目录只有读写权限，无管理权限
- [ ] 共享缓存目录不在 Web 可访问路径下

## SQLite 并发安全
- [ ] 所有共享 DB 连接启用 WAL 模式 (`PRAGMA journal_mode=WAL`)
- [ ] 共享写入使用 `INSERT OR IGNORE`（不覆写其他机器的数据）
- [ ] 连接 timeout 设置（5 秒），防 NAS 挂起
- [ ] 所有共享操作 try/except 包裹，失败不影响本地

## 数据完整性
- [ ] 共享缓存 key 包含作用域（bucket/endpoint），防跨环境冲突
- [ ] `gemini_files_cache` 正确传播 `expires_at`，不使用过期 file_uri
- [ ] 共享命中后 promote 到本地 DB，减少 NAS 依赖

## 降级安全
- [ ] NAS 不可达时完全降级到本地缓存（无报错、无卡顿）
- [ ] `_SHARED_DB_PATH=""` 时所有共享逻辑被跳过
- [ ] 共享 DB 初始化失败时只 warning 不 error
