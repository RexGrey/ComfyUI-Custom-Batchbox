# 部署架构：双轨制（完整版 + 阉割版）

## 概述

本插件采用"同源异构"双轨部署。同一份代码库维护两套运行版本：
- **E 盘完整版**（教师主控）：拥有 API 管理器 UI、密钥配置接口等全部功能
- **Z 盘阉割版**（学生母盘）：物理移除了管理器入口和敏感接口，被学生机克隆后天然无权限

## 关键路径

| 角色 | 路径 | 说明 |
|------|------|------|
| **E 盘源码** | `E:\AIGC\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox` | Git 仓库，完整版，教师直接运行 |
| **Z 盘实际运行** | `Z:\ComfyUI_Master\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox` | 学生端 ComfyUI 实际加载的插件目录，也是 `Start_Client.bat` 克隆的母盘源 |

> ⚠️ **关键提醒**：任何面向学生的修改必须在 Z 盘实际运行路径上操作。同步时必须排除已阉割的文件（见下方清单）。

## 学生端克隆链路

```
E盘源码 --[robocopy（排除阉割文件）]--> Z盘实际运行目录
                                          ↓
Z盘实际运行目录 --[Start_Client.bat robocopy]--> C:\ComfyUI_Portable（学生本地）
```

`Start_Client.bat` 位于 `Z:\ComfyUI_Master\Start_Client.bat`，它会：
1. 自动搜索 NAS 盘符（F-Z 全扫描）
2. 将 `%NAS%\ComfyUI_Master\ComfyUI_windows_portable\ComfyUI\custom_nodes` 整体镜像到学生本地
3. 同步 Python 包
4. 启动 ComfyUI

## 阉割版修改清单

以下文件在 **Z 盘实际运行路径** 中被物理修改（与 E 盘源码不同）：

### `web/api_manager.js`
- **修改位置**：`createFloatingButton()` 调用处（约第 3059 行）
- **修改内容**：将按钮创建和注入替换为 `return;`，管理器入口永不渲染
- **标记注释**：`// [STUDENT EDITION] API Manager UI disabled for security`

### `__init__.py`
- **修改位置**：`GET /api/batchbox/config` 和 `POST /api/batchbox/config`（约第 157-165 行）
- **修改内容**：两个接口直接返回 `403 Forbidden`，防止通过 HTTP 工具抓取密钥
- **标记注释**：`"""[STUDENT EDITION] Config endpoint disabled"""`

## E 盘完整版的自适应机制

E 盘源码中还包含了一套基于 `.git` 目录存在性的运行时检测机制（`IS_ADMIN` 变量）。但由于 Z 盘采用的是**物理阉割**而非运行时检测，这套机制目前仅作为 E 盘的额外保险层存在。

## 控制台安全

经审计，所有后端网络模块（`adapters/generic.py`、`independent_generator.py` 等）在控制台日志中仅打印 Key 的末尾 6 位掩码（如 `Key#1 ...pIb3mE`），不会泄漏完整密钥。
