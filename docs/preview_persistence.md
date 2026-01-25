# 预览持久化机制

## 功能描述

BatchBox 节点生成的图片预览在 ComfyUI 重启后仍能显示，解决了预览图消失的问题。

## 工作原理

### 保存流程

1. 生成图片时，`save_settings.py` 将图片保存到 `output/batchbox/` 目录
2. 返回预览信息到后端：`{"filename", "subfolder", "type": "output"}`
3. `nodes.py` 将预览信息作为 `ui._last_images` 返回
4. 前端 `onExecuted` 将信息保存到 `node.properties._last_images`
5. 用户保存工作流时，properties 随工作流 JSON 一起保存

### 恢复流程

1. 加载工作流时，前端 `loadedGraphNode` 被触发
2. 调用 `restorePreviewFromProperties()` 读取 `node.properties._last_images`
3. 解析 JSON，设置 `node.imgs` 和 `node.images`
4. 触发画布重绘，预览恢复显示

## 关键实现

### 后端 (nodes.py)

```python
# generate() 方法返回值
return {
    "ui": {
        "images": preview_results,
        "_last_images": [json.dumps(preview_results)]  # 前端保存此值
    },
    "result": (images_tensor, response_info, last_url)
}
```

### 前端 (dynamic_inputs.js)

```javascript
// onExecuted - 保存到 properties
node.onExecuted = function(message) {
    if (message && message._last_images && message._last_images[0]) {
        this.properties._last_images = message._last_images[0];
    }
};

// loadedGraphNode - 恢复预览
function restorePreviewFromProperties(node) {
    const images = JSON.parse(node.properties._last_images);
    node.imgs = images.map(img => {
        const url = `/view?filename=${img.filename}&subfolder=${img.subfolder}&type=${img.type}`;
        const imgEl = new Image();
        imgEl.src = url;
        return imgEl;
    });
    node.images = images;
    node.imageIndex = 0;
}
```

## 注意事项

- `OUTPUT_NODE = True` 是必须的，否则节点无法单独执行
- 预览图必须保存到非临时目录（如 output/），否则重启后文件被清除
- `node.properties` 是 LiteGraph 标准属性，自动序列化到工作流 JSON

## 相关文件

- [nodes.py](file:///Users/sansan/Documents/ComfyUI/custom_nodes/ComfyUI-Custom-Batchbox/nodes.py) - 后端节点实现
- [save_settings.py](file:///Users/sansan/Documents/ComfyUI/custom_nodes/ComfyUI-Custom-Batchbox/save_settings.py) - 图片保存逻辑
- [dynamic_inputs.js](file:///Users/sansan/Documents/ComfyUI/custom_nodes/ComfyUI-Custom-Batchbox/web/dynamic_inputs.js) - 前端预览恢复逻辑
