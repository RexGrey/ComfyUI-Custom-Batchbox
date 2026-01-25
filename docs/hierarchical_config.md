# 层级配置指南

## 概述

ComfyUI-Custom-Batchbox 支持三级配置层级，配置会按优先级从高到低查找：

```
Mode 级 (modes.text2img) > Endpoint 级 (api_endpoints[]) > Provider 级 (providers[])
```

## 配置层级示意

```yaml
providers:
  bltcy_ai:
    file_format: indexed       # Provider 级默认
    file_field: image
    
models:
  my_model:
    api_endpoints:
      - provider: bltcy_ai
        file_format: array     # Endpoint 级覆盖
        modes:
          text2img:
            file_format: numbered  # Mode 级最高优先级
          img2img:
            # 未设置，继承 Endpoint 级: array
```

## 支持的层级配置项

| 配置项 | 说明 | 可选值 |
|--------|------|--------|
| `file_format` | 多图片上传字段命名格式 | `same_name`, `indexed`, `array`, `numbered` |
| `file_field` | 图片字段名 | 默认 `image` |
| `content_type` | HTTP Content-Type | `application/json`, `multipart/form-data` |
| `response_path` | 响应数据提取路径 | 如 `data[0].url` |
| `response_type` | 响应类型 | `sync`, `async` |

## 文件格式详解

### `file_format` 选项

| 值 | 请求格式 | 使用场景 |
|----|----------|----------|
| `same_name` | `image=file1, image=file2` | 标准多值字段 |
| `indexed` | `image[0]=file1, image[1]=file2` | 索引序列 |
| `array` | `images[]=file1, images[]=file2` | 数组格式 |
| `numbered` | `image1=file1, image2=file2` | 编号命名 |

### 配置示例

```yaml
# Provider 级设置（所有使用该 provider 的 endpoint 默认继承）
providers:
  my_provider:
    file_format: indexed
    file_field: images

# Endpoint 级覆盖
api_endpoints:
  - provider: my_provider
    file_format: array  # 覆盖 provider 的 indexed

# Mode 级覆盖
    modes:
      img2img:
        file_format: numbered  # 覆盖 endpoint 的 array
        file_field: reference  # 覆盖默认字段名
```

## 读取逻辑（代码实现）

```python
# adapters/generic.py
file_format = (
    self.mode_config.get("file_format") or
    self.endpoint.get("file_format") or
    self.provider.get("file_format") or
    "same_name"  # 系统默认
)

file_field = (
    self.mode_config.get("file_field") or
    self.endpoint.get("file_field") or
    self.provider.get("file_field") or
    "image"  # 系统默认
)
```

## Chat API 特殊配置

对于 Chat API 格式（`/v1/chat/completions`），使用 `_chat_content` 模板变量自动处理：

```yaml
modes:
  text2img:
    endpoint: /v1/chat/completions
    payload_template:
      model: "{{model}}"
      stream: false
      messages:
        - role: user
          content: "{{_chat_content}}"  # 自动包含 prompt + base64 图片
    response_path: choices[0].message.content
```

### `_chat_content` 生成格式

```json
[
  {"type": "text", "text": "用户的 prompt"},
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0..."}},
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]
```

## 最佳实践

1. **Provider 级**：设置该 API 供应商的通用默认值
2. **Endpoint 级**：针对特定端点的覆盖配置
3. **Mode 级**：针对 text2img/img2img 的精细配置

4. **继承原则**：只在需要覆盖时才设置，减少重复配置
