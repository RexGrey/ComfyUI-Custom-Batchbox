---
description: Git commit 规范
---
# Git Commit 规范

1. 前缀使用英文 conventional commits 类型，描述部分**使用中文**
2. 格式：`type: 中文描述`
3. 常用类型：
   - `feat:` 新增功能
   - `fix:` 修复 bug
   - `perf:` 性能优化
   - `refactor:` 重构代码
   - `chore:` 杂项（日志、注释等）
   - `docs:` 文档变更
   - `style:` 样式/格式调整

示例：
```
feat: 新增多密钥轮换与黑名单机制
fix: Files API 缓存按密钥隔离，避免 403 错误
perf: 预览图缩略图降低画布内存占用
chore: 密钥日志增加编号显示 (Key#1-#8)
```
