# 历次安全审查发现汇总

## 审查历史

| 次数 | 日期 | 范围 | 结论 |
|:-----|:-----|:-----|:-----|
| 1-8 | 2026-03 | 全仓 | 基础安全审查 |
| 9 | 2026-03-25 | 网络层韧性 | 通过 ✅ |
| 10 | 2026-03-25 | Account 鉴权 + IO 防护 | 通过 ✅ |
| 11 | 2026-03-26 | NAS 共享缓存 + 选区裁剪 | 通过 ✅ |
| 12 | 2026-03-26 | 基线验证 (SKILL 自动化+语义审计) | 通过 ✅ |

## 已确认安全的模块

### 模板引擎 (第 9 次确认)
- `adapters/template_engine.py` 使用 AST-free 纯正则替换
- 无 `eval()`/`exec()` 调用链
- 结论：无沙箱逃逸风险

### JSON 解析 (第 9 次确认)
- 所有 `resp.json()` 和 `json.loads()` 均被 try/except 包裹
- 畸形 JSON 不会导致进程级崩溃

### 鉴权系统 (第 10 次确认)
- `/api/batchbox/account/status` 只吐脱敏字段
- WebSocket `55441` 为物理单向阀，无 get_token 指令

### 文件写入 (第 10 次确认)
- 所有写入路径封锁在插件目录和 tempdir
- 无外部传入 filename 的 open 动作

### 共享缓存 (第 11 次确认)
- WAL 模式 + INSERT OR IGNORE + try/except
- NAS 故障完全透明降级

## 持续关注项

| 项目 | 风险等级 | 状态 |
|:-----|:---------|:-----|
| Google API URL 含 key 参数的日志 | P2 | 已知，key 在 URL 中是 Google API 设计 |
| 共享 DB 连接泄漏风险 | P3 | 极低，依赖 GC 回收 |
| `BATCHBOX_KEY` 单密钥风险 | P2 | 已知，30 机共用同一密钥 |
