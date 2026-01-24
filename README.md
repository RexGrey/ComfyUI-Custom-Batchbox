# ComfyUI-Custom-Batchbox (Nano Banana Pro)

**Nano Banana Pro** 是一个功能强大的 ComfyUI 自定义节点，专为需要高效、稳定调用远程绘图 API（如 Nano Banana, Flux Pro 等）的用户设计。它支持批量生成、集中式配置管理以及自动负载均衡（供应商轮询）。

## ✨ 核心功能

*   **⚡ 集中配置**: 告别在节点上重复填写 API Key 和 URL，所有配置统一在 `api_config.yaml` 管理。
*   **🔌 多供应商轮询 (Load Balancing)**: 若当前 API 供应商请求失败，插件可自动切换到备用供应商，最大程度保证任务成功。
*   **🔄 批量循环**: 支持一次性提交多个请求 (`batch_count`)。
*   **🧠 智能识别**: 自动识别同步（Direct）和异步（Polling）API 响应格式。
*   **📁 预设管理**: 通过下拉菜单快速切换不同的模型或供应商配置。

---

## 🚀 安装说明

1.  将本项目文件夹 `ComfyUI-Custom-Batchbox` 放置在您的 ComfyUI `custom_nodes` 目录下。
    *   路径示例: `...\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox\`
2.  确保安装了必要的 Python 依赖（通常 ComfyUI 自带）：
    *   `requests`
    *   `pyyaml`
3.  **重启 ComfyUI**。

---

## ⚙️ 配置指南 (重要)

在使用节点前，您**必须**配置 API 信息。

1.  打开插件目录下的 **`api_config.yaml`** 文件。
2.  参照以下格式填入您的服务商信息：

```yaml
# 1. 定义服务商 (Providers)
# 在这里填写您的中转站或官方 API 的 Base URL 和 Key
providers:
  MyProxy:
    base_url: "https://api.one-api.com"
    api_key: "sk-xxxxxxxxxxxxxxxx"

  BackupProxy:
    base_url: "https://api.backup-site.com"
    api_key: "sk-yyyyyyyyyyyyyyyy"

# 2. 定义预设 (Presets)
presets:
  # 预设名称 (显示在节点菜单中)
  NanoBanana_Main:
    description: "Nano Banana (主线路)"
    provider: "MyProxy"        # <--- 引用上面的服务商
    model_name: "nano-banana-2"
    modes:
      text2img:
        endpoint: "/v1/images/generations"
        response_type: "sync"  # "sync" (直接返回) 或 "async" (需要轮询)

  # 备用预设 (用于自动切换)
  NanoBanana_Backup:
    description: "Nano Banana (备用线路)"
    provider: "BackupProxy"    # <--- 引用备用服务商
    model_name: "nano-banana-2" # 模型名称必须相同，才能触发自动轮询
    modes:
      text2img:
        endpoint: "/api/generate"
        response_type: "async"

  # [NEW] 独立动态节点 (Dynamic Node)
  # 定义这个预设后，ComfyUI 中会自动生成一个独立的节点
  NanoBanana_Specific:
    provider: "MyProxy"
    model_name: "nano-banana-2"
    modes:
       text2img: { endpoint: "/v1/images/generations", response_type: "sync" }
    
    # 关键字段：不加这个字段就是通用节点的预设，加了就是独立节点
    dynamic_node:
      class_name: "NanoBananaSpecificNode"      # 必须唯一
      display_name: "🍌 Nano Banana Specific"   # 搜索菜单里显示的名字
      parameters:
        required:
          # 在这里只定义你想在这个节点上看到的参数
          image_size: { type: ["1K", "2K", "4K"], default: "2K" }
          aspect_ratio: { type: ["1:1", "16:9"], default: "16:9" }
          prompt: { type: STRING, multiline: True }
        optional:
          seed: { type: INT, default: 0 }
```

---

## 📖 节点使用说明

本插件采用了 **混合架构**，提供两种类型的节点，您可以根据喜好选择。

### 1. 🍌 通用节点 (Universal Node)
- **节点名称**: `Nano Banana Pro (Universal)`
- **特点**: 功能最全，参数最多。
- **用法**: 
    1.  添加节点。
    2.  在 `preset` 下拉菜单中选择任意已配置的模型。
    3.  即使是为“独立节点”配置的预设，也可以在这里被选到。

### 2. 🆕 独立动态节点 (Dynamic Node)
- **节点名称**: 取决于您在配置文件的 `display_name` (例如 `🍌 Nano Banana Specific`)。
- **特点**: 界面清爽，只显示该模型需要的参数。
- **用法**:
    1.  在 `api_config.yaml` 中定义 `dynamic_node` 字段。
    2.  重启 ComfyUI。
    3.  搜索您定义的名字并添加使用。

---

### 通用节点参数详解

### 参数详解

| 参数名 | 说明 |
| :--- | :--- |
| **preset** | **预设选择**。从 `api_config.yaml` 加载的配置列表。选择后将自动应用对应的 URL 和 Key。 |
| **auto_switch_provider** | **自动切换供应商**。<br>- `Disabled`: 仅使用当前选中的预设。<br>- `Enabled`: 如果当前预设请求失败，会自动查找并尝试其他同模型 (`model_name` 相同) 的预设。 |
| **batch_count** | **批量数量**。循环运行生成的次数。 |
| **prompt** | 正向提示词。 |
| **mode** | `text2img` (文生图) 或 `img2img` (图生图)。 |
| **aspect_ratio** | 图片比例 (如 16:9, 1:1, auto)。 |
| **image_size** | 图片尺寸/分辨率 (如 1K, 2K)。 |
| **seed** | 随机种子。 |

### 图生图 (img2img)
连接 `image1` 到 `image14` 端口即可传入参考图。节点会自动处理图片的上传和 Base64 转换。

---

## ❓ 常见问题

**Q: 为什么节点加载失败？**
A: 请检查 `custom_nodes/ComfyUI-Custom-Batchbox` 目录下是否有 `__init__.py` 和 `nodes.py`。如果是依赖缺失，请尝试 `pip install pyyaml requests`。

**Q: 如何让“自动切换”生效？**
A: 您需要在 `api_config.yaml` 中定义至少两个预设，并且它们的 `model_name` 字段必须**完全一致**。例如 `NanoBanana_Main` 和 `NanoBanana_Backup` 的 model_name 都是 `nano-banana-2`。

**Q: 节点一直在 Polling 但是不结束？**
A: 请检查您的 `base_url` 和 `endpoint` 是否正确。如果是异步任务，确保服务商支持 `/v1/images/tasks/{task_id}` 格式的查询。
