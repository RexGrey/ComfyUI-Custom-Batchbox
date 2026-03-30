---
description: 将 E 盘源码同步到 Z 盘实际运行目录，保护阉割版修改和敏感文件不被覆盖
---

# 同步 E 盘代码到 Z 盘

## 前置知识
- E 盘是完整版源码（有 `.git`、有管理器）
- Z 盘实际运行目录：`Z:\ComfyUI_Master\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox`
- Z 盘中的 `api_manager.js` 和 `__init__.py` 已被物理阉割，**同步时必须排除**
- Z 盘的 `secrets.yaml`（明文密钥）**绝不能存在**，只允许 `.enc` 加密版

## 步骤

### 1. 同步到 Z 盘实际运行目录

同步时**必须排除已阉割的两个文件**，否则会把完整版覆盖上去：

// turbo
```
robocopy "e:\AIGC\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox" "z:\ComfyUI_Master\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox" /MIR /XD .git .agents __pycache__ tests node_modules /XF _bench_results.json api_manager.js __init__.py secrets.yaml .secrets_key .auth.json
```

> ⚠️ `/XF` 排除清单说明：
> - `api_manager.js` + `__init__.py` → 阉割版核心，不可覆盖
> - `secrets.yaml` + `.secrets_key` + `.auth.json` → 明文密钥/凭据，不可同步到 Z 盘

### 2. 如需更新阉割文件中的非敏感代码

如果 E 盘的 `__init__.py` 或 `api_manager.js` 有功能性更新（比如修了 bug），需要**手动合并**：
1. 先把 E 盘的改动同步到 Z 盘对应文件
2. 然后重新打上阉割补丁（参考 `DEPLOYMENT.md` 中的修改清单）

### 3. 验证

同步完成后，在学生端重启 ComfyUI 并确认：
- [ ] 管理器浮窗不出现
- [ ] 生图功能正常
- [ ] 控制台无明文密钥
- [ ] Z 盘目录中不存在 `secrets.yaml`（只允许 `.enc`）

## 注意事项
- 学生端需要**重启 ComfyUI 后台进程**才能加载新的 Python 代码
- 前端 JS 文件可以通过 `Ctrl+F5` 强刷浏览器缓存生效
- `Start_Client.bat` 位于 `Z:\ComfyUI_Master\Start_Client.bat`，修改后学生下次启动时自动拉取最新版
