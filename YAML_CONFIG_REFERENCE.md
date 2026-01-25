# ComfyUI-Custom-Batchbox YAML 配置参考

> 本文档用于指导 LLM (大语言模型) 帮助用户配置 API 接入。
> 使用方法：将此文档 + 第三方 API 文档发送给 LLM，请求生成配置。

---

## 1. 配置文件位置

```
ComfyUI-Custom-Batchbox/api_config.yaml
```

---

## 2. 顶层结构

```yaml
providers:
  # 供应商配置（API 服务商）
  provider_name:
    base_url: https://api.example.com
    api_key: sk-xxxxx
    file_format: same_name  # 可选，默认文件格式
    file_field: image       # 可选，默认字段名

models:
  # 模型配置
  ModelDisplayName:
    display_name: 🎨 友好显示名
    category: image         # image | text | video | audio
    description: 模型描述
    show_seed_widget: true  # 是否显示 seed 控件
    dynamic_inputs:         # 可选，动态输入配置
      image:
        max: 14
        type: IMAGE
    parameter_schema:       # 参数定义
      basic: {}
      advanced: {}
    api_endpoints: []       # 端点列表

settings:
  auto_failover: true       # 自动故障转移
```

---

## 3. 供应商配置 (providers)

```yaml
providers:
  openai_compatible:
    base_url: https://api.openai.com
    api_key: sk-xxxxxx
    # 高级设置（可选）
    file_format: same_name   # 多文件格式，见下表
    file_field: image        # 文件字段名，默认 "image"
```

### file_format 选项

| 值 | 发送格式 | 适用 API |
|----|---------|----------|
| `same_name` | `('image', f1), ('image', f2)` | OpenAI, DALL-E, 大多数现代API |
| `indexed` | `('image[0]', f1), ('image[1]', f2)` | 某些 PHP 后端 |
| `array` | `('images[]', f1), ('images[]', f2)` | Rails 风格 |
| `numbered` | `('image1', f1), ('image2', f2)` | 传统 API |

---

## 4. 模型配置 (models)

### 4.1 基本信息

```yaml
models:
  Nano Banana Pro:
    display_name: 🍌 Nano Banana Pro
    category: image
    description: 高质量图片生成
    show_seed_widget: false  # 不显示 seed 控件
```

### 4.2 动态输入 (dynamic_inputs)

配置节点可以接收的动态输入槽：

```yaml
dynamic_inputs:
  image:           # 前缀名
    max: 14        # 最大数量
    type: IMAGE    # ComfyUI 类型
    label: 图片    # 显示标签
```

### 4.3 参数模式 (parameter_schema)

定义 UI 上显示的参数控件：

```yaml
parameter_schema:
  basic:
    # 文本输入
    prompt:
      type: string
      label: 提示词
      multiline: true
      required: true
      default: ""
    
    # 下拉选择
    风格:
      type: select
      label: 风格
      api_name: style        # 发送给 API 的参数名（可选）
      default: realistic
      options:
        - value: realistic
          label: 写实
        - value: anime
          label: 动漫
    
    # 数字输入
    steps:
      type: number
      label: 步数
      default: 20
      min: 1
      max: 100
    
    # 布尔开关
    enhance:
      type: boolean
      label: 增强
      default: true
  
  advanced:
    # 高级参数放这里，默认折叠
    guidance_scale:
      type: number
      default: 7.5
```

### 4.4 端点配置 (api_endpoints)

```yaml
api_endpoints:
  - display_name: 主线路           # 手动选择时显示的名称
    provider: openai_compatible    # 引用的供应商
    priority: 1                    # 优先级（数字越小越优先）
    model_name: dall-e-3           # 发送给 API 的 model 值
    
    modes:
      text2img:                    # 文生图模式
        endpoint: /v1/images/generations
        method: POST
        content_type: application/json
        response_type: sync        # sync 或 async
        response_path: data[0].url # 图片 URL 在响应中的路径
      
      img2img:                     # 图生图模式
        endpoint: /v1/images/edits
        method: POST
        content_type: multipart/form-data
        response_type: sync
        response_path: data[0].url
        file_format: same_name     # 可选，覆盖供应商设置
        file_field: image          # 可选，覆盖供应商设置
```

---

## 5. 响应类型详解

### 5.1 同步模式 (sync)

API 直接返回结果：

```yaml
response_type: sync
response_path: data[0].url
```

### 5.2 异步模式 (async)

API 返回任务 ID，需要轮询获取结果：

```yaml
response_type: async
task_id_path: task_id              # 任务 ID 路径
poll_endpoint: /v1/tasks/{task_id} # 轮询端点
poll_interval: 2                   # 轮询间隔（秒）
status_path: status                # 状态字段路径
success_value: completed           # 成功状态值
response_path: result.url          # 完成后图片 URL 路径
```

---

## 6. 完整示例

### 示例 1：OpenAI DALL-E 风格 API

```yaml
providers:
  my_api:
    base_url: https://api.example.com
    api_key: sk-xxxxxx

models:
  MyImageModel:
    display_name: 🎨 我的图像模型
    category: image
    description: 图像生成
    dynamic_inputs:
      image:
        max: 4
        type: IMAGE
    parameter_schema:
      basic:
        style:
          type: select
          default: vivid
          options:
            - value: vivid
              label: 生动
            - value: natural
              label: 自然
    api_endpoints:
      - provider: my_api
        priority: 1
        model_name: my-model-v1
        modes:
          text2img:
            endpoint: /v1/images/generations
            method: POST
            content_type: application/json
            response_type: sync
            response_path: data[0].url
          img2img:
            endpoint: /v1/images/edits
            method: POST
            content_type: multipart/form-data
            response_type: sync
            response_path: data[0].url
```

### 示例 2：异步 API

```yaml
api_endpoints:
  - provider: async_provider
    modes:
      text2img:
        endpoint: /api/generate
        method: POST
        content_type: application/json
        response_type: async
        task_id_path: data.task_id
        poll_endpoint: /api/task/{task_id}
        poll_interval: 3
        status_path: data.status
        success_value: SUCCESS
        response_path: data.images[0].url
```

---

## 7. LLM 配置指南

当拿到新的 API 文档时，请按以下步骤分析：

1. **确定 base_url** - API 的基础地址
2. **确定认证方式** - 通常是 Bearer Token (api_key)
3. **确定端点和方法** - 文生图/图生图的 URL 和 HTTP 方法
4. **确定请求格式** - JSON 还是 multipart/form-data
5. **分析响应格式** - 同步还是异步，图片 URL 在哪个字段
6. **分析参数** - 哪些参数可配置，类型和默认值

然后生成对应的 YAML 配置即可。
