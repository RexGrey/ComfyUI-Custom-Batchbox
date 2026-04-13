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

function splitFilename(filename) {
    const lastDot = filename.lastIndexOf(".");
    if (lastDot <= 0) {
        return { stem: filename, ext: "" };
    }
    return {
        stem: filename.slice(0, lastDot),
        ext: filename.slice(lastDot),
    };
}

async function computeFileHash(fileOrBlob) {
    if (!globalThis.crypto?.subtle || !fileOrBlob?.arrayBuffer) {
        return null;
    }
    const bytes = await fileOrBlob.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest))
        .map(b => b.toString(16).padStart(2, "0"))
        .join("");
}

async function fetchExistingInputBlob(filename) {
    try {
        const resp = await api.fetchApi(`/view?filename=${encodeURIComponent(filename)}&type=input`);
        if (!resp.ok) return null;
        return await resp.blob();
    } catch {
        return null;
    }
}

async function resolveUploadFile(file) {
    const incomingHash = await computeFileHash(file);
    if (!incomingHash) {
        return { uploadFile: file, existingName: null };
    }

    const existingBlob = await fetchExistingInputBlob(file.name);
    if (!existingBlob) {
        return { uploadFile: file, existingName: null };
    }

    const existingHash = await computeFileHash(existingBlob);
    if (existingHash && existingHash === incomingHash) {
        return { uploadFile: null, existingName: file.name };
    }

    const { stem, ext } = splitFilename(file.name);
    for (let counter = 0; counter < 100; counter++) {
        const suffix = counter === 0
            ? `_${incomingHash.slice(0, 8)}`
            : `_${incomingHash.slice(0, 8)}_${counter}`;
        const candidateName = `${stem}${suffix}${ext}`;
        const candidateBlob = await fetchExistingInputBlob(candidateName);
        if (!candidateBlob) {
            return {
                uploadFile: new File([file], candidateName, {
                    type: file.type,
                    lastModified: file.lastModified,
                }),
                existingName: null,
            };
        }

        const candidateHash = await computeFileHash(candidateBlob);
        if (candidateHash && candidateHash === incomingHash) {
            return { uploadFile: null, existingName: candidateName };
        }
    }

    return {
        uploadFile: new File([file], `${stem}_${Date.now()}${ext}`, {
            type: file.type,
            lastModified: file.lastModified,
        }),
        existingName: null,
    };
}

/**
 * Upload an image file to ComfyUI's input folder via /upload/image API.
 * @param {File} file - The image file to upload
 * @returns {Promise<string|null>} The uploaded filename, or null on failure
 */
async function uploadImageToInput(file) {
    const { uploadFile, existingName } = await resolveUploadFile(file);
    if (existingName) {
        console.log(`[ImageDrop] ♻️ Reusing existing input image: ${existingName}`);
        return existingName;
    }

    const formData = new FormData();
    formData.append("image", uploadFile || file);
    formData.append("type", "input");
    formData.append("subfolder", "");
    // Preserve existing files. Same-hash files are reused; different files get a suffix.
    formData.append("overwrite", "false");

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
    setLoadImageWidgetValue(node, imageName);

    // Force the node to refresh so the preview shows
    node.setDirtyCanvas(true, true);
    app.graph.setDirtyCanvas(true, true);
    console.log(`[ImageDrop] ✅ Created LoadImage node with: ${imageName}`);
}

/**
 * Set the image widget value on a LoadImage node, ensuring the filename
 * is in the combo options list so execution can find it.
 */
function setLoadImageWidgetValue(node, imageName) {
    const imageWidget = node.widgets?.find(w => w.name === "image");
    if (!imageWidget) return;

    // Ensure the uploaded filename is in the widget's options list
    // ComfyUI combo widgets store options in widget.options.values (array)
    // or may use a different structure depending on version
    if (imageWidget.options?.values && Array.isArray(imageWidget.options.values)) {
        if (!imageWidget.options.values.includes(imageName)) {
            imageWidget.options.values.push(imageName);
        }
    }

    imageWidget.value = imageName;

    // Trigger callback to update preview
    if (imageWidget.callback) {
        imageWidget.callback(imageName);
    }
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
                    setLoadImageWidgetValue(nodeUnderCursor, uploadedName);
                    nodeUnderCursor.setDirtyCanvas(true, true);
                    app.graph.setDirtyCanvas(true, true);
                    console.log(`[ImageDrop] ✅ Replaced image in node #${nodeUnderCursor.id}: ${uploadedName}`);
                }
                return;
            }

            // Delegate to any custom node that implements onDropFile (e.g. BatchBoxImageAnnotator)
            if (imageFiles.length === 1 && nodeUnderCursor && typeof nodeUnderCursor.onDropFile === "function" && nodeUnderCursor.type !== "LoadImage") {
                console.log(`[ImageDrop] Delegating to ${nodeUnderCursor.type} node #${nodeUnderCursor.id}`);
                nodeUnderCursor.onDropFile(imageFiles[0]);
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

/**
 * Bugfix: In some ComfyUI environments (like specific aki-v3 versions or when conflicting with other custom nodes), 
 * the native LoadImage node fails to trigger its preview refresh callback upon restoring from localStorage (browser F5 refresh).
 * This explicitly hooks LoadImage's onConfigure to ensure the thumbnail renders.
 */
app.registerExtension({
    name: "Batchbox.LoadImagePreviewFix",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "LoadImage") {
            const origOnConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (o) {
                if (origOnConfigure) {
                    origOnConfigure.apply(this, arguments);
                }

                // After standard configuration restores the widget values, forcefully trigger the callback
                // to make sure ComfyUI fetches the image and displays the preview thumbnail.
                setTimeout(() => {
                    if (this.widgets) {
                        const imageWidget = this.widgets.find(w => w.name === "image");
                        if (imageWidget && imageWidget.value && typeof imageWidget.callback === "function") {
                            // If the node doesn't have an image cached yet or it's empty, trigger callback
                            if (!this.imgs || this.imgs.length === 0) {
                                console.log(`[BatchBox.PreviewFix] Force refreshing LoadImage preview for: ${imageWidget.value}`);
                                imageWidget.callback(imageWidget.value);
                            }
                        }
                    }
                }, 100);
            };
        }
    }
});
