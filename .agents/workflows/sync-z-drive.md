---
description: 将 E 盘源码同步到 Z 盘实际运行目录，保护阉割版修改和敏感文件不被覆盖
---

# 一键安全发行 (Sync Z-Drive)

## 前置知识
不再需要手动排雷或物理阉割 JavaScript/Python 代码！此宏指令将自动触发端到端的 Cython 编译打包，确保发往 Z 盘的全部是一致的 `.pyd` 机器码及安全的 `__init__.py` 接口屏蔽层。

## 步骤

### 1. 执行 Cython 安全编译 (使用目标环境的 Python)
为确保 C-API 的 ABI 版本兼容，强制使用 Z 盘的官方便携版 Python 3.13 执行 `build_plugin.py`。
此步骤将遍历除 Web/配置 外的 28 个核心 Python 文件并生成二进制库到 `dist/ComfyUI-Custom-Batchbox`。

// turbo
```powershell
Z:\ComfyUI_Master\ComfyUI_windows_portable\python_embeded\python.exe build_plugin.py
```

### 2. 清理遗留并部署黑盒环境
使用 RoboCopy 将纯净的 `dist` 产物镜像到 Z 盘运行环境，并补发加密基底文件。

// turbo
```powershell
# 删除Z盘中旧的二进制文件，避免残留问题
Remove-Item "Z:\ComfyUI_Master\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox\*.pyd" -ErrorAction SilentlyContinue

# 只同步安全构建包 dist 目录
robocopy "e:\AIGC\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox\dist\ComfyUI-Custom-Batchbox" "Z:\ComfyUI_Master\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox" /MIR

# 补发基础加密凭证 (剔除了 secrets.yaml)
Copy-Item "e:\AIGC\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox\secrets.yaml.enc" "Z:\ComfyUI_Master\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox\" -Force
Copy-Item "e:\AIGC\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox\api_config.yaml" "Z:\ComfyUI_Master\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox\" -Force
```

## 验证
同步完成后在学生端重启 ComfyUI，即可获得完全无核心源代码的“只读环境”。
