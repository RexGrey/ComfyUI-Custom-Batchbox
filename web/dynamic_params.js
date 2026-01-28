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

/**
 * Compute MD5 hash of a string (for cache key matching with backend)
 * Uses a simple MD5 implementation since Web Crypto doesn't support MD5
 */
async function computeMD5Hash(str) {
  // Simple MD5 implementation for browser
  function md5cycle(x, k) {
    var a = x[0], b = x[1], c = x[2], d = x[3];
    a = ff(a, b, c, d, k[0], 7, -680876936);
    d = ff(d, a, b, c, k[1], 12, -389564586);
    c = ff(c, d, a, b, k[2], 17, 606105819);
    b = ff(b, c, d, a, k[3], 22, -1044525330);
    a = ff(a, b, c, d, k[4], 7, -176418897);
    d = ff(d, a, b, c, k[5], 12, 1200080426);
    c = ff(c, d, a, b, k[6], 17, -1473231341);
    b = ff(b, c, d, a, k[7], 22, -45705983);
    a = ff(a, b, c, d, k[8], 7, 1770035416);
    d = ff(d, a, b, c, k[9], 12, -1958414417);
    c = ff(c, d, a, b, k[10], 17, -42063);
    b = ff(b, c, d, a, k[11], 22, -1990404162);
    a = ff(a, b, c, d, k[12], 7, 1804603682);
    d = ff(d, a, b, c, k[13], 12, -40341101);
    c = ff(c, d, a, b, k[14], 17, -1502002290);
    b = ff(b, c, d, a, k[15], 22, 1236535329);
    a = gg(a, b, c, d, k[1], 5, -165796510);
    d = gg(d, a, b, c, k[6], 9, -1069501632);
    c = gg(c, d, a, b, k[11], 14, 643717713);
    b = gg(b, c, d, a, k[0], 20, -373897302);
    a = gg(a, b, c, d, k[5], 5, -701558691);
    d = gg(d, a, b, c, k[10], 9, 38016083);
    c = gg(c, d, a, b, k[15], 14, -660478335);
    b = gg(b, c, d, a, k[4], 20, -405537848);
    a = gg(a, b, c, d, k[9], 5, 568446438);
    d = gg(d, a, b, c, k[14], 9, -1019803690);
    c = gg(c, d, a, b, k[3], 14, -187363961);
    b = gg(b, c, d, a, k[8], 20, 1163531501);
    a = gg(a, b, c, d, k[13], 5, -1444681467);
    d = gg(d, a, b, c, k[2], 9, -51403784);
    c = gg(c, d, a, b, k[7], 14, 1735328473);
    b = gg(b, c, d, a, k[12], 20, -1926607734);
    a = hh(a, b, c, d, k[5], 4, -378558);
    d = hh(d, a, b, c, k[8], 11, -2022574463);
    c = hh(c, d, a, b, k[11], 16, 1839030562);
    b = hh(b, c, d, a, k[14], 23, -35309556);
    a = hh(a, b, c, d, k[1], 4, -1530992060);
    d = hh(d, a, b, c, k[4], 11, 1272893353);
    c = hh(c, d, a, b, k[7], 16, -155497632);
    b = hh(b, c, d, a, k[10], 23, -1094730640);
    a = hh(a, b, c, d, k[13], 4, 681279174);
    d = hh(d, a, b, c, k[0], 11, -358537222);
    c = hh(c, d, a, b, k[3], 16, -722521979);
    b = hh(b, c, d, a, k[6], 23, 76029189);
    a = hh(a, b, c, d, k[9], 4, -640364487);
    d = hh(d, a, b, c, k[12], 11, -421815835);
    c = hh(c, d, a, b, k[15], 16, 530742520);
    b = hh(b, c, d, a, k[2], 23, -995338651);
    a = ii(a, b, c, d, k[0], 6, -198630844);
    d = ii(d, a, b, c, k[7], 10, 1126891415);
    c = ii(c, d, a, b, k[14], 15, -1416354905);
    b = ii(b, c, d, a, k[5], 21, -57434055);
    a = ii(a, b, c, d, k[12], 6, 1700485571);
    d = ii(d, a, b, c, k[3], 10, -1894986606);
    c = ii(c, d, a, b, k[10], 15, -1051523);
    b = ii(b, c, d, a, k[1], 21, -2054922799);
    a = ii(a, b, c, d, k[8], 6, 1873313359);
    d = ii(d, a, b, c, k[15], 10, -30611744);
    c = ii(c, d, a, b, k[6], 15, -1560198380);
    b = ii(b, c, d, a, k[13], 21, 1309151649);
    a = ii(a, b, c, d, k[4], 6, -145523070);
    d = ii(d, a, b, c, k[11], 10, -1120210379);
    c = ii(c, d, a, b, k[2], 15, 718787259);
    b = ii(b, c, d, a, k[9], 21, -343485551);
    x[0] = add32(a, x[0]);
    x[1] = add32(b, x[1]);
    x[2] = add32(c, x[2]);
    x[3] = add32(d, x[3]);
  }
  function cmn(q, a, b, x, s, t) {
    a = add32(add32(a, q), add32(x, t));
    return add32((a << s) | (a >>> (32 - s)), b);
  }
  function ff(a, b, c, d, x, s, t) { return cmn((b & c) | ((~b) & d), a, b, x, s, t); }
  function gg(a, b, c, d, x, s, t) { return cmn((b & d) | (c & (~d)), a, b, x, s, t); }
  function hh(a, b, c, d, x, s, t) { return cmn(b ^ c ^ d, a, b, x, s, t); }
  function ii(a, b, c, d, x, s, t) { return cmn(c ^ (b | (~d)), a, b, x, s, t); }
  function md51(s) {
    var n = s.length, state = [1732584193, -271733879, -1732584194, 271733878], i;
    for (i = 64; i <= n; i += 64) { md5cycle(state, md5blk(s.substring(i - 64, i))); }
    s = s.substring(i - 64);
    var tail = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0];
    for (i = 0; i < s.length; i++) { tail[i >> 2] |= s.charCodeAt(i) << ((i % 4) << 3); }
    tail[i >> 2] |= 0x80 << ((i % 4) << 3);
    if (i > 55) { md5cycle(state, tail); tail = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]; }
    tail[14] = n * 8;
    md5cycle(state, tail);
    return state;
  }
  function md5blk(s) {
    var md5blks = [], i;
    for (i = 0; i < 64; i += 4) {
      md5blks[i >> 2] = s.charCodeAt(i) + (s.charCodeAt(i + 1) << 8) + (s.charCodeAt(i + 2) << 16) + (s.charCodeAt(i + 3) << 24);
    }
    return md5blks;
  }
  var hex_chr = '0123456789abcdef'.split('');
  function rhex(n) {
    var s = '', j = 0;
    for (; j < 4; j++) { s += hex_chr[(n >> (j * 8 + 4)) & 0x0F] + hex_chr[(n >> (j * 8)) & 0x0F]; }
    return s;
  }
  function hex(x) { for (var i = 0; i < x.length; i++) { x[i] = rhex(x[i]); } return x.join(''); }
  function add32(a, b) { return (a + b) & 0xFFFFFFFF; }
  return hex(md51(str));
}

// Flag to distinguish button-triggered execution from global Queue Prompt
// When true, BatchBox nodes are included in execution
// When false (default), BatchBox nodes are excluded from global Queue Prompt
let isButtonTriggeredExecution = false;

// Setting cache for bypass behavior (loaded from backend)
let bypassQueuePromptEnabled = true; // Default: enabled
let showInCanvasMenuEnabled = true; // Default: enabled (show BatchBox nodes in canvas right-click menu)
let smartCacheHashCheckEnabled = true; // Default: enabled (check param hash for cache invalidation)

// Fetch node settings from backend
async function fetchNodeSettings() {
  try {
    const resp = await api.fetchApi("/api/batchbox/node-settings");
    if (resp.ok) {
      const data = await resp.json();
      bypassQueuePromptEnabled = data.node_settings?.bypass_queue_prompt !== false;
      showInCanvasMenuEnabled = data.node_settings?.show_in_canvas_menu !== false;
      smartCacheHashCheckEnabled = data.node_settings?.smart_cache_hash_check !== false;
      console.log(`[DynamicParams] bypass_queue_prompt: ${bypassQueuePromptEnabled}, smart_cache_hash_check: ${smartCacheHashCheckEnabled}`);
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
 * @param {Object} pendingParams - Optional saved params to restore (prevents flash)
 * @returns {Object|null} Created widget or existing widget
 */
function createWidget(node, paramDef, existingWidgets, pendingParams = null) {
  const name = paramDef.name;
  const type = paramDef.type;
  const label = paramDef.label || name;
  
  // Determine initial value: check pendingParams first (for restoration), then use default
  // pendingParams uses api_name as key, so check both api_name and widget name
  const apiName = paramDef.api_name;
  let initialValue = paramDef.default;
  
  if (pendingParams) {
    const paramKey = apiName || name;
    if (paramKey in pendingParams) {
      initialValue = pendingParams[paramKey];
      console.log(`[DynamicParams] Creating ${name} with restored value: ${initialValue}`);
    } else if (name in pendingParams) {
      initialValue = pendingParams[name];
      console.log(`[DynamicParams] Creating ${name} with restored value (legacy): ${initialValue}`);
    }
  }

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
        initialValue || options[0],
        (v) => {},
        { values: options },
      );
      break;

    case "boolean":
      // Handle boolean: could be string "true"/"false" or actual boolean
      let boolValue = initialValue;
      if (typeof boolValue === "string") {
        boolValue = boolValue === "true";
      }
      widget = node.addWidget("toggle", name, boolValue || false, (v) => {});
      break;

    case "number":
      widget = node.addWidget("number", name, initialValue || 0, (v) => {}, {
        min: paramDef.min || 0,
        max: paramDef.max || 100,
        step: paramDef.step || 1,
        precision: 0,
      });
      break;

    case "string":
      if (paramDef.multiline) {
        widget = node.addWidget("text", name, initialValue || "", (v) => {});
      } else {
        widget = node.addWidget("text", name, initialValue || "", (v) => {});
      }
      break;

    case "slider":
      widget = node.addWidget(
        "slider",
        name,
        initialValue || paramDef.min || 0,
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
        String(initialValue || ""),
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
    
    // Check for pending endpoint state (set by onConfigure before widgets exist)
    // This allows creating widgets with correct initial values, preventing UI flash
    const pendingState = this.node._pendingEndpointState;
    const initialManualEnabled = pendingState?.manualEnabled || false;
    const initialEndpoint = pendingState?.selectedEndpoint || options[0];
    
    if (pendingState) {
      console.log(`[DynamicParams] Creating endpoint widgets with restored state: manual=${initialManualEnabled}, endpoint=${initialEndpoint}`);
      // Clear after consumption
      delete this.node._pendingEndpointState;
    }

    // Add toggle for manual selection with correct initial value
    const toggleWidget = this.node.addWidget("toggle", "手动选择端点", initialManualEnabled, (v) => {
      if (selectorWidget) {
        selectorWidget.hidden = !v;
      }
      resizeNodePreservingWidth(this.node);
    });
    toggleWidget.serialize = false;  // Don't participate in widgets_values serialization

    // Add endpoint selector widget with correct initial value and visibility
    const selectorWidget = this.node.addWidget("combo", "endpoint_selector", initialEndpoint, () => {}, {
      values: options
    });
    selectorWidget.hidden = !initialManualEnabled;  // Show if manual was enabled
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
    
    // Get pending params for restoration (set by onConfigure before widgets exist)
    // This allows creating widgets with correct initial values, preventing "flash"
    const pendingParams = this.node._pendingDynamicParams;
    if (pendingParams) {
      console.log('[DynamicParams] Found pending params to restore:', Object.keys(pendingParams));
      // Clear after consumption to prevent re-use
      delete this.node._pendingDynamicParams;
    }

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

        // Pass pendingParams to create widget with correct initial value
        const widget = createWidget(this.node, param, this.node.widgets || [], pendingParams);
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
function updateNodePreview(node, previewImages, paramsHash = null) {
  if (!previewImages || previewImages.length === 0) return;
  
  console.log(`[BatchBox] Node ${node.id}: Loading ${previewImages.length} preview image(s)...`);
  
  // Set the images property (used by ComfyUI's OUTPUT_NODE mechanism)
  node.images = previewImages;
  node.imageIndex = 0;
  
  // Pre-allocate imgs array with nulls, fill in as images load
  node.imgs = new Array(previewImages.length).fill(null);
  let loadedCount = 0;
  
  previewImages.forEach((imgInfo, index) => {
    const url = `/view?filename=${encodeURIComponent(imgInfo.filename)}&subfolder=${encodeURIComponent(imgInfo.subfolder || "")}&type=${imgInfo.type || "output"}&t=${Date.now()}`;
    const img = new Image();
    
    img.onload = () => {
      // Store loaded image at correct index
      node.imgs[index] = img;
      loadedCount++;
      console.log(`[BatchBox] Node ${node.id}: Image ${loadedCount}/${previewImages.length} loaded`);
      
      // Force immediate redraw when image loads
      node.setDirtyCanvas(true, true);
      
      // Also trigger global graph redraw
      if (app.graph) {
        app.graph.setDirtyCanvas(true, true);
      }
      
      // Try to trigger a canvas refresh via requestAnimationFrame
      if (loadedCount === previewImages.length) {
        requestAnimationFrame(() => {
          node.setDirtyCanvas(true, true);
          if (app.canvas) {
            app.canvas.draw(true, true);
          }
        });
      }
    };
    
    img.onerror = (e) => {
      console.error(`[BatchBox] Node ${node.id}: Failed to load image ${index}`, url, e);
    };
    
    console.log(`[BatchBox] Node ${node.id}: Loading image ${index}: ${url}`);
    img.src = url;
  });
  
  // Save to properties for persistence
  if (!node.properties) {
    node.properties = {};
  }
  node.properties._last_images = JSON.stringify(previewImages);
  // Also save node size for proper restoration
  node.properties._last_size = JSON.stringify(node.size);
  
  // Save params hash for smart cache (if provided)
  if (paramsHash) {
    node.properties._cached_hash = paramsHash;
    console.log(`[BatchBox] Node ${node.id}: Saved params hash: ${paramsHash}`);
  }
  
  // === IMAGE SELECTION: Set default selection after generation ===
  // For independent generation, always reset to first image (index 0)
  // This is a NEW generation, so we start fresh
  node._selectedImageIndex = 0;
  if (previewImages.length > 1) {
    node.imageIndex = 0;
    node.properties._selected_image_index = 0;
    console.log(`[BatchBox] Node ${node.id}: New generation - selection reset to 0`);
  }
  
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
      // Debug: log result
      console.log("[BatchBox] result.preview_images:", JSON.stringify(result.preview_images, null, 2));
      console.log("[BatchBox] Backend params_hash:", result.params_hash);
      
      // Use the hash computed by backend for consistency
      // This ensures the hash matches what nodes.py computes during Queue Prompt
      const paramsHash = result.params_hash;
      
      // Update node preview with the backend-computed hash
      updateNodePreview(node, result.preview_images, paramsHash);
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

  // Add BatchBox nodes directly to the first-level canvas right-click menu
  getCanvasMenuItems() {
    // Respect the setting - if disabled, return empty array
    if (!showInCanvasMenuEnabled) {
      return [];
    }

    const batchboxNodes = [
      { label: "🖼️ Dynamic Image Generation", type: "DynamicImageGeneration" },
      { label: "🎬 Dynamic Video Generation", type: "DynamicVideoGeneration" },
      { label: "📝 Dynamic Text Generation", type: "DynamicTextGeneration" },
      { label: "✏️ Dynamic Image Editor", type: "DynamicImageEditor" },
      { label: "🔊 Dynamic Audio Generation", type: "DynamicAudioGeneration" },
    ];

    return batchboxNodes.map(nodeInfo => ({
      content: nodeInfo.label,
      callback: () => {
        const node = LiteGraph.createNode(nodeInfo.type);
        if (node) {
          // Position at mouse or center of canvas
          const canvas = app.canvas;
          if (canvas.graph_mouse) {
            node.pos = [canvas.graph_mouse[0], canvas.graph_mouse[1]];
          } else {
            node.pos = [100, 100];
          }
          app.graph.add(node);
          canvas.selectNode(node);
        }
      }
    }));
  },

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
      
      // === IMAGE SELECTION: Track user's image selection ===
      // Intercept imageIndex setter to capture when ComfyUI changes it
      // This gives us an immediate signal without delays
      this._selectedImageIndex = 0;
      this._ignoreImageIndexChanges = false;  // Flag to pause tracking during/after execution
      this._imageIndexInternal = 0;  // Internal storage for imageIndex
      
      // Store reference to node for the getter/setter
      const selfNode = this;
      
      // Use Object.defineProperty to intercept imageIndex changes
      Object.defineProperty(this, 'imageIndex', {
        get: function() {
          return selfNode._imageIndexInternal;
        },
        set: function(value) {
          // Block null during execution window, allow at all other times
          if ((value === null || value === undefined) && selfNode._ignoreImageIndexChanges) {
            selfNode._imageIndexInternal = selfNode._selectedImageIndex || 0;
            return;
          }
          
          selfNode._imageIndexInternal = value;
          
          // Track user selections (valid indices only)
          if (!selfNode._ignoreImageIndexChanges && value !== null && value !== undefined) {
            if (selfNode.imgs && selfNode.imgs.length > 1 && value >= 0 && value < selfNode.imgs.length) {
              selfNode._selectedImageIndex = value;
              
              // Save to properties
              if (!selfNode.properties) selfNode.properties = {};
              selfNode.properties._selected_image_index = value;
              
              console.log(`[BatchBox] Node ${selfNode.id}: Selection saved: ${value}`);
            }
          }
        },
        configurable: true,
        enumerable: true
      });
      
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
      
      // Save collapsed groups state (e.g., 高级设置 expanded/collapsed)
      if (this._dynamicParamManager?.collapsedGroups) {
        o.collapsedGroups = Array.from(this._dynamicParamManager.collapsedGroups);
      }
      
      // === IMAGE SELECTION: Save selection state ===
      o.imageSelectionState = {
        selectedIndex: this._selectedImageIndex || this.properties?._selected_image_index || 0
      };
    };

    // Deserialize dynamic params
    const origOnConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (o) {
      if (origOnConfigure) {
        origOnConfigure.apply(this, arguments);
      }

      // Store pending params for restoration when widgets are created
      // The actual restoration happens in updateWidgets -> createWidget
      // This elegant approach creates widgets with correct values, preventing UI flash
      if (o.dynamicParams) {
        this._pendingDynamicParams = o.dynamicParams;
        console.log('[DynamicParams] Stored pending params for widget creation:', Object.keys(o.dynamicParams));
      }
      
      // Store pending endpoint state for restoration when endpoint widgets are created
      // The actual restoration happens in updateEndpointSelector
      if (o.endpointState) {
        this._pendingEndpointState = o.endpointState;
        console.log('[DynamicParams] Stored pending endpoint state for widget creation');
      }
      
      // Restore collapsed groups state (must happen before widgets are created)
      if (o.collapsedGroups && this._dynamicParamManager) {
        this._dynamicParamManager.collapsedGroups = new Set(o.collapsedGroups);
        console.log('[DynamicParams] Restored collapsed groups:', o.collapsedGroups);
      }
      
      // === IMAGE SELECTION: Restore selection state ===
      if (o.imageSelectionState) {
        this._selectedImageIndex = o.imageSelectionState.selectedIndex || 0;
        // Ensure imageIndex matches for display
        if (this.imgs && this.imgs.length > 0) {
          this.imageIndex = this._selectedImageIndex;
        }
        console.log(`[DynamicParams] Restored image selection: index=${this._selectedImageIndex}`);
      } else if (this.properties?._selected_image_index !== undefined) {
        // Fallback: restore from properties
        this._selectedImageIndex = parseInt(this.properties._selected_image_index) || 0;
        console.log(`[DynamicParams] Restored image selection from properties: index=${this._selectedImageIndex}`);
      }
    };
  },

});

// ==========================================
// Intercept queuePrompt to update extra_params and inject cache state
// ==========================================
const origQueuePrompt = api.queuePrompt;
api.queuePrompt = async function(number, workflowData) {
  // Capture and reset the flag immediately
  const wasButtonTriggered = isButtonTriggeredExecution;
  isButtonTriggeredExecution = false;
  
  // Collect BatchBox node IDs
  const batchboxNodeIds = new Set();
  
  // Update extra_params for all dynamic nodes before sending to backend
  if (app.graph && app.graph._nodes) {
    for (const node of app.graph._nodes) {
      if (node._dynamicParamManager && node.widgets) {
        // Track BatchBox nodes
        batchboxNodeIds.add(String(node.id));
        
        // Update extra_params widget
        // IMPORTANT: If widgets aren't restored yet (after restart), use pending params
        const extraParamsWidget = node.widgets.find(w => w.name === "extra_params");
        if (extraParamsWidget) {
          let dynamicParams = node._dynamicParamManager.collectDynamicParams();
          
          // If collected params are empty but we have pending params (saved in workflow),
          // use those instead. This fixes the "first execution after restart" issue.
          if (Object.keys(dynamicParams).length === 0 && node._pendingDynamicParams) {
            dynamicParams = node._pendingDynamicParams;
            console.log(`[DynamicParams] node ${node.id}: Using pending params (widgets not ready yet)`);
          }
          
          extraParamsWidget.value = JSON.stringify(dynamicParams);
          console.log(`[DynamicParams] node ${node.id} extra_params:`, extraParamsWidget.value);
        }
      }
    }
  }
  
  // === SMART CACHE: Inject hidden inputs directly into workflowData ===
  // This is more reliable than widgets for hidden inputs
  if (workflowData?.output && app.graph && app.graph._nodes) {
    for (const node of app.graph._nodes) {
      if (node._dynamicParamManager) {
        const nodeId = String(node.id);
        const nodeData = workflowData.output[nodeId];
        
        if (nodeData && nodeData.inputs) {
          // === CRITICAL: Also sync extra_params to workflowData ===
          // The widget update alone doesn't update workflowData, we need to do it explicitly
          let dynamicParams = node._dynamicParamManager.collectDynamicParams();
          if (Object.keys(dynamicParams).length === 0 && node._pendingDynamicParams) {
            dynamicParams = node._pendingDynamicParams;
          }
          nodeData.inputs.extra_params = JSON.stringify(dynamicParams);
          
          // Inject _force_generate
          nodeData.inputs._force_generate = wasButtonTriggered ? "true" : "false";
          
          // Set flag for onExecuted to know if this is a new generation
          // (used to decide whether to reset selection to 0)
          node._forceGenerateFlag = wasButtonTriggered;
          
          // === IMAGE SELECTION: Pause tracking during execution ===
          // This prevents ComfyUI's automatic imageIndex resets from being tracked
          node._ignoreImageIndexChanges = true;
          
          // Inject _cached_hash from properties (persisted from last generation)
          nodeData.inputs._cached_hash = node.properties?._cached_hash || "";
          
          // Inject _last_images from properties (persisted from last generation)
          nodeData.inputs._last_images = node.properties?._last_images || "";
          
          // Inject _skip_hash_check based on setting (when disabled, skip hash comparison)
          nodeData.inputs._skip_hash_check = smartCacheHashCheckEnabled ? "false" : "true";
          
          // === IMAGE SELECTION: Inject _selected_image_index ===
          const selectedIndex = node._selectedImageIndex || node.properties?._selected_image_index || 0;
          nodeData.inputs._selected_image_index = parseInt(selectedIndex) || 0;
          
          console.log(`[SmartCache] node ${nodeId}: force=${nodeData.inputs._force_generate}, hasCache=${!!nodeData.inputs._last_images}, selectedIdx=${nodeData.inputs._selected_image_index}, extra_params=${nodeData.inputs.extra_params.substring(0, 50)}...`);
        }
      }
    }
  }
  
  // If bypass is enabled AND NOT button-triggered, BatchBox nodes will still execute
  // but the backend will skip API call and return cached images
  if (bypassQueuePromptEnabled && !wasButtonTriggered && batchboxNodeIds.size > 0) {
    console.log(`[BatchBox] Bypass mode: ${batchboxNodeIds.size} BatchBox node(s) will return cached images`);
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

