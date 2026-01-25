# ComfyUI Widget 序列化避坑指南

## 核心问题

ComfyUI 使用 `widgets_values` 数组**按索引**序列化和反序列化 widget 值。当前端动态创建 widgets 时，如果不正确处理，会导致：

1. **索引错位**：动态 widgets 挤占固定 widgets 的索引位置
2. **值错乱**：值被应用到错误的 widget（如端点名称出现在 prompt 字段）
3. **数据丢失**：用户输入的内容在重新加载后消失

## 解决方案

### 关键原则：动态 Widget 必须设置 `serialize = false`

所有前端动态创建的 widgets 都必须设置此属性：

```javascript
const widget = node.addWidget("combo", "my_widget", defaultValue, callback, options);
widget.serialize = false;  // 关键！不参与 widgets_values 序列化
```

### 需要设置 `serialize = false` 的场景

1. **从 Schema 动态创建的参数 widgets**（风格、分辨率、比例等）
2. **分组/折叠按钮**（如"高级设置"按钮）
3. **端点选择相关 widgets**（toggle、combo）
4. **隐藏的辅助 widgets**（如 `extra_params`）
5. **任何在 `INPUT_TYPES` 中未定义的 widget**

### 不能设置 `serialize = false` 的 widgets

后端 `INPUT_TYPES` 中定义的 required/optional inputs 对应的 widgets **不能**设置此属性，否则用户输入不会保存：
- `model`
- `prompt`
- `batch_count`
- `seed`

## 动态 Widget 值的保存与恢复

动态 widgets 的值通过自定义机制保存，**与 ComfyUI 机制隔离**：

```javascript
// 在 onSerialize 中保存
nodeType.prototype.onSerialize = function(o) {
  o.dynamicParams = this.collectDynamicParams();  // 自定义数据
  o.endpointState = { manualEnabled: ..., selectedEndpoint: ... };
};

// 在 onConfigure 中恢复
nodeType.prototype.onConfigure = function(o) {
  if (o.dynamicParams) {
    setTimeout(() => this.restoreDynamicParams(o.dynamicParams), 200);
  }
};
```

## 常见错误

### ❌ 错误：将动态 widget 移动到固定 widget 之间

```javascript
// 错误做法：会导致 null 占位符破坏索引
const toggleIdx = node.widgets.indexOf(toggleWidget);
node.widgets.splice(toggleIdx, 1);
node.widgets.splice(modelWidgetIdx + 1, 0, toggleWidget);  // 移动到中间
```

### ✅ 正确：保持动态 widgets 在数组末尾

```javascript
// 正确做法：动态 widgets 添加后保持在末尾
const widget = node.addWidget(...);
widget.serialize = false;
// 不要移动位置，让它留在末尾
```

### ❌ 错误：忘记设置 serialize = false

```javascript
// 错误做法
const widget = node.addWidget("combo", "style", "realistic", () => {});
widget._dynamicParam = true;  // 只标记了动态属性
// 缺少 widget.serialize = false;
```

### ✅ 正确：完整设置

```javascript
// 正确做法
const widget = node.addWidget("combo", "style", "realistic", () => {});
widget._dynamicParam = true;
widget.serialize = false;  // 关键！
```

## 调试技巧

1. **检查保存的 workflow JSON**：查看 `widgets_values` 数组长度是否与后端 `INPUT_TYPES` 定义的 widget 数量匹配
2. **检查 null 值**：如果 `widgets_values` 中有很多 `null`，说明动态 widgets 序列化了但没有值
3. **添加调试日志**：在 `onSerialize` 和 `onConfigure` 中打印 widget 状态

## 相关文件

- `web/dynamic_params.js`：动态参数管理器
- `nodes.py`：后端 `INPUT_TYPES` 定义

## 参考

- 修复 PR：端点选择持久化问题
- 日期：2026-01-25
