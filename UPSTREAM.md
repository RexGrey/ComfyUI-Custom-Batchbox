# Upstream Project Reference

本项目的 Account 模块移植自 [AIGODLIKE BlenderAIStudio](https://github.com/AIGODLIKE/BlenderAIStudio)。

## 移植基准版本

| 字段 | 值 |
|------|---|
| **版本** | v0.1.4 |
| **Commit** | `8b8c53394c8d18adc167b86aa3f4bc22929fcaba` |
| **日期** | 2026-02-28 17:20:15 +0800 |
| **分支** | master |
| **本地路径** | `/Users/sansan/Documents/GitHub/BlenderAIStudio` |

## 移植范围

### 已移植模块

| 原始文件 | 我们的文件 | 说明 |
|---------|-----------|------|
| `src/studio/account/core.py` | `account/core.py` | 账户核心逻辑（移除 bpy 依赖） |
| `src/studio/account/websocket.py` | `account/websocket_server.py` | WebSocket 登录服务器 |
| `src/studio/account/network.py` | `account/network.py` | HTTP 会话管理 |
| `src/studio/account/task_sync.py` | `account/task_sync.py` | 任务同步服务 |
| `src/studio/account/task_history.py` | `account/task_history.py` | 任务历史管理 |
| `src/studio/config/url_config.py` | `account/url_config.py` | URL 配置管理 |
| `src/studio/config/products.json` | (内嵌 `api_manager.js`) | 购买礼包信息 |
| `src/studio/config/models_config.yaml` | `api_config.yaml` | 模型配置（Account 通道部分） |

### 已移植模型（Account 通道）

| 模型名 | modelId | 状态 |
|--------|---------|------|
| NanoBananaPro | `gemini-3-pro-image-preview` | ✅ |
| NanoBanana2 | `gemini-3.1-flash-image-preview` | ✅ |
| NanoBanana | `gemini-2.5-flash-image` | ✅ |
| Seedream-v4 | `doubao-seedream-4-0-250828` | ✅ |
| Seedream-v4.5 | `doubao-seedream-4-5-251128` | ✅ |

### 未移植（Blender 专属）

- `src/studio/account/error_report.py` — 依赖 bpy，日志上报
- `src/studio/config/model_registry.py` — Blender 端模型注册器
- imgui UI 渲染 (StorePanel / RedeemPanel) — 用 HTML 替代
- 图片编辑/导出操作 — Blender 特有

## 同步更新方法

当原项目发布新版本时：

```bash
# 1. 拉取最新代码
cd /Users/sansan/Documents/GitHub/BlenderAIStudio
git pull

# 2. 查看自上次移植以来的变更
git log 8b8c533..HEAD --oneline

# 3. 重点关注以下目录的变更
git diff 8b8c533..HEAD -- src/studio/account/
git diff 8b8c533..HEAD -- src/studio/config/models_config.yaml
git diff 8b8c533..HEAD -- src/studio/config/products.json
```

审阅变更后，对照修改我们的对应文件。
