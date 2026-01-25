# ComfyUI 节点默认宽度功能 - 开发复盘

## 功能需求
- 用户可以在 API Manager 中设置 BatchBox 节点的默认宽度
- **新建节点**时使用设置的默认宽度
- **保存/加载工作流**时保留用户手动调整的尺寸

---

## 踩过的坑

### 1. 后端保存问题
**问题**：节点设置（`node_settings.default_width`）没有被保存到配置文件

**原因**：
- `save_settings.py` 中的 `save_node_settings` 函数没有正确调用 `ConfigManager.update_section()`
- 或者保存后 `api_config.yaml` 中确实有数据，但前端缓存导致看不到更新

**解决方案**：确保 `save_node_settings` 正确调用 `config_manager.update_section("node_settings", settings)`

---

### 2. 前端缓存问题
**问题**：保存后新建节点仍使用旧的默认宽度

**原因**：`dynamic_inputs.js` 中的 `getNodeSettings()` 函数使用了 `nodeSettingsCache` 变量缓存设置，保存后缓存没有失效

**错误代码**：
```javascript
let nodeSettingsCache = null;
async function getNodeSettings() {
    if (nodeSettingsCache !== null) {
        return nodeSettingsCache;  // 永远返回第一次加载的值
    }
    // ...
}
```

**解决方案**：
1. 移除缓存，每次都从 API 获取
2. 或保存后通知前端清除缓存

---

### 3. nodeCreated vs loadedGraphNode 执行顺序
**问题**：无法区分"用户手动添加节点"和"从工作流加载节点"

**ComfyUI 执行顺序**：
1. `nodeCreated(node)` - 节点对象创建时调用（**两种情况都会调用**）
2. `loadedGraphNode(node)` - 仅在加载工作流时调用（在 nodeCreated 之后）

**关键点**：
- 加载工作流时，`nodeCreated` 会先于 `loadedGraphNode` 被调用
- 无法在 `nodeCreated` 中判断节点是新建还是加载的

---

### 4. setSize/computeSize 覆盖宽度
**问题**：即使设置了默认宽度，节点仍然显示为 ~350px

**原因**：`addDynamicInput()` 和 `removeDynamicInput()` 函数内部调用：
```javascript
node.setSize(node.computeSize());  // computeSize() 返回 ~350px
```

这会在初始化动态输入时覆盖我们设置的默认宽度

**解决方案**：保留宽度，只调整高度：
```javascript
const computedSize = node.computeSize();
node.setSize([Math.max(node.size[0], computedSize[0]), computedSize[1]]);
```

---

### 5. 竞态条件（Race Condition）
**问题**：设置默认宽度后，其他 ComfyUI 初始化代码覆盖了宽度

**尝试过的方案**：
- `requestAnimationFrame` - 太快，被后续代码覆盖
- `setTimeout(100ms)` - 不够可靠
- `setTimeout(300-500ms)` - 可能有效但用户体验差（会看到闪烁）

---

### 6. isLoadingWorkflow 全局标志失效
**问题**：使用全局 `isLoadingWorkflow` 标志区分加载/新建节点失败

**原因**：
- `setup()` 中覆盖 `app.graph.configure` 的时机可能不对
- 或者 `loadedGraphNode` 在 `nodeCreated` 之后才被调用，标志设置太晚

---

### 7. 用硬编码宽度判断是否新节点
**问题**：用 `initialWidth < 400` 判断是否新节点

**原因**：这是 hack 方案，不可靠：
- 如果用户的默认宽度设置为 380，就会误判
- 如果 ComfyUI 默认宽度改变，就会失效

---

## 正确实现思路

### 核心问题
ComfyUI 的节点尺寸保存/加载机制：
1. 工作流 JSON 中保存节点的 `size: [width, height]`
2. 加载时 ComfyUI 会自动恢复 `size`
3. 但 `nodeCreated` 和 `initializeDynamicInputs` 中的 `setSize()` 调用会覆盖它

---

## ✅ 最终解决方案（2026-01-25 验证通过）

### 核心原则
**永远不要直接调用 `setSize(computeSize())`**，应保持当前宽度，只更新高度。

### 1. 创建辅助函数

在 `dynamic_params.js` 中添加：

```javascript
function resizeNodePreservingWidth(node) {
  const currentWidth = node.size[0];
  const computedSize = node.computeSize();
  node.setSize([currentWidth, computedSize[1]]);
}
```

### 2. 修改动态输入函数

在 `dynamic_inputs.js` 中：

```javascript
function addDynamicInput(node, prefix, index, inputType) {
    const currentWidth = node.size[0];  // 保存当前宽度
    node.addInput(`${prefix}${index}`, inputType);
    const computedSize = node.computeSize();
    node.setSize([currentWidth, computedSize[1]]);  // 恢复宽度
}

function updateInputsForType(node, prefix, inputType, maxInputs) {
    const currentWidth = node.size[0];  // 保存当前宽度
    // ... 添加/删除输入 ...
    const computedSize = node.computeSize();
    node.setSize([currentWidth, computedSize[1]]);  // 恢复宽度
}
```

### 3. 区分新建节点和加载节点

```javascript
async nodeCreated(node) {
    node._fresh_create = true;
    setTimeout(async () => {
        if (node._fresh_create) {
            // 仅新建节点使用默认宽度
            node.size = [DEFAULT_WIDTH, node.computeSize()[1]];
        }
        delete node._fresh_create;
        await initializeNode(node);
    }, 50);
},

async loadedGraphNode(node) {
    node._fresh_create = false;  // 清除标记
    const savedWidth = node.size[0];  // 保存工作流中的宽度
    setTimeout(async () => {
        await initializeNode(node);
        node.size = [savedWidth, node.computeSize()[1]];  // 恢复保存的宽度
    }, 100);
}
```

### 4. 替换所有 setSize(computeSize()) 调用

在 `dynamic_params.js` 中搜索并替换以下位置：
- `updateEndpointSelector`
- `updateSeedWidgetVisibility`
- `updateWidgets`
- `updateGroupVisibility`
- `addGenerateButton`
- `onConfigure`

全部改为使用 `resizeNodePreservingWidth(node)`。

---

## 验证清单

- [x] 新建节点使用默认宽度（500px）
- [x] 切换模型/预设后宽度不变
- [x] 手动调整宽度后切换模型仍保持
- [x] 保存/加载工作流后宽度正确恢复
- [x] 无宽度"闪烁"现象

---

## 相关文件

| 文件 | 修改内容 |
|------|----------|
| `web/dynamic_inputs.js` | `addDynamicInput`, `removeDynamicInput`, `updateInputsForType`, 生命周期钩子 |
| `web/dynamic_params.js` | 添加 `resizeNodePreservingWidth`, 替换 7 处 `setSize(computeSize())` |
| `save_settings.py` | 后端保存逻辑 |
| `config_manager.py` | 配置管理 |
| `api_config.yaml` | 配置文件 |

