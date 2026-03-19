/**
 * Image Drop → LoadImage Node
 * 
 * Intercepts image file drops on the canvas and creates a LoadImage node
 * instead of the default behavior (loading embedded workflow).
 * 
 * Supports: png, jpg, jpeg, webp, gif, bmp, tiff
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "tif"]);

/**
 * Upload an image file to ComfyUI's input folder via /upload/image API.
 * @param {File} file - The image file to upload
 * @returns {Promise<string|null>} The uploaded filename, or null on failure
 */
async function uploadImageToInput(file) {
    const formData = new FormData();
    formData.append("image", file);
    formData.append("type", "input");
    formData.append("subfolder", "");
    // Overwrite=true to avoid filename conflicts
    formData.append("overwrite", "true");

    try {
        const resp = await api.fetchApi("/upload/image", {
            method: "POST",
            body: formData,
        });
        if (resp.ok) {
            const data = await resp.json();
            // API returns { name, subfolder, type }
            const uploadedName = data.name || data.filename;
            console.log(`[ImageDrop] ✅ Uploaded: ${file.name} → ${uploadedName}`);
            return uploadedName;
        } else {
            console.error(`[ImageDrop] ❌ Upload failed: HTTP ${resp.status}`);
            return null;
        }
    } catch (e) {
        console.error("[ImageDrop] ❌ Upload error:", e);
        return null;
    }
}

/**
 * Create a LoadImage node at the given canvas position and set the image.
 * @param {string} imageName - The uploaded image filename
 * @param {number} canvasX - X position on canvas
 * @param {number} canvasY - Y position on canvas
 */
function createLoadImageNode(imageName, canvasX, canvasY) {
    const node = LiteGraph.createNode("LoadImage");
    if (!node) {
        console.error("[ImageDrop] ❌ LoadImage node type not found");
        return;
    }

    node.pos = [canvasX, canvasY];
    app.graph.add(node);

    // Set the image widget value
    // LoadImage node has a widget named "image" that lists available images
    const imageWidget = node.widgets?.find(w => w.name === "image");
    if (imageWidget) {
        imageWidget.value = imageName;
        // Trigger callback to update preview
        if (imageWidget.callback) {
            imageWidget.callback(imageName);
        }
    }

    // Force the node to refresh so the preview shows
    node.setDirtyCanvas(true, true);
    app.graph.setDirtyCanvas(true, true);
    console.log(`[ImageDrop] ✅ Created LoadImage node with: ${imageName}`);
}

/**
 * Get file extension from filename.
 */
function getExtension(filename) {
    const parts = filename.split(".");
    return parts.length > 1 ? parts.pop().toLowerCase() : "";
}

app.registerExtension({
    name: "Batchbox.ImageDrop",

    async setup() {
        // Intercept drop events on the canvas element
        const canvasEl = document.getElementById("graph-canvas");
        if (!canvasEl) {
            console.warn("[ImageDrop] Canvas element not found, retrying...");
            // Retry after a short delay in case canvas isn't ready yet
            setTimeout(() => this._attachDropHandler(), 1000);
            return;
        }
        this._attachDropHandler(canvasEl);
    },

    _attachDropHandler(canvasEl) {
        if (!canvasEl) {
            canvasEl = document.getElementById("graph-canvas");
        }
        if (!canvasEl) {
            console.warn("[ImageDrop] Canvas element not found");
            return;
        }

        // We need to intercept BEFORE ComfyUI's default handler.
        // Use capture phase (3rd arg = true) to run first.
        canvasEl.addEventListener("drop", async (e) => {
            const files = e.dataTransfer?.files;
            if (!files || files.length === 0) return;

            // Check if ALL dropped files are images
            const imageFiles = [];
            for (const file of files) {
                const ext = getExtension(file.name);
                if (IMAGE_EXTENSIONS.has(ext)) {
                    imageFiles.push(file);
                }
            }

            // Only intercept if we have image files (not JSON workflows, etc.)
            if (imageFiles.length === 0) return;

            // Prevent ComfyUI's default drop handler (workflow loading)
            e.preventDefault();
            e.stopPropagation();

            // Get canvas coordinates from drop position
            const graphCanvas = app.canvas;
            const [canvasX, canvasY] = graphCanvas.convertEventToCanvasOffset(e);

            // Check if drop landed on an existing LoadImage node
            const nodeUnderCursor = app.graph.getNodeOnPos(canvasX, canvasY);

            if (imageFiles.length === 1 && nodeUnderCursor && nodeUnderCursor.type === "LoadImage") {
                // Single image dropped onto LoadImage node → replace its image
                const file = imageFiles[0];
                console.log(`[ImageDrop] Replacing image in node #${nodeUnderCursor.id}: ${file.name}`);
                const uploadedName = await uploadImageToInput(file);
                if (uploadedName) {
                    const imageWidget = nodeUnderCursor.widgets?.find(w => w.name === "image");
                    if (imageWidget) {
                        imageWidget.value = uploadedName;
                        if (imageWidget.callback) {
                            imageWidget.callback(uploadedName);
                        }
                    }
                    nodeUnderCursor.setDirtyCanvas(true, true);
                    app.graph.setDirtyCanvas(true, true);
                    console.log(`[ImageDrop] ✅ Replaced image in node #${nodeUnderCursor.id}: ${uploadedName}`);
                }
                return;
            }

            // Not on a LoadImage node → create new node(s)
            // Space nodes vertically with ~220px gap
            for (let i = 0; i < imageFiles.length; i++) {
                const file = imageFiles[i];
                console.log(`[ImageDrop] Processing ${file.name} (${(file.size / 1024).toFixed(0)} KB)`);

                const uploadedName = await uploadImageToInput(file);
                if (uploadedName) {
                    createLoadImageNode(uploadedName, canvasX, canvasY + i * 220);
                }
            }
        }, true); // capture phase = intercept before ComfyUI

        console.log("[ImageDrop] ✅ Image drop handler registered");
    },
});
