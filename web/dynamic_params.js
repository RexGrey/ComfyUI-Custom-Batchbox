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

// Flag to distinguish button-triggered execution from global Queue Prompt
// When true, BatchBox nodes are included in execution
// When false (default), BatchBox nodes are excluded from global Queue Prompt
let isButtonTriggeredExecution = false;

// Setting cache for bypass behavior (loaded from backend)
let bypassQueuePromptEnabled = true; // Default: enabled

// Fetch node settings from backend
async function fetchNodeSettings() {
  try {
    const resp = await api.fetchApi("/api/batchbox/node-settings");
    if (resp.ok) {
      const data = await resp.json();
      bypassQueuePromptEnabled = data.node_settings?.bypass_queue_prompt !== false;
      console.log(`[DynamicParams] bypass_queue_prompt setting: ${bypassQueuePromptEnabled}`);
    }
  } catch (e) {
    console.warn('[DynamicParams] Failed to fetch node settings:', e);
  }
}

// Load settings on startup
fetchNodeSettings();

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
  // Skip during restore to avoid intermediate layout changes
  if (node._isRestoring) {
    return;
  }
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

  async onModelChange(modelName, forceRefresh = false) {
    // Skip if same model UNLESS forceRefresh is requested (e.g., after config change)
    if (modelName === this.currentModel && !forceRefresh) {
      return;
    }

    this.currentModel = modelName;
    console.log(`[DynamicParams] Model changed to: ${modelName}${forceRefresh ? ' (forced refresh)' : ''}`);

    // Fetch schema (use forceRefresh when hot-reloading config)
    const schemaData = await fetchModelSchema(modelName, forceRefresh);
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
// Generate Button Helper (Independent Generation)
// ==========================================

/**
 * Set node generating state (button text and disabled state)
 * @param {Object} node - ComfyUI node
 * @param {boolean} isGenerating - Whether generation is in progress
 */
function setNodeGeneratingState(node, isGenerating) {
  const btn = node.widgets?.find(w => w._isGenerateButton);
  if (btn) {
    btn.name = isGenerating ? "⏳ 生成中..." : "▶ 开始生成";
    // Note: ComfyUI button widgets don't have a built-in disabled state
    // We'll track this via a custom flag
    btn._isGenerating = isGenerating;
  }
  node.setDirtyCanvas(true, true);
}

/**
 * Get source node from a link ID
 * @param {number} linkId - The link ID
 * @returns {Object|null} Source node
 */
function getSourceNode(linkId) {
  if (!linkId || !app.graph) return null;
  const link = app.graph.links[linkId];
  if (!link) return null;
  return app.graph.getNodeById(link.origin_id);
}

/**
 * Collect image inputs from connected nodes as base64
 * Supports LoadImage nodes and nodes with cached preview images
 * @param {Object} node - The node to collect images for
 * @returns {Promise<Array<string>>} Array of base64-encoded images
 */
async function collectImageInputsBase64(node) {
  const images = [];
  
  if (!node.inputs) return images;
  
  for (const input of node.inputs) {
    // Only process IMAGE type inputs that are connected
    if (!input.link || input.type !== "IMAGE") continue;
    
    const sourceNode = getSourceNode(input.link);
    if (!sourceNode) continue;
    
    console.log(`[BatchBox] Checking source node: ${sourceNode.type} (${sourceNode.id})`);
    
    // Case 1: LoadImage node - fetch directly from ComfyUI
    if (sourceNode.type === "LoadImage" || sourceNode.comfyClass === "LoadImage") {
      const imageWidget = sourceNode.widgets?.find(w => w.name === "image");
      if (imageWidget && imageWidget.value) {
        try {
          const filename = imageWidget.value;
          const url = `/view?filename=${encodeURIComponent(filename)}&type=input`;
          const response = await fetch(url);
          if (response.ok) {
            const blob = await response.blob();
            const base64 = await blobToBase64(blob);
            images.push(base64);
            console.log(`[BatchBox] Loaded image from LoadImage node: ${filename}`);
          }
        } catch (e) {
          console.error(`[BatchBox] Failed to load image from LoadImage:`, e);
        }
      }
    }
    // Case 2: Node has cached preview images (imgs array)
    else if (sourceNode.imgs && sourceNode.imgs.length > 0) {
      try {
        const img = sourceNode.imgs[0];
        const base64 = await imageElementToBase64(img);
        images.push(base64);
        console.log(`[BatchBox] Loaded cached image from node ${sourceNode.id}`);
      } catch (e) {
        console.error(`[BatchBox] Failed to get cached image:`, e);
      }
    }
    // Case 3: Node has images property (from ComfyUI execution)
    else if (sourceNode.images && sourceNode.images.length > 0) {
      try {
        const imgInfo = sourceNode.images[0];
        const url = `/view?filename=${encodeURIComponent(imgInfo.filename)}&subfolder=${encodeURIComponent(imgInfo.subfolder || "")}&type=${imgInfo.type || "output"}`;
        const response = await fetch(url);
        if (response.ok) {
          const blob = await response.blob();
          const base64 = await blobToBase64(blob);
          images.push(base64);
          console.log(`[BatchBox] Loaded image from node output`);
        }
      } catch (e) {
        console.error(`[BatchBox] Failed to load output image:`, e);
      }
    }
    // Case 4: Cannot get image - throw error with guidance
    else {
      throw new Error(`无法获取节点 "${sourceNode.title || sourceNode.type}" 的图片。请先执行一次工作流，以缓存该节点的输出。`);
    }
  }
  
  return images;
}

/**
 * Convert Blob to base64 data URL
 */
async function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/**
 * Convert Image element to base64 data URL
 */
async function imageElementToBase64(img) {
  return new Promise((resolve, reject) => {
    try {
      const canvas = document.createElement("canvas");
      canvas.width = img.naturalWidth || img.width;
      canvas.height = img.naturalHeight || img.height;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0);
      const base64 = canvas.toDataURL("image/png");
      resolve(base64);
    } catch (e) {
      reject(e);
    }
  });
}

/**
 * Collect all parameters from a node
 * @param {Object} node - The node
 * @returns {Object} Parameters object
 */
function collectNodeParams(node) {
  const params = {};
  
  if (!node.widgets) return params;
  
  for (const widget of node.widgets) {
    if (widget.name && !widget.name.startsWith("_")) {
      params[widget.name] = widget.value;
    }
  }
  
  // Collect dynamic params if available
  if (node._dynamicParamManager) {
    params.dynamicParams = node._dynamicParamManager.collectDynamicParams();
  }
  
  return params;
}

/**
 * Update node preview with generated images
 * @param {Object} node - The node
 * @param {Array} previewImages - Array of preview image info objects
 */
function updateNodePreview(node, previewImages) {
  if (!previewImages || previewImages.length === 0) return;
  
  console.log(`[BatchBox] Node ${node.id}: Loading ${previewImages.length} preview image(s)...`);
  
  // Set the images property (used by ComfyUI's OUTPUT_NODE mechanism)
  node.images = previewImages;
  node.imageIndex = 0;
  
  // Load images into imgs array for display
  node.imgs = [];
  let loadedCount = 0;
  
  previewImages.forEach((imgInfo, index) => {
    const url = `/view?filename=${encodeURIComponent(imgInfo.filename)}&subfolder=${encodeURIComponent(imgInfo.subfolder || "")}&type=${imgInfo.type || "output"}&t=${Date.now()}`;
    const img = new Image();
    
    img.onload = () => {
      loadedCount++;
      console.log(`[BatchBox] Node ${node.id}: Image ${loadedCount}/${previewImages.length} loaded`);
      
      // Force immediate redraw when image loads
      node.setDirtyCanvas(true, true);
      
      // Also trigger global graph redraw
      if (app.graph) {
        app.graph.setDirtyCanvas(true, true);
      }
    };
    
    img.onerror = () => {
      console.error(`[BatchBox] Node ${node.id}: Failed to load image ${index}`);
    };
    
    img.src = url;
    node.imgs.push(img);
  });
  
  // Save to properties for persistence
  if (!node.properties) {
    node.properties = {};
  }
  node.properties._last_images = JSON.stringify(previewImages);
  // Also save node size for proper restoration
  node.properties._last_size = JSON.stringify(node.size);
  
  // Force immediate redraw (even before images fully load)
  node.setDirtyCanvas(true, true);
  if (app.graph) {
    app.graph.setDirtyCanvas(true, true);
  }
  
  console.log(`[BatchBox] Node ${node.id}: Preview update initiated`);
}

/**
 * Independent generation - bypasses ComfyUI queue for concurrent execution
 * @param {Object} node - The node to generate for
 */
async function executeIndependent(node) {
  // Prevent double-click during generation
  const btn = node.widgets?.find(w => w._isGenerateButton);
  if (btn && btn._isGenerating) {
    console.log("[BatchBox] Generation already in progress, ignoring click");
    return;
  }
  
  // Set generating state
  setNodeGeneratingState(node, true);
  
  try {
    // Collect parameters
    const params = collectNodeParams(node);
    
    // Try to collect image inputs if any are connected
    let imagesBase64 = [];
    try {
      imagesBase64 = await collectImageInputsBase64(node);
    } catch (e) {
      // Show error to user via alert (since we can't use ComfyUI's toast easily)
      alert(e.message);
      setNodeGeneratingState(node, false);
      return;
    }
    
    // Build request
    const requestBody = {
      model: params.model || params.preset,
      prompt: params.prompt || "",
      seed: params.seed || 0,
      batch_count: params.batch_count || 1,
      extra_params: params.dynamicParams || {},
      images_base64: imagesBase64.length > 0 ? imagesBase64 : null,
      endpoint_override: params.dynamicParams?.endpoint_override || null
    };
    
    console.log("[BatchBox] Starting independent generation:", requestBody.model);
    
    // Call independent generation API
    const response = await api.fetchApi("/api/batchbox/generate-independent", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(requestBody)
    });
    
    const result = await response.json();
    
    if (result.success) {
      // Update node preview
      updateNodePreview(node, result.preview_images);
      console.log("[BatchBox] Generation complete:", result.response_info);
    } else {
      console.error("[BatchBox] Generation failed:", result.error);
      alert(`生成失败: ${result.error}`);
    }
    
  } catch (e) {
    console.error("[BatchBox] Independent generation error:", e);
    alert(`生成出错: ${e.message}`);
  } finally {
    // Reset generating state
    setNodeGeneratingState(node, false);
  }
}

/**
 * Randomize seed and execute independent generation
 * @param {Object} node - The node to execute
 */
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
  const seedControlNames = ["control_after_generate", "生成后控制"];
  for (const controlName of seedControlNames) {
    const controlWidget = node.widgets?.find((w) => w.name === controlName);
    if (controlWidget) {
      controlWidget.value = "fixed";
      console.log(`[BatchBox] Set ${controlName} to fixed`);
      break;
    }
  }

  // Use independent generation (bypasses ComfyUI queue)
  executeIndependent(node);
}

// Legacy functions kept for compatibility but no longer used by main flow
function recursiveAddNodes(nodeId, oldOutput, newOutput) {
  const currentId = String(nodeId);
  const currentNode = oldOutput[currentId];
  if (!currentNode || newOutput[currentId] != null) return;
  newOutput[currentId] = currentNode;
  if (currentNode.inputs) {
    for (const inputValue of Object.values(currentNode.inputs)) {
      if (Array.isArray(inputValue)) {
        recursiveAddNodes(inputValue[0], oldOutput, newOutput);
      }
    }
  }
}

async function executeToNode(node) {
  // Legacy: uses ComfyUI queue, kept for potential fallback
  const nodeIds = [node.id];
  const originalQueuePrompt = api.queuePrompt;
  
  api.queuePrompt = async function(index, prompt) {
    if (nodeIds && nodeIds.length > 0 && prompt.output) {
      const oldOutput = prompt.output;
      const newOutput = {};
      for (const nodeId of nodeIds) {
        recursiveAddNodes(String(nodeId), oldOutput, newOutput);
      }
      prompt.output = newOutput;
    }
    const result = await originalQueuePrompt.apply(api, [index, prompt]);
    api.queuePrompt = originalQueuePrompt;
    return result;
  };
  
  try {
    isButtonTriggeredExecution = true;
    await app.queuePrompt();
  } catch (error) {
    console.error("[BatchBox] Execution error:", error);
    api.queuePrompt = originalQueuePrompt;
  }
}

function addGenerateButton(node) {
  // Check if button already exists
  if (node.widgets?.find((w) => w._isGenerateButton)) {
    return;
  }

  // Add the generate button
  const generateBtn = node.addWidget(
    "button",
    "▶ 开始生成",
    null,
    () => {
      randomizeSeedAndExecute(node);
    },
  );

  // Mark the button
  generateBtn._isGenerateButton = true;
  generateBtn._isGenerating = false;

  // Move button to be after model/preset selector for better UX
  const widgets = node.widgets;
  const btnIndex = widgets.indexOf(generateBtn);
  if (btnIndex > 1) {
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
    // Apply to all BatchBox dynamic nodes
    const batchboxNodePatterns = [
      "DynamicImage",
      "DynamicVideo", 
      "DynamicText",
      "DynamicAudio",
      "NanoBananaPro"
    ];
    
    const isMatchingNode = batchboxNodePatterns.some(pattern => 
      nodeData.name.includes(pattern)
    );
    
    if (!isMatchingNode) {
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
// Intercept queuePrompt to update extra_params and handle BatchBox exclusion
// ==========================================
const origQueuePrompt = api.queuePrompt;
api.queuePrompt = async function(number, workflowData) {
  // Collect BatchBox node IDs for potential exclusion
  const batchboxNodeIds = new Set();
  
  // Update extra_params for all dynamic nodes before sending to backend
  if (app.graph && app.graph._nodes) {
    for (const node of app.graph._nodes) {
      if (node._dynamicParamManager && node.widgets) {
        // Track BatchBox nodes
        batchboxNodeIds.add(String(node.id));
        
        const extraParamsWidget = node.widgets.find(w => w.name === "extra_params");
        if (extraParamsWidget) {
          const dynamicParams = node._dynamicParamManager.collectDynamicParams();
          extraParamsWidget.value = JSON.stringify(dynamicParams);
          console.log(`[DynamicParams] node ${node.id} extra_params:`, extraParamsWidget.value);
        }
      }
    }
  }
  
  // Capture and reset the flag immediately
  const wasButtonTriggered = isButtonTriggeredExecution;
  isButtonTriggeredExecution = false;
  
  // If bypass is enabled AND NOT button-triggered (i.e., global Queue Prompt), exclude BatchBox nodes
  if (bypassQueuePromptEnabled && !wasButtonTriggered && batchboxNodeIds.size > 0 && workflowData?.output) {
    console.log(`[BatchBox] Global Queue Prompt detected, excluding ${batchboxNodeIds.size} BatchBox node(s)`);
    
    // Remove BatchBox nodes from the prompt output
    for (const nodeId of batchboxNodeIds) {
      if (workflowData.output[nodeId]) {
        delete workflowData.output[nodeId];
        console.log(`[BatchBox] Excluded node ${nodeId} from execution`);
      }
    }
    
    // Check if any nodes remain
    if (Object.keys(workflowData.output).length === 0) {
      console.log(`[BatchBox] No nodes left to execute after exclusion`);
      return { error: "No nodes to execute (BatchBox nodes are only triggered by their Generate button)" };
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
  clearSchemaCache,  // Expose for external refresh
};

// Listen for settings changes from Manager
window.addEventListener("batchbox:node-settings-changed", () => {
  console.log("[DynamicParams] Reloading node settings...");
  fetchNodeSettings();
});

// Listen for config changes from API Manager - Hot Reload!
window.addEventListener("batchbox:config-changed", async () => {
  console.log("[DynamicParams] Config changed, refreshing all BatchBox nodes...");
  
  // 1. Clear schema cache to force fresh fetch
  clearSchemaCache();
  
  // 2. Reload node settings (for bypass_queue_prompt etc)
  await fetchNodeSettings();
  
  // 3. Fetch updated model lists from backend for each category
  const categoryMap = {
    "DynamicImageGeneration": "image",
    "DynamicTextGeneration": "text",
    "DynamicVideoGeneration": "video",
    "DynamicAudioGeneration": "audio",
    "DynamicImageEditor": "image_editor",
    "NanoBananaPro": null  // Uses all models (presets)
  };
  
  const modelListCache = {};  // Cache fetched model lists by category
  
  async function fetchModelsForCategory(category) {
    if (modelListCache[category]) {
      return modelListCache[category];
    }
    try {
      const url = category ? `/api/batchbox/models?category=${category}` : "/api/batchbox/models";
      const resp = await api.fetchApi(url);
      if (resp.ok) {
        const data = await resp.json();
        const models = data.models || [];
        // Build display name -> model name mapping and options list
        const result = {
          names: models.map(m => m.name),
          displayNames: models.map(m => m.display_name || m.name),
          nameToDisplay: {}
        };
        models.forEach(m => {
          result.nameToDisplay[m.name] = m.display_name || m.name;
        });
        modelListCache[category || "all"] = result;
        return result;
      }
    } catch (e) {
      console.warn(`[DynamicParams] Failed to fetch models for ${category}:`, e);
    }
    return null;
  }
  
  // 4. Refresh all BatchBox nodes in the canvas
  if (app.graph && app.graph._nodes) {
    const batchboxNodeTypes = Object.keys(categoryMap);
    
    for (const node of app.graph._nodes) {
      if (!batchboxNodeTypes.includes(node.type)) continue;
      
      const category = categoryMap[node.type];
      const modelWidget = node.widgets?.find(w => w.name === "model" || w.name === "preset");
      
      if (modelWidget) {
        // Fetch updated model list for this category
        const modelData = await fetchModelsForCategory(category);
        
        if (modelData && modelData.names.length > 0) {
          const currentValue = modelWidget.value;
          
          // Update widget options
          if (modelWidget.options) {
            modelWidget.options.values = modelData.names;
          }
          
          // If current value is still valid, keep it; otherwise select first
          if (!modelData.names.includes(currentValue)) {
            modelWidget.value = modelData.names[0];
            console.log(`[DynamicParams] Node ${node.id}: Model "${currentValue}" no longer exists, switched to "${modelWidget.value}"`);
          }
          
          console.log(`[DynamicParams] Node ${node.id}: Updated model options (${modelData.names.length} models)`);
        }
        
        // Also refresh dynamic parameters
        if (node._dynamicParamManager && modelWidget.value) {
          await node._dynamicParamManager.onModelChange(modelWidget.value, true);
        }
      }
    }
    
    // Redraw canvas
    app.graph.setDirtyCanvas(true, true);
  }
  
  console.log("[DynamicParams] Hot reload complete!");
});

console.log("[ComfyUI-Custom-Batchbox] Dynamic parameter extension loaded");

