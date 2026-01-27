/**
 * Dynamic Inputs Extension (Multi-Type Support)
 * 
 * Implements automatic input slot management using LiteGraph's addInput/removeInput.
 * Supports multiple input types: IMAGE, FILE, AUDIO, VIDEO, etc.
 * 
 * Config format in api_config.yaml:
 * dynamic_inputs:
 *   image:
 *     max: 14
 *     type: "IMAGE"
 *     label: "图片"
 *   file:
 *     max: 5
 *     type: "FILE"
 *     label: "文件"
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Cache for model configs
const modelConfigCache = {};

// Node types that support dynamic inputs
const DYNAMIC_INPUT_NODES = [
    "NanoBananaPro",
    "DynamicImageGeneration",
    "DynamicVideoGeneration",
    "DynamicAudioGeneration",
    "DynamicTextGeneration",
    "DynamicImageEditor"
];

// Cache for node settings (default_width, etc.)
let nodeSettingsCache = null;

/**
 * Fetch node settings from backend (cached)
 */
async function getNodeSettings() {
    if (nodeSettingsCache !== null) {
        return nodeSettingsCache;
    }
    
    try {
        const resp = await api.fetchApi("/api/batchbox/node-settings");
        if (resp.status === 200) {
            const data = await resp.json();
            nodeSettingsCache = data.node_settings || { default_width: 500 };
            return nodeSettingsCache;
        }
    } catch (e) {
        console.warn("[DynamicInputs] Failed to fetch node settings:", e);
    }
    
    // Default fallback
    nodeSettingsCache = { default_width: 500 };
    return nodeSettingsCache;
}

/**
 * Fetch dynamic_inputs config for a model from backend
 */
async function getDynamicInputsConfig(modelName) {
    if (modelConfigCache[modelName] !== undefined) {
        return modelConfigCache[modelName];
    }

    try {
        const resp = await api.fetchApi(`/api/batchbox/schema/${modelName}`);
        if (resp.status === 200) {
            const data = await resp.json();
            // Support both new format (dynamic_inputs) and legacy (max_image_inputs)
            let config = data.dynamic_inputs;
            if (!config && data.max_image_inputs) {
                // Legacy fallback
                config = {
                    image: {
                        max: data.max_image_inputs,
                        type: "IMAGE",
                        label: "图片"
                    }
                };
            }
            modelConfigCache[modelName] = config || {};
            return modelConfigCache[modelName];
        }
    } catch (e) {
        console.warn("[DynamicInputs] Failed to fetch model config:", e);
    }

    // Default fallback
    modelConfigCache[modelName] = {
        image: { max: 4, type: "IMAGE", label: "图片" }
    };
    return modelConfigCache[modelName];
}

/**
 * Count current inputs of a specific type prefix on a node
 */
function countInputsByPrefix(node, prefix) {
    let count = 0;

    if (node.inputs) {
        for (const input of node.inputs) {
            if (input.name && input.name.startsWith(prefix)) {
                count++;
            }
        }
    }
    return count;
}

/**
 * Get the highest connected input index for a prefix
 */
function getHighestConnectedIndex(node, prefix) {
    let highest = 0;
    if (node.inputs) {
        for (const input of node.inputs) {
            if (input.name && input.name.startsWith(prefix)) {

                if (input.link != null) {
                    const idx = parseInt(input.name.replace(prefix, ""));
                    if (!isNaN(idx) && idx > highest) {
                        highest = idx;
                    }
                }
            }
        }
    }
    return highest;
}

/**
 * Add a new input to the node
 */
function addDynamicInput(node, prefix, index, inputType) {
    const inputName = `${prefix}${index}`;

    // Check if already exists
    if (node.inputs) {
        for (const input of node.inputs) {
            if (input.name === inputName) {
                return false;
            }
        }
    }

    // Save current width before adding input (to preserve user's custom width)
    const currentWidth = node.size[0];
    
    node.addInput(inputName, inputType);
    
    // Restore width after adding input, only update height
    const computedSize = node.computeSize();
    node.setSize([currentWidth, computedSize[1]]);
    return true;
}

/**
 * Remove an input from the node by name
 */
function removeDynamicInput(node, inputName) {
    if (!node.inputs) return false;

    const index = node.inputs.findIndex(i => i.name === inputName);
    if (index === -1) return false;

    // Don't remove if connected
    if (node.inputs[index].link != null) return false;

    // Save current width before removing input (to preserve user's custom width)
    const currentWidth = node.size[0];
    
    node.removeInput(index);
    
    // Restore width after removing input, only update height
    const computedSize = node.computeSize();
    node.setSize([currentWidth, computedSize[1]]);
    return true;
}

/**
 * Update inputs for a specific type/prefix
 */
function updateInputsForType(node, prefix, inputType, maxInputs) {
    // Save current width before any modifications (to preserve user's custom width)
    const currentWidth = node.size[0];
    
    const currentCount = countInputsByPrefix(node, prefix);
    const highestConnected = getHighestConnectedIndex(node, prefix);

    // Always have one more slot than highest connected (up to max)
    // This ensures there's always an empty slot to connect to
    let targetCount = Math.max(1, highestConnected + 1);
    targetCount = Math.min(targetCount, maxInputs);

    // Add missing inputs up to target
    for (let i = 1; i <= targetCount; i++) {
        const inputName = `${prefix}${i}`;
        const exists = node.inputs?.some(inp => inp.name === inputName);
        if (!exists) {
            node.addInput(inputName, inputType);
        }
    }

    // Remove extra empty inputs beyond target (but keep connected ones)
    for (let i = currentCount; i > targetCount; i--) {
        const inputName = `${prefix}${i}`;
        const input = node.inputs?.find(inp => inp.name === inputName);
        // Only remove if not connected
        if (input && input.link == null) {
            const index = node.inputs.indexOf(input);
            if (index >= 0) {
                node.removeInput(index);
            }
        }
    }

    // Restore width after input modifications, only update height
    const computedSize = node.computeSize();
    node.setSize([currentWidth, computedSize[1]]);
}

/**
 * Update all dynamic inputs based on connection state
 */
async function updateAllDynamicInputs(node) {
    // Get model name from widget
    let modelName = null;
    if (node.widgets) {
        const modelWidget = node.widgets.find(w => w.name === "model" || w.name === "preset");
        if (modelWidget) {
            modelName = modelWidget.value;
        }
    }

    const config = modelName ? await getDynamicInputsConfig(modelName) : {};
    console.log(`[DynamicInputs] Model: ${modelName}, config:`, config);

    // Process each configured input type
    for (const [key, typeConfig] of Object.entries(config)) {
        const prefix = key;  // e.g., "image", "file", "audio"
        const inputType = typeConfig.type || "IMAGE";
        const maxInputs = typeConfig.max || 1;

        updateInputsForType(node, prefix, inputType, maxInputs);
    }

    // Trigger graph update (skip during restore to avoid intermediate renders)
    if (app.graph && !node._isRestoring) {
        app.graph.setDirtyCanvas(true, true);
    }
}

/**
 * Initialize dynamic inputs for a node
 */
async function initializeDynamicInputs(node) {
    // Get node type from various possible sources
    const nodeType = node.comfyClass || node.type || node.constructor?.type || '';
    
    // Skip if not a supported node type
    if (!DYNAMIC_INPUT_NODES.includes(nodeType)) {
        return;
    }

    // Mark as initialized
    if (node._dynamicInputsInitialized) {
        return;
    }
    node._dynamicInputsInitialized = true;

    // Store original onExecuted to save preview info for persistence
    const originalOnExecuted = node.onExecuted;
    node.onExecuted = function(message) {
        if (originalOnExecuted) {
            originalOnExecuted.call(this, message);
        }
        
        // Save _last_images to node.properties for persistence (properties are saved in workflow JSON)
        // Let OUTPUT_NODE handle the actual preview display
        if (message && message._last_images && message._last_images[0]) {
            if (!this.properties) {
                this.properties = {};
            }
            this.properties._last_images = message._last_images[0];
            console.log("[Batchbox] Saved preview info to properties");
        }
    };

    // Store original onConnectionsChange
    const originalOnConnectionsChange = node.onConnectionsChange;

    node.onConnectionsChange = function (type, slotIndex, isConnected, link, ioSlot) {
        // Call original if exists
        if (originalOnConnectionsChange) {
            originalOnConnectionsChange.call(this, type, slotIndex, isConnected, link, ioSlot);
        }

        // Only handle input connections (type 1)
        if (type !== 1) return;

        // Debounce the update
        if (this._updateInputsTimeout) {
            clearTimeout(this._updateInputsTimeout);
        }
        this._updateInputsTimeout = setTimeout(() => {
            updateAllDynamicInputs(this);
        }, 50);
    };

    // Listen for model changes
    if (node.widgets) {
        const modelWidget = node.widgets.find(w => w.name === "model" || w.name === "preset");
        if (modelWidget) {
            const originalCallback = modelWidget.callback;
            modelWidget.callback = async (value) => {
                if (originalCallback) {
                    originalCallback.call(modelWidget, value);
                }
                // Clear cache and reinitialize for new model
                // Width is preserved by addDynamicInput/removeDynamicInput functions
                modelConfigCache[value] = undefined;
                await updateAllDynamicInputs(node);
            };
        }
    }

    // Initial update
    await updateAllDynamicInputs(node);
}

// ==========================================
// Extension Registration
// ==========================================
app.registerExtension({
    name: "ComfyUI.CustomBatchbox.DynamicInputs",

    async nodeCreated(node) {
        const nodeType = node.comfyClass || node.type;
        if (!DYNAMIC_INPUT_NODES.includes(nodeType)) {
            return;
        }
        
        // Mark this as a fresh node creation (not loading from workflow)
        // This flag will be cleared by loadedGraphNode if it's actually a workflow load
        node._batchbox_fresh_create = true;
        
        // Use a short delay to allow loadedGraphNode to run first if this is a workflow load
        setTimeout(async () => {
            // If still marked as fresh create, this is truly a new node
            if (node._batchbox_fresh_create) {
                // Set default width for newly created nodes (from config)
                const nodeSettings = await getNodeSettings();
                const defaultWidth = nodeSettings.default_width || 500;
                const computedSize = node.computeSize();
                node.size = [defaultWidth, computedSize[1]];
                node.setDirtyCanvas(true, true);
                console.log(`[Batchbox] Set initial width for new ${nodeType}: ${defaultWidth}px`);
            }
            delete node._batchbox_fresh_create;
            
            // Initialize dynamic inputs
            await initializeDynamicInputs(node);
        }, 50);
    },

    async loadedGraphNode(node) {
        const nodeType = node.comfyClass || node.type;
        if (!DYNAMIC_INPUT_NODES.includes(nodeType)) {
            return;
        }
        
        // This is a workflow load, not a fresh create
        node._batchbox_fresh_create = false;
        
        // Mark as restoring - suppress intermediate canvas updates
        node._isRestoring = true;
        
        // Apply saved size IMMEDIATELY to prevent initial wrong size
        const savedWidth = node.size[0];
        if (node.properties?._last_size) {
            try {
                const savedSize = JSON.parse(node.properties._last_size);
                node.size = [savedWidth, savedSize[1]];
            } catch (e) {}
        }
        
        // Pre-load images BEFORE setTimeout to start loading early
        if (node.properties?._last_images) {
            try {
                const imagesData = node.properties._last_images;
                const images = typeof imagesData === "string" ? JSON.parse(imagesData) : imagesData;
                if (images && images.length > 0) {
                    node.imageIndex = 0;
                    node.images = images;
                    node.imgs = images.map(img => {
                        const url = `/view?filename=${encodeURIComponent(img.filename)}&subfolder=${encodeURIComponent(img.subfolder || "")}&type=${img.type || "output"}`;
                        const imgEl = new Image();
                        imgEl.src = url;
                        return imgEl;
                    });
                }
            } catch (e) {}
        }
        
        // Now do async initialization
        setTimeout(async () => {
            // Initialize dynamic inputs (widgets etc)
            await initializeDynamicInputs(node);
            
            // Wait for images if any
            if (node.imgs && node.imgs.length > 0) {
                await Promise.all(node.imgs.map(img => {
                    if (img.complete) return Promise.resolve();
                    return new Promise(resolve => {
                        img.onload = resolve;
                        img.onerror = resolve;
                    });
                }));
            }
            
            // Final size calculation
            if (node.properties?._last_size) {
                try {
                    const savedSize = JSON.parse(node.properties._last_size);
                    node.size = [savedWidth, savedSize[1]];
                } catch (e) {
                    const computedSize = node.computeSize();
                    node.size = [savedWidth, computedSize[1]];
                }
            } else {
                const computedSize = node.computeSize();
                node.size = [savedWidth, computedSize[1]];
            }
            
            // Clear restoring flag and do single final render
            node._isRestoring = false;
            node.setDirtyCanvas(true, true);
            if (app.graph) {
                app.graph.setDirtyCanvas(true, true);
            }
        }, 100);
    }
});

/**
 * Restore preview images from saved node.properties
 */
function restorePreviewFromProperties(node) {
    console.log(`[Batchbox] restorePreviewFromProperties called for node ${node.id}, type: ${node.comfyClass || node.type}`);
    console.log(`[Batchbox] node.properties:`, node.properties);
    
    // Read from node.properties (saved in workflow JSON)
    const lastImagesData = node.properties?._last_images;
    if (!lastImagesData) {
        console.log(`[Batchbox] No _last_images found for node ${node.id}`);
        return;
    }
    
    console.log(`[Batchbox] _last_images data type: ${typeof lastImagesData}, value:`, lastImagesData);
    
    try {
        // Handle both formats:
        // - String (from independent generation): JSON stringified array
        // - Array/Object (from ComfyUI execution): direct array of image objects
        let images;
        if (typeof lastImagesData === "string") {
            images = JSON.parse(lastImagesData);
        } else if (Array.isArray(lastImagesData)) {
            images = lastImagesData;
        } else {
            console.warn("[Batchbox] Unknown _last_images format:", typeof lastImagesData);
            return;
        }
        
        console.log(`[Batchbox] Parsed images:`, images);
        
        if (images && images.length > 0) {
            // Set image metadata - ComfyUI's OUTPUT_NODE mechanism
            node.imageIndex = 0;
            node.images = images;
            
            // Pre-create Image objects for node.imgs
            // ComfyUI uses node.imgs for actual rendering
            node.imgs = images.map(img => {
                const url = `/view?filename=${encodeURIComponent(img.filename)}&subfolder=${encodeURIComponent(img.subfolder || "")}&type=${img.type || "output"}`;
                const imgEl = new Image();
                imgEl.src = url;
                return imgEl;
            });
            
            console.log(`[Batchbox] Restored ${images.length} preview image(s) for node ${node.id}`);
        }
    } catch (e) {
        console.warn("[Batchbox] Failed to restore preview:", e);
    }
}

console.log("[ComfyUI-Custom-Batchbox] Dynamic Inputs extension (multi-type) loaded");
