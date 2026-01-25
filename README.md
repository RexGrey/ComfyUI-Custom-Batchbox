# ComfyUI-Custom-Batchbox

**ComfyUI-Custom-Batchbox** 是一个强大的 ComfyUI 自定义节点系统，支持动态参数面板、多 API 供应商、自动故障转移，以及完整的可视化配置管理。

## ✨ 核心功能

### 🎯 动态参数面板

- 选择不同模型后，节点参数自动更新
- 支持参数分组（基础/高级）
- 支持多种参数类型：字符串、数字、下拉选择、开关

### 🔌 多供应商支持

- 同一模型可配置多个 API 供应商
- 支持优先级排序
- 自动故障转移（Failover）

### 📊 节点类型

| 节点 | 功能 |
|------|------|
| �️ 图片生成 | 文生图、图生图 |
| 📝 文本生成 | AI 脚本、广告词 |
| 🎬 视频生成 | AI 视频创作 |
| 🎵 音频生成 | AI 音频合成 |
| � 图片编辑 | 局部重绘、超分 |

### ⚙️ 可视化配置

- 内置 API Manager 界面
- 无需编辑 YAML 文件
- 支持热更新

### 🛡️ 程序强健性

- 请求重试机制（指数退避）
- 结构化异常处理
- 可配置日志级别
- RGBA 透明度保持
- WebP 格式支持

### 💾 自动保存功能

- 生成图片自动保存到指定目录
- 可自定义命名格式（模型名、时间戳、seed 等）
- 支持 PNG/JPG/WebP 或保持原格式
- 按日期自动创建子文件夹
- API Manager 内可视化配置

### 🔄 预览持久化

- 重启 ComfyUI 后预览图片不丢失
- 自动从保存的文件恢复预览
- 详见 [docs/preview_persistence.md](docs/preview_persistence.md)

### 📊 模型排序

- 拖拽调整模型显示顺序
- 节点下拉框按配置顺序显示
- 顺序保存在 `api_config.yaml`

### 📐 节点宽度保持

- **可配置默认宽度** - 在 API Manager → 保存设置 Tab 中调整（300-1200px）
- 新建节点使用配置的默认宽度
- 切换模型后保持用户设置的宽度
- 保存/加载工作流后宽度正确恢复
- 详见 [docs/node_width_retrospective.md](docs/node_width_retrospective.md)

---

## 🚀 安装

1. 将本项目放入 ComfyUI `custom_nodes` 目录：

   ```
   ComfyUI/custom_nodes/ComfyUI-Custom-Batchbox/
   ```

2. 安装依赖：

   ```bash
   pip install pyyaml requests
   ```

3. **重启 ComfyUI**

---

## ⚙️ 配置指南

### 方式一：可视化配置（推荐）

1. 在 ComfyUI 菜单中找到 **Batchbox API Manager**
2. 配置供应商：
   - 名称（如 `bltcy_ai`）
   - Base URL（如 `https://api.bltcy.ai`）
   - API Key
3. 配置模型：
   - 选择类别（图片/文本/视频等）
   - 设置参数 Schema
   - 配置 API 端点

### 方式二：YAML 配置

编辑 `api_config.yaml`：

```yaml
# 1. 供应商配置
providers:
  bltcy_ai:
    base_url: "https://api.bltcy.ai"
    api_key: "sk-xxxxxxxx"

# 2. 模型配置
models:
  banana_pro:
    display_name: "🍌 Banana Pro"
    category: image
    parameter_schema:
      basic:
        prompt: { type: string, default: "" }
        style: 
          type: select
          default: realistic
          options:
            - { value: realistic, label: 写实风格 }
            - { value: anime, label: 动漫风格 }
    api_endpoints:
      - provider: bltcy_ai
        priority: 1
        modes:
          text2img:
            endpoint: "/v1/images/generations"
          img2img:
            endpoint: "/v1/images/edits"

# 3. 全局设置
settings:
  default_timeout: 600
  max_retries: 3
  auto_failover: true
```

---

## 📖 使用说明

### 1. 添加节点

在 ComfyUI 中搜索 `ComfyUI-Custom-Batchbox`，选择对应类型的节点。

### 2. 选择模型

从下拉菜单选择已配置的模型，参数面板会自动更新。

### 3. 连接输入

- **prompt**: 必填，提示词
- **image**: 可选，用于图生图

### 4. 执行

连接输出后执行工作流。

---

## 🔧 端点配置说明

### text2img vs img2img

每个模型可配置两种端点：

| 端点 | 用途 | 触发条件 |
|------|------|----------|
| text2img | 文生图 | 无图片输入 |
| img2img | 图生图 | 有图片输入 |

**配置规则：**

- 至少配置一个端点
- 如只配置一个，另一个自动使用相同端点

---

## 📁 项目结构

```
ComfyUI-Custom-Batchbox/
├── __init__.py          # 入口、API 端点注册
├── nodes.py             # 节点定义
├── config_manager.py    # 配置管理器（含缓存、验证）
├── batchbox_logger.py   # 日志与重试模块
├── errors.py            # 结构化异常类
├── image_utils.py       # 图片处理工具
├── api_config.yaml      # 配置文件
├── adapters/            # API 适配器
│   ├── base.py
│   ├── generic.py       # 通用适配器（层级配置 + 重试）
│   └── template_engine.py
├── web/                 # 前端资源
│   ├── api_manager.js
│   ├── api_manager.css
│   ├── dynamic_params.js
│   └── dynamic_inputs.js
├── tests/               # 单元测试
└── docs/                # 文档
```

---

## ❓ 常见问题

### Q: 节点加载失败？

**A:** 检查依赖是否安装：

```bash
pip install pyyaml requests
```

### Q: 自动切换供应商不生效？

**A:** 确保：

1. 配置了多个供应商
2. `settings.auto_failover` 设为 `true`
3. 各端点的供应商优先级正确设置

### Q: API Key 不显示？

**A:** 点击输入框旁边的 👁 按钮可以显示/隐藏。

---

## 📄 许可证

MIT License

## 🔗 相关链接

- [ComfyUI 官方仓库](https://github.com/comfyanonymous/ComfyUI)
