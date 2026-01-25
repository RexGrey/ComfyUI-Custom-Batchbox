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

    node.addInput(inputName, inputType);
    node.setSize(node.computeSize());
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

    node.removeInput(index);
    node.setSize(node.computeSize());
    return true;
}

/**
 * Update inputs for a specific type/prefix
 */
function updateInputsForType(node, prefix, inputType, maxInputs) {
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

    node.setSize(node.computeSize());
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

    // Trigger graph update
    if (app.graph) {
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
        // Initialize when node is created
        await initializeDynamicInputs(node);
    },

    async loadedGraphNode(node) {
        // Initialize when loading from saved workflow
        setTimeout(async () => {
            await initializeDynamicInputs(node);
        }, 100);
    }
});

console.log("[ComfyUI-Custom-Batchbox] Dynamic Inputs extension (multi-type) loaded");
