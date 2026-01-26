/**
 * @fileoverview Dynamic Parameter Renderer for ComfyUI-Custom-Batchbox
 *
 * This extension handles:
 * - Fetching parameter schemas for selected models
 * - Dynamically rendering parameter widgets
 * - Managing parameter dependencies
 * - Syncing with backend API
 * 
 * TABLE OF CONTENTS:
 * ------------------
 * 1. SCHEMA CACHE (Line ~25)
 * 2. WIDGET FACTORY (Line ~95)
 * 3. PARAMETER RENDERER (Line ~200)
 * 4. NODE MANAGEMENT (Line ~400)
 * 5. EXTENSION REGISTRATION (Line ~600)
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ================================================================
// SECTION 1: SCHEMA CACHE WITH TTL
// ================================================================

const schemaCache = new Map();
const CACHE_TTL_MS = 60000; // 60 seconds
let lastConfigMtime = 0;

// Cache entry: { data: any, timestamp: number }
function getCachedSchema(modelName) {
  const entry = schemaCache.get(modelName);
  if (!entry) return null;
  
  // Check TTL
  if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
    schemaCache.delete(modelName);
    return null;
  }
  return entry.data;
}

function setCachedSchema(modelName, data) {
  schemaCache.set(modelName, {
    data: data,
    timestamp: Date.now()
  });
}

function clearSchemaCache() {
  schemaCache.clear();
  console.log('[DynamicParams] Schema cache cleared');
}

async function checkConfigChanged() {
  try {
    const response = await api.fetchApi(`/api/batchbox/config/mtime?since=${lastConfigMtime}`);
    if (response.ok) {
      const data = await response.json();
      if (data.changed && lastConfigMtime > 0) {
        console.log('[DynamicParams] Config changed, clearing cache');
        clearSchemaCache();
      }
      lastConfigMtime = data.mtime;
      return data.changed;
    }
  } catch (e) {
    console.warn('[DynamicParams] Failed to check config mtime:', e);
  }
  return false;
}

async function fetchModelSchema(modelName, forceRefresh = false) {
  // Check if config changed on server (lightweight check)
  await checkConfigChanged();
  
  if (!forceRefresh) {
    const cached = getCachedSchema(modelName);
    if (cached) {
      return cached;
    }
  }

  try {
    const response = await api.fetchApi(`/api/batchbox/schema/${modelName}`);
    if (response.ok) {
      const data = await response.json();
      setCachedSchema(modelName, data);
      return data;
    }
  } catch (e) {
    console.error(
      `[DynamicParams] Failed to fetch schema for ${modelName}:`,
      e,
    );
  }
  return null;
}

// ================================================================
// SECTION 2: WIDGET FACTORY
// ================================================================

/**
 * Helper function to resize node while preserving user's custom width.
 * Only updates height based on computeSize(), keeps current width.
 * @param {Object} node - ComfyUI node instance
 */
function resizeNodePreservingWidth(node) {
  const currentWidth = node.size[0];
  const computedSize = node.computeSize();
  node.setSize([currentWidth, computedSize[1]]);
}

/**
 * Create a widget for a parameter definition.
 * @param {Object} node - ComfyUI node instance
 * @param {Object} paramDef - Parameter definition from schema
 * @param {Array} existingWidgets - List of existing widgets
 * @returns {Object|null} Created widget or existing widget
 */
function createWidget(node, paramDef, existingWidgets) {
  const name = paramDef.name;
  const type = paramDef.type;
  const label = paramDef.label || name;
  const defaultValue = paramDef.default;

  // Check if widget already exists
  const existingIdx = existingWidgets.findIndex((w) => w.name === name);
  if (existingIdx >= 0) {
    return existingWidgets[existingIdx];
  }

  let widget = null;

  switch (type) {
    case "select":
      const options = (paramDef.options || []).map((opt) =>
        typeof opt === "object" ? opt.value : opt,
      );
      widget = node.addWidget(
        "combo",
        name,
        defaultValue || options[0],
        (v) => {},
        { values: options },
      );
      break;

    case "boolean":
      widget = node.addWidget("toggle", name, defaultValue || false, (v) => {});
      break;

    case "number":
      widget = node.addWidget("number", name, defaultValue || 0, (v) => {}, {
        min: paramDef.min || 0,
        max: paramDef.max || 100,
        step: paramDef.step || 1,
        precision: 0,
      });
      break;

    case "string":
      if (paramDef.multiline) {
        // Multiline is typically handled as a required input, not widget
        // But we can still create a simple text widget
        widget = node.addWidget("text", name, defaultValue || "", (v) => {});
      } else {
        widget = node.addWidget("text", name, defaultValue || "", (v) => {});
      }
      break;

    case "slider":
      widget = node.addWidget(
        "slider",
        name,
        defaultValue || paramDef.min || 0,
        (v) => {},
        {
          min: paramDef.min || 0,
          max: paramDef.max || 100,
          step: paramDef.step || 1,
        },
      );
      break;

    default:
      widget = node.addWidget(
        "text",
        name,
        String(defaultValue || ""),
        (v) => {},
      );
  }

  if (widget) {
    widget._dynamicParam = true;
    widget._paramDef = paramDef;
    widget.serialize = false;  // CRITICAL: Don't participate in widgets_values serialization
  }

  return widget;
}

// ==========================================
// Dynamic Parameter Manager
// ==========================================
class DynamicParameterManager {
  constructor(node) {
    this.node = node;
    this.currentModel = null;
    this.dynamicWidgets = [];
    this.baseWidgets = [];
    this.collapsedGroups = new Set(["advanced"]);
  }

  async onModelChange(modelName) {
    if (modelName === this.currentModel) {
      return;
    }

    this.currentModel = modelName;
    console.log(`[DynamicParams] Model changed to: ${modelName}`);

    // Fetch schema
    const schemaData = await fetchModelSchema(modelName);
    if (!schemaData || !schemaData.flat_schema) {
      console.warn(`[DynamicParams] No schema found for ${modelName}`);
      return;
    }

    // Update visibility of seed-related widgets based on model setting
    const showSeedWidget = schemaData.show_seed_widget !== false;
    this.updateSeedWidgetVisibility(showSeedWidget);

    // Update endpoint selection options if available
    this.updateEndpointSelector(schemaData.endpoint_options);

    // Update widgets
    this.updateWidgets(schemaData.flat_schema);
  }

  updateEndpointSelector(endpointOptions) {
    // Remove existing endpoint widgets if they exist
    const existingManual = this.node.widgets?.find(w => w.name === "手动选择端点");
    const existingSelector = this.node.widgets?.find(w => w.name === "endpoint_selector");
    
    if (existingManual) {
      const idx = this.node.widgets.indexOf(existingManual);
      if (idx >= 0) this.node.widgets.splice(idx, 1);
    }
    if (existingSelector) {
      const idx = this.node.widgets.indexOf(existingSelector);
      if (idx >= 0) this.node.widgets.splice(idx, 1);
    }

    // If no endpoint options, skip
    if (!endpointOptions || endpointOptions.length < 2) {
      return;
    }

    // Build options list: only actual endpoint names (no auto option in manual mode)
    const options = endpointOptions.map(ep => ep.name);

    // Add toggle for manual selection FIRST (so it appears before selector visually)
    // CRITICAL: serialize=false to prevent ComfyUI index-based serialization issues
    // NOTE: We keep these widgets at end of array - moving them to middle causes
    // null placeholders in widgets_values which corrupts all widget indices
    const toggleWidget = this.node.addWidget("toggle", "手动选择端点", false, (v) => {
      if (selectorWidget) {
        selectorWidget.hidden = !v;
      }
      resizeNodePreservingWidth(this.node);
    });
    toggleWidget.serialize = false;  // Don't participate in widgets_values serialization

    // Add endpoint selector widget (hidden initially)
    const selectorWidget = this.node.addWidget("combo", "endpoint_selector", options[0], () => {}, {
      values: options
    });
    selectorWidget.hidden = true;
    selectorWidget.serialize = false;  // Don't participate in widgets_values serialization
    selectorWidget._endpointOptions = endpointOptions;

    // Update toggle callback to reference selectorWidget
    toggleWidget.callback = (v) => {
      selectorWidget.hidden = !v;
      resizeNodePreservingWidth(this.node);
    };

    resizeNodePreservingWidth(this.node);
  }

  updateSeedWidgetVisibility(visible) {
    // Find and update seed-related widgets
    const seedWidgetNames = ["seed", "control_after_generate", "生成后控制"];
    
    for (const widget of this.node.widgets || []) {
      if (seedWidgetNames.includes(widget.name)) {
        widget.hidden = !visible;
        console.log(`[DynamicParams] ${widget.name} visibility: ${visible}`);
      }
    }
    
    // Force node resize while preserving width
    resizeNodePreservingWidth(this.node);
  }

  updateWidgets(flatSchema) {
    // Remove old dynamic widgets
    this.removeDynamicWidgets();

    // Group parameters
    const groups = {};
    for (const param of flatSchema) {
      const group = param.group || "basic";
      if (!groups[group]) {
        groups[group] = [];
      }
      groups[group].push(param);
    }

    // Add widgets for each group
    for (const [groupName, params] of Object.entries(groups)) {
      // Add group separator if not basic
      if (groupName !== "basic" && params.length > 0) {
        this.addGroupSeparator(groupName);
      }

      for (const param of params) {
        // Skip prompt - it's a required input, not dynamic widget
        if (param.name === "prompt") {
          continue;
        }

        // Check dependencies
        if (param.depends_on) {
          // Will be handled by dependency system
        }

        const widget = createWidget(this.node, param, this.node.widgets || []);
        if (widget && widget._dynamicParam) {
          // Apply initial hidden state for collapsed groups
          if (groupName !== "basic" && this.collapsedGroups.has(groupName)) {
            widget.hidden = true;
          }
          this.dynamicWidgets.push(widget);
        }
      }
    }

    // Force node resize while preserving width
    resizeNodePreservingWidth(this.node);
  }

  addGroupSeparator(groupName) {
    // Check if this group is initially collapsed
    const isCollapsed = this.collapsedGroups.has(groupName);
    const prefix = isCollapsed ? "▶" : "▼";
    const label = groupName === "advanced" ? "高级设置" : groupName;
    const displayName = `${prefix} ${label}`;
    
    // In ComfyUI button widget, the second parameter (name) is what displays on the button
    const separator = this.node.addWidget(
      "button",
      displayName,  // This is the displayed text on button
      null,
      () => {
        this.toggleGroup(groupName);
      },
    );
    separator._dynamicParam = true;
    separator._isGroupHeader = true;
    separator._groupName = groupName;
    separator.serialize = false;  // CRITICAL: Don't participate in widgets_values serialization
    this.dynamicWidgets.push(separator);
  }

  toggleGroup(groupName) {
    if (this.collapsedGroups.has(groupName)) {
      this.collapsedGroups.delete(groupName);
    } else {
      this.collapsedGroups.add(groupName);
    }
    // Update visibility of group widgets
    this.updateGroupVisibility(groupName);
  }

  updateGroupVisibility(groupName) {
    let inGroup = false;

    for (const widget of this.dynamicWidgets) {
      if (widget._isGroupHeader && widget._groupName === groupName) {
        inGroup = true;
        // Update header text
        const collapsed = this.collapsedGroups.has(groupName);
        const prefix = collapsed ? "▶" : "▼";
        widget.name = `${prefix} ${groupName === "advanced" ? "高级设置" : groupName}`;
        continue;
      }

      if (widget._isGroupHeader) {
        inGroup = false;
        continue;
      }

      if (inGroup && widget._paramDef?.group === groupName) {
        widget.hidden = this.collapsedGroups.has(groupName);
      }
    }

    resizeNodePreservingWidth(this.node);
  }

  removeDynamicWidgets() {
    for (const widget of this.dynamicWidgets) {
      const idx = this.node.widgets.indexOf(widget);
      if (idx >= 0) {
        this.node.widgets.splice(idx, 1);
      }
    }
    this.dynamicWidgets = [];
  }

  collectDynamicParams() {
    const params = {};
    for (const widget of this.dynamicWidgets) {
      if (widget._paramDef && !widget._isGroupHeader) {
        // Use api_name if defined, otherwise use widget name
        const paramKey = widget._paramDef.api_name || widget.name;
        params[paramKey] = widget.value;
      }
    }
    
    // Include endpoint_override if manual selection is enabled
    const toggleWidget = this.node.widgets?.find(w => w.name === "手动选择端点");
    const selectorWidget = this.node.widgets?.find(w => w.name === "endpoint_selector");
    if (toggleWidget?.value && selectorWidget) {
      params["endpoint_override"] = selectorWidget.value;
    }
    
    return params;
  }
}

// ==========================================
// Generate Button Helper
// ==========================================
function randomizeSeedAndExecute(node) {
  // Find the seed widget and set it to a random value
  const seedWidget = node.widgets?.find((w) => w.name === "seed");

  if (seedWidget) {
    // Generate random seed (0 to 2147483647)
    const randomSeed = Math.floor(Math.random() * 2147483647);
    seedWidget.value = randomSeed;
    console.log(`[BatchBox] Randomized seed to: ${randomSeed}`);
  }

  // Find seed control widget (生成后控制) and set it to 'fixed'
  // This widget may be named differently in different ComfyUI versions
  const seedControlNames = ["control_after_generate", "生成后控制"];
  for (const controlName of seedControlNames) {
    const controlWidget = node.widgets?.find((w) => w.name === controlName);
    if (controlWidget) {
      controlWidget.value = "fixed";
      console.log(`[BatchBox] Set ${controlName} to fixed`);
      break;
    }
  }

  // Trigger execution to this node using ComfyUI's partial execution
  executeToNode(node);
}

/**
 * 递归收集节点及其所有上游依赖
 * @param {string} nodeId - 当前节点 ID
 * @param {Object} oldOutput - 原始的完整 prompt output
 * @param {Object} newOutput - 新的只包含需要执行节点的 output
 */
function recursiveAddNodes(nodeId, oldOutput, newOutput) {
  const currentId = String(nodeId);
  const currentNode = oldOutput[currentId];
  
  // 如果节点不存在或已经添加过，跳过
  if (!currentNode || newOutput[currentId] != null) {
    return;
  }
  
  // 添加当前节点
  newOutput[currentId] = currentNode;
  
  // 递归添加所有输入节点
  if (currentNode.inputs) {
    for (const inputValue of Object.values(currentNode.inputs)) {
      // 如果输入是数组，说明是来自其他节点的连接
      // 格式为 [upstream_node_id, output_slot]
      if (Array.isArray(inputValue)) {
        recursiveAddNodes(inputValue[0], oldOutput, newOutput);
      }
    }
  }
}

/**
 * 执行指定的输出节点（部分执行）
 * 只执行该节点及其上游依赖节点
 * @param {Object} node - 要执行的节点
 */
async function executeToNode(node) {
  const nodeIds = [node.id];
  const originalQueuePrompt = api.queuePrompt;
  
  // 临时替换 api.queuePrompt 以拦截和修改 prompt
  api.queuePrompt = async function(index, prompt) {
    if (nodeIds && nodeIds.length > 0 && prompt.output) {
      const oldOutput = prompt.output;
      const newOutput = {};
      
      // 为每个目标节点递归收集依赖
      for (const nodeId of nodeIds) {
        recursiveAddNodes(String(nodeId), oldOutput, newOutput);
      }
      
      // 替换 output 为只包含需要执行的节点
      prompt.output = newOutput;
      
      console.log("[BatchBox] Partial execution - original nodes:", Object.keys(oldOutput).length);
      console.log("[BatchBox] Partial execution - executing nodes:", Object.keys(newOutput).length);
    }
    
    // 调用原始方法
    const result = await originalQueuePrompt.apply(api, [index, prompt]);
    
    // 立即恢复原始方法
    api.queuePrompt = originalQueuePrompt;
    
    return result;
  };
  
  try {
    // 触发队列提交
    await app.queuePrompt();
  } catch (error) {
    console.error("[BatchBox] Execution error:", error);
    // 确保恢复原始方法
    api.queuePrompt = originalQueuePrompt;
  }
}

function addGenerateButton(node) {
  // Check if button already exists
  if (node.widgets?.find((w) => w._isGenerateButton)) {
    return;
  }

  // Add the generate button - use proper button widget API
  // In ComfyUI, button widget: addWidget("button", name, label, callback)
  // The 'name' is what shows on the button face
  const generateBtn = node.addWidget(
    "button",
    "▶ 开始生成",  // This is the displayed text on button
    null,
    () => {
      randomizeSeedAndExecute(node);
    },
  );

  // Mark the button
  generateBtn._isGenerateButton = true;

  // Move button to be after model/preset selector for better UX
  const widgets = node.widgets;
  const btnIndex = widgets.indexOf(generateBtn);
  if (btnIndex > 1) {
    // Move to position 1 (after model selector)
    widgets.splice(btnIndex, 1);
    widgets.splice(1, 0, generateBtn);
  }

  // Force node resize while preserving width
  resizeNodePreservingWidth(node);
}

// ==========================================
// Node Extension Registration
// ==========================================
app.registerExtension({
  name: "ComfyUI-Custom-Batchbox.DynamicParams",

  async beforeRegisterNodeDef(nodeType, nodeData, app) {
    // Apply to our dynamic nodes
    if (
      !nodeData.name.includes("DynamicImage") &&
      !nodeData.name.includes("NanoBananaPro")
    ) {
      return;
    }

    const origOnNodeCreated = nodeType.prototype.onNodeCreated;

    nodeType.prototype.onNodeCreated = function () {
      if (origOnNodeCreated) {
        origOnNodeCreated.apply(this, arguments);
      }

      // Add the "开始生成" button
      addGenerateButton(this);

      // Initialize dynamic parameter manager
      this._dynamicParamManager = new DynamicParameterManager(this);

      // Create hidden extra_params widget for passing dynamic params to backend
      const extraParamsWidget = this.addWidget("text", "extra_params", "{}", () => {});
      extraParamsWidget.hidden = true;
      extraParamsWidget.serialize = false; // Don't save to workflow

      // Find model widget and attach change handler
      const modelWidget = this.widgets?.find(
        (w) => w.name === "model" || w.name === "preset",
      );

      if (modelWidget) {
        const origCallback = modelWidget.callback;
        modelWidget.callback = async (value) => {
          if (origCallback) {
            origCallback.call(this, value);
          }
          await this._dynamicParamManager.onModelChange(value);
        };

        // Trigger initial load if value exists
        if (modelWidget.value) {
          setTimeout(() => {
            this._dynamicParamManager.onModelChange(modelWidget.value);
          }, 100);
        }
      }
      
      // Override to inject dynamic params before execution
      const node = this;
      this.onExecute = function() {
        // Update extra_params with current dynamic param values
        if (node._dynamicParamManager) {
          const dynamicParams = node._dynamicParamManager.collectDynamicParams();
          const ep = node.widgets?.find(w => w.name === "extra_params");
          if (ep) {
            ep.value = JSON.stringify(dynamicParams);
          }
        }
      };
      
      console.log('[DynamicParams] onNodeCreated END, prompt value:', this.widgets?.find(w => w.name === "prompt")?.value);
    };

    // Serialize dynamic params
    const origOnSerialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onSerialize = function (o) {
      if (origOnSerialize) {
        origOnSerialize.apply(this, arguments);
      }

      if (this._dynamicParamManager) {
        o.dynamicParams = this._dynamicParamManager.collectDynamicParams();
      }
      
      // Also save endpoint selection state
      const toggleWidget = this.widgets?.find(w => w.name === "手动选择端点");
      const selectorWidget = this.widgets?.find(w => w.name === "endpoint_selector");
      if (toggleWidget || selectorWidget) {
        o.endpointState = {
          manualEnabled: toggleWidget?.value || false,
          selectedEndpoint: selectorWidget?.value || ""
        };
      }
    };

    // Deserialize dynamic params
    const origOnConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (o) {
      if (origOnConfigure) {
        origOnConfigure.apply(this, arguments);
      }

      // Restore dynamic params after model loads
      if (o.dynamicParams && this._dynamicParamManager) {
        setTimeout(() => {
          for (const widget of this._dynamicParamManager.dynamicWidgets) {
            if (widget.name in o.dynamicParams) {
              widget.value = o.dynamicParams[widget.name];
            }
          }
        }, 200);
      }
      
      // Restore endpoint selection state
      if (o.endpointState) {
        setTimeout(() => {
          const toggleWidget = this.widgets?.find(w => w.name === "手动选择端点");
          const selectorWidget = this.widgets?.find(w => w.name === "endpoint_selector");
          
          if (toggleWidget && o.endpointState.manualEnabled) {
            toggleWidget.value = true;
            if (selectorWidget) {
              selectorWidget.hidden = false;
              if (o.endpointState.selectedEndpoint) {
                selectorWidget.value = o.endpointState.selectedEndpoint;
              }
            }
            resizeNodePreservingWidth(this);
          }
        }, 300);  // Slightly after dynamicParams restore
      }
    };
  },

});

// ==========================================
// Intercept queuePrompt to update extra_params before execution
// ==========================================
const origQueuePrompt = api.queuePrompt;
api.queuePrompt = async function(number, workflowData) {
  // Update extra_params for all dynamic nodes before sending to backend
  if (app.graph && app.graph._nodes) {
    for (const node of app.graph._nodes) {
      if (node._dynamicParamManager && node.widgets) {
        const extraParamsWidget = node.widgets.find(w => w.name === "extra_params");
        if (extraParamsWidget) {
          const dynamicParams = node._dynamicParamManager.collectDynamicParams();
          extraParamsWidget.value = JSON.stringify(dynamicParams);
          console.log(`[DynamicParams] node ${node.id} extra_params:`, extraParamsWidget.value);
        }
      }
    }
  }
  
  // Call original queuePrompt
  return origQueuePrompt.call(this, number, workflowData);
};

// ==========================================
// Utility: Expose API for other extensions
// ==========================================
window.BatchboxDynamicParams = {
  fetchModelSchema,
  schemaCache,
  DynamicParameterManager,
};

console.log("[ComfyUI-Custom-Batchbox] Dynamic parameter extension loaded");
