/**
 * BatchBox Image Annotator – Frontend Extension
 *
 * Provides:
 *  1. Drag-and-drop / upload image directly onto the node
 *  2. "Open Editor" button that launches a full-screen modal
 *  3. Rectangle drawing tool (with adjustable colour & line-width)
 *  4. Sequential number marker tool (click to place 1, 2, 3…)
 *  5. "Save Edit" merges annotations onto the image and pushes
 *     a base64 PNG back into the node's hidden widget for Python.
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

/* ──────────────────── Constants ──────────────────── */
const NODE_TYPE = "BatchBoxImageAnnotator";
const PRESET_COLORS = [
    "#FF3B30", // Red
    "#FF9500", // Orange
    "#34C759", // Green
    "#007AFF", // Blue
    "#AF52DE", // Purple
    "#FFFFFF", // White
];
const COLOR_NAMES = ["红", "橙", "绿", "蓝", "紫", "白"];

/* ──────────────────── Helpers ──────────────────── */
function getExtension(name) {
    const parts = name.split(".");
    return parts.length > 1 ? parts.pop().toLowerCase() : "";
}
const IMG_EXTS = new Set(["png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "tif"]);

async function uploadImageToInput(file) {
    const formData = new FormData();
    formData.append("image", file);
    formData.append("type", "input");
    formData.append("subfolder", "");
    formData.append("overwrite", "false");
    try {
        const resp = await api.fetchApi("/upload/image", { method: "POST", body: formData });
        if (resp.ok) {
            const data = await resp.json();
            return data.name || data.filename;
        }
    } catch (e) {
        console.error("[ImageAnnotator] upload error", e);
    }
    return null;
}

/* ──────────────────── CSS (injected once) ──────────────────── */
const EDITOR_CSS = `
.bbia-overlay {
    position: fixed; inset: 0; z-index: 99999;
    background: rgba(0,0,0,.82);
    display: flex; align-items: center; justify-content: center;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
}
.bbia-container {
    background: #1e1e2e; border-radius: 14px;
    display: flex; flex-direction: column;
    max-width: 95vw; max-height: 95vh;
    box-shadow: 0 24px 80px rgba(0,0,0,.6);
    overflow: hidden;
}
.bbia-toolbar {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 16px; background: #272740;
    flex-wrap: wrap; border-bottom: 1px solid #3a3a5c;
}
.bbia-toolbar label { color: #ccc; font-size: 13px; }
.bbia-toolbar select, .bbia-toolbar input[type=range] {
    background: #3a3a5c; color: #eee; border: none;
    border-radius: 6px; padding: 4px 8px; font-size: 13px;
}
.bbia-toolbar input[type=range] { width: 90px; cursor: pointer; }
.bbia-tool-btn {
    padding: 6px 14px; border-radius: 8px; border: 2px solid transparent;
    background: #3a3a5c; color: #ddd; cursor: pointer;
    font-size: 13px; font-weight: 600; transition: all .15s;
}
.bbia-tool-btn:hover { background: #50507a; }
.bbia-tool-btn.active { border-color: #007AFF; background: #2a2a5a; color: #fff; }
.bbia-color-btn {
    width: 24px; height: 24px; border-radius: 50%;
    border: 2px solid transparent; cursor: pointer;
    transition: transform .12s, border-color .12s;
}
.bbia-color-btn:hover { transform: scale(1.15); }
.bbia-color-btn.active { border-color: #fff; transform: scale(1.2); }
.bbia-canvas-wrap {
    flex: 1; display: flex; align-items: center; justify-content: center;
    overflow: auto; padding: 12px; min-height: 0;
}
.bbia-canvas-wrap canvas {
    cursor: crosshair; border-radius: 4px;
    box-shadow: 0 0 0 1px rgba(255,255,255,.08);
}
.bbia-bottom {
    display: flex; align-items: center; justify-content: flex-end;
    gap: 10px; padding: 10px 16px; background: #272740;
    border-top: 1px solid #3a3a5c;
}
.bbia-bottom button {
    padding: 8px 22px; border-radius: 8px; border: none;
    font-size: 14px; font-weight: 600; cursor: pointer;
    transition: background .15s;
}
.bbia-btn-cancel { background: #555; color: #ddd; }
.bbia-btn-cancel:hover { background: #666; }
.bbia-btn-undo { background: #6e4b00; color: #ffc; }
.bbia-btn-undo:hover { background: #7d5700; }
.bbia-btn-save { background: #007AFF; color: #fff; }
.bbia-btn-save:hover { background: #0066d6; }
.bbia-size-label { color: #999; font-size: 12px; min-width: 28px; text-align: center; }
`;

let cssInjected = false;
function injectCSS() {
    if (cssInjected) return;
    const s = document.createElement("style");
    s.textContent = EDITOR_CSS;
    document.head.appendChild(s);
    cssInjected = true;
}

/* ──────────────────── Editor Modal Class ──────────────────── */
class ImageAnnotatorEditor {
    constructor(sourceImage, onSave, onClose, existingAnnotations, existingNextNumber) {
        this.sourceImage = sourceImage;   // HTMLImageElement (original)
        this.onSave = onSave;            // callback(base64, annotations, nextNumber)
        this.onClose = onClose;          // callback(annotations, nextNumber) — called on cancel too
        this.tool = "rect";              // "rect" | "number"
        this.color = PRESET_COLORS[0];
        this.lineWidth = 20;
        this.fontSize = 250;
        this.annotations = existingAnnotations ? JSON.parse(JSON.stringify(existingAnnotations)) : [];
        this.nextNumber = existingNextNumber || 1;
        this.dragging = false;
        this.dragStart = null;
        this._build();
    }

    /* ---- DOM ---- */
    _build() {
        injectCSS();
        this.overlay = document.createElement("div");
        this.overlay.className = "bbia-overlay";

        const container = document.createElement("div");
        container.className = "bbia-container";

        /* Toolbar */
        const tb = document.createElement("div");
        tb.className = "bbia-toolbar";

        // Tool buttons
        this.btnRect = this._toolBtn("框选", "rect");
        this.btnNum = this._toolBtn("数字", "number");
        tb.append(this.btnRect, this.btnNum);

        // Separator
        tb.appendChild(this._sep());

        // Color buttons
        const colorLabel = document.createElement("label");
        colorLabel.textContent = "颜色:";
        tb.appendChild(colorLabel);
        this.colorBtns = PRESET_COLORS.map((c, i) => {
            const btn = document.createElement("div");
            btn.className = "bbia-color-btn" + (i === 0 ? " active" : "");
            btn.style.background = c;
            btn.title = COLOR_NAMES[i];
            btn.addEventListener("click", () => this._setColor(c, i));
            return btn;
        });
        this.colorBtns.forEach(b => tb.appendChild(b));

        // Line width group (rect mode only)
        this.lwGroup = document.createElement("div");
        this.lwGroup.style.cssText = "display:flex;align-items:center;gap:8px;";
        this.lwGroup.appendChild(this._sep());
        const lwLabel = document.createElement("label");
        lwLabel.textContent = "粗细:";
        this.lwGroup.appendChild(lwLabel);
        this.lwSlider = document.createElement("input");
        this.lwSlider.type = "range"; this.lwSlider.min = 15; this.lwSlider.max = 30;
        this.lwSlider.value = this.lineWidth;
        this.lwValue = document.createElement("span");
        this.lwValue.className = "bbia-size-label";
        this.lwValue.textContent = this.lineWidth;
        this.lwSlider.addEventListener("input", () => {
            this.lineWidth = +this.lwSlider.value;
            this.lwValue.textContent = this.lineWidth;
        });
        this.lwGroup.append(this.lwSlider, this.lwValue);
        tb.appendChild(this.lwGroup);

        // Font size group (number mode only)
        this.fsGroup = document.createElement("div");
        this.fsGroup.style.cssText = "display:none;align-items:center;gap:8px;";
        this.fsGroup.appendChild(this._sep());
        const fsLabel = document.createElement("label");
        fsLabel.textContent = "字号:";
        this.fsGroup.appendChild(fsLabel);
        this.fsSlider = document.createElement("input");
        this.fsSlider.type = "range"; this.fsSlider.min = 100; this.fsSlider.max = 800;
        this.fsSlider.value = this.fontSize;
        this.fsValue = document.createElement("span");
        this.fsValue.className = "bbia-size-label";
        this.fsValue.textContent = this.fontSize;
        this.fsSlider.addEventListener("input", () => {
            this.fontSize = +this.fsSlider.value;
            this.fsValue.textContent = this.fontSize;
        });
        this.fsGroup.append(this.fsSlider, this.fsValue);
        tb.appendChild(this.fsGroup);

        container.appendChild(tb);

        /* Canvas area */
        const canvasWrap = document.createElement("div");
        canvasWrap.className = "bbia-canvas-wrap";
        this.canvas = document.createElement("canvas");
        this.ctx = this.canvas.getContext("2d");
        canvasWrap.appendChild(this.canvas);
        container.appendChild(canvasWrap);

        /* Bottom bar */
        const bottom = document.createElement("div");
        bottom.className = "bbia-bottom";

        const btnCancel = document.createElement("button");
        btnCancel.className = "bbia-btn-cancel";
        btnCancel.textContent = "取消";
        btnCancel.addEventListener("click", () => this.close());

        const btnUndo = document.createElement("button");
        btnUndo.className = "bbia-btn-undo";
        btnUndo.textContent = "撤销";
        btnUndo.addEventListener("click", () => this._undo());

        const btnUndoAll = document.createElement("button");
        btnUndoAll.className = "bbia-btn-undo";
        btnUndoAll.textContent = "撤销所有";
        btnUndoAll.addEventListener("click", () => this._undoAll());

        const btnSave = document.createElement("button");
        btnSave.className = "bbia-btn-save";
        btnSave.textContent = "保存编辑";
        btnSave.addEventListener("click", () => this._save());

        bottom.append(btnCancel, btnUndo, btnUndoAll, btnSave);
        container.appendChild(bottom);

        this.overlay.appendChild(container);
        document.body.appendChild(this.overlay);

        /* Init canvas */
        this._initCanvas();

        /* Keyboard: Escape to close, Ctrl+Z to undo */
        this._keyHandler = (e) => {
            if (e.key === "Escape") this.close();
            if ((e.ctrlKey || e.metaKey) && e.key === "z") { e.preventDefault(); this._undo(); }
        };
        document.addEventListener("keydown", this._keyHandler);
    }

    _sep() {
        const d = document.createElement("div");
        d.style.cssText = "width:1px;height:22px;background:#555;margin:0 4px;";
        return d;
    }

    _toolBtn(label, tool) {
        const btn = document.createElement("button");
        btn.className = "bbia-tool-btn" + (tool === this.tool ? " active" : "");
        btn.textContent = label;
        btn.addEventListener("click", () => {
            this.tool = tool;
            this.btnRect.classList.toggle("active", tool === "rect");
            this.btnNum.classList.toggle("active", tool === "number");
            this._updateToolControls();
        });
        return btn;
    }

    _setColor(c, idx) {
        this.color = c;
        this.colorBtns.forEach((b, i) => b.classList.toggle("active", i === idx));
    }

    _updateToolControls() {
        if (this.lwGroup) this.lwGroup.style.display = this.tool === "rect" ? "flex" : "none";
        if (this.fsGroup) this.fsGroup.style.display = this.tool === "number" ? "flex" : "none";
    }

    /* ---- Canvas ---- */
    _initCanvas() {
        const img = this.sourceImage;
        // Fit to viewport while maintaining pixel ratio
        const maxW = Math.min(window.innerWidth * 0.88, img.naturalWidth);
        const maxH = Math.min(window.innerHeight * 0.72, img.naturalHeight);
        const scale = Math.min(maxW / img.naturalWidth, maxH / img.naturalHeight, 1);
        const dispW = Math.round(img.naturalWidth * scale);
        const dispH = Math.round(img.naturalHeight * scale);

        this.canvas.width = img.naturalWidth;
        this.canvas.height = img.naturalHeight;
        this.canvas.style.width = dispW + "px";
        this.canvas.style.height = dispH + "px";
        this.displayScale = scale;

        this._redraw();
        this._bindEvents();
    }

    _toImageCoords(e) {
        const rect = this.canvas.getBoundingClientRect();
        return {
            x: (e.clientX - rect.left) / this.displayScale,
            y: (e.clientY - rect.top) / this.displayScale,
        };
    }

    _bindEvents() {
        this.canvas.addEventListener("mousedown", (e) => {
            if (e.button !== 0) return;
            const pos = this._toImageCoords(e);
            if (this.tool === "rect") {
                this.dragging = true;
                this.dragStart = pos;
            } else if (this.tool === "number") {
                this.annotations.push({
                    type: "number",
                    x: pos.x, y: pos.y,
                    num: this.nextNumber++,
                    color: this.color,
                    fontSize: this.fontSize,
                });
                this._redraw();
            }
        });

        this.canvas.addEventListener("mousemove", (e) => {
            if (!this.dragging) return;
            const pos = this._toImageCoords(e);
            this._redraw();
            // Draw live preview rectangle
            this._drawRect(this.dragStart.x, this.dragStart.y, pos.x, pos.y, this.color, this.lineWidth, true);
        });

        const endDrag = (e) => {
            if (!this.dragging) return;
            this.dragging = false;
            const pos = this._toImageCoords(e);
            const dx = Math.abs(pos.x - this.dragStart.x);
            const dy = Math.abs(pos.y - this.dragStart.y);
            if (dx > 4 || dy > 4) {
                this.annotations.push({
                    type: "rect",
                    x1: this.dragStart.x, y1: this.dragStart.y,
                    x2: pos.x, y2: pos.y,
                    color: this.color,
                    lineWidth: this.lineWidth,
                });
            }
            this._redraw();
        };
        this.canvas.addEventListener("mouseup", endDrag);
        this.canvas.addEventListener("mouseleave", endDrag);
    }

    _redraw() {
        const ctx = this.ctx;
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        ctx.drawImage(this.sourceImage, 0, 0);
        for (const a of this.annotations) {
            if (a.type === "rect") {
                this._drawRect(a.x1, a.y1, a.x2, a.y2, a.color, a.lineWidth, false);
            } else if (a.type === "number") {
                this._drawNumber(a.x, a.y, a.num, a.color, a.fontSize);
            }
        }
    }

    _drawRect(x1, y1, x2, y2, color, lw, dashed) {
        const ctx = this.ctx;
        ctx.save();
        ctx.strokeStyle = color;
        ctx.lineWidth = lw;
        if (dashed) ctx.setLineDash([8, 4]);
        ctx.strokeRect(
            Math.min(x1, x2), Math.min(y1, y2),
            Math.abs(x2 - x1), Math.abs(y2 - y1),
        );
        ctx.restore();
    }

    _drawNumber(x, y, num, color, fontSize) {
        const ctx = this.ctx;
        ctx.save();
        ctx.font = `900 ${fontSize}px 'Inter', 'Arial Black', sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        // Outline for contrast
        ctx.lineWidth = Math.max(3, fontSize / 8);
        ctx.strokeStyle = color === "#FFFFFF" ? "#000" : "rgba(0,0,0,0.7)";
        ctx.lineJoin = "round";
        ctx.strokeText(String(num), x, y);

        // Fill
        ctx.fillStyle = color;
        ctx.fillText(String(num), x, y);
        ctx.restore();
    }

    /* ---- Actions ---- */
    _undo() {
        const removed = this.annotations.pop();
        if (removed && removed.type === "number") {
            // Re-sync next number counter
            this.nextNumber = 1;
            for (const a of this.annotations) {
                if (a.type === "number") this.nextNumber = Math.max(this.nextNumber, a.num + 1);
            }
        }
        this._redraw();
    }

    _undoAll() {
        this.annotations = [];
        this.nextNumber = 1;
        this._redraw();
    }

    _save() {
        // Flatten annotations onto canvas and export
        this._redraw();
        const dataUrl = this.canvas.toDataURL("image/png");
        this.onSave(dataUrl, this.annotations, this.nextNumber);
        this._cleanup();
    }

    close() {
        // Cancel — still persist annotations for next open
        if (this.onClose) this.onClose(this.annotations, this.nextNumber);
        this._cleanup();
    }

    _cleanup() {
        document.removeEventListener("keydown", this._keyHandler);
        this.overlay.remove();
    }
}

/* ──────────────────── ComfyUI Extension ──────────────────── */
app.registerExtension({
    name: "Batchbox.ImageAnnotator",

    async beforeRegisterNodeDef(nodeType, nodeData, _app) {
        if (nodeData.name !== NODE_TYPE) return;

        /* ---- onNodeCreated: add widgets & drop handling ---- */
        const origOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origOnNodeCreated?.apply(this, arguments);

            // Internal state
            this._annotatorSourceImg = null;   // HTMLImageElement of the loaded source
            this._annotatorEditedB64 = "";     // base64 of last saved edit
            this._annotatorSourceName = "";    // uploaded filename
            this._annotatorAnnotations = [];   // cached annotation objects
            this._annotatorNextNumber = 1;     // next number counter

            /* --- Upload button widget --- */
            const uploadBtn = this.addWidget("button", "上传图片", null, () => {
                const input = document.createElement("input");
                input.type = "file";
                input.accept = "image/*";
                input.onchange = async () => {
                    const file = input.files[0];
                    if (!file) return;
                    await this._annotatorLoadFile(file);
                };
                input.click();
            });

            /* --- Open Editor button --- */
            const editBtn = this.addWidget("button", "✏️ 打开编辑器", null, () => {
                this._annotatorOpenEditor();
            });

            // Make node a bit wider for comfortable button layout
            if (this.size[0] < 280) this.size[0] = 280;
        };

        /* ---- Load image file ---- */
        nodeType.prototype._annotatorLoadFile = async function (file) {
            const uploaded = await uploadImageToInput(file);
            if (!uploaded) return;

            // Clear any previous state — only one image source at a time
            this._annotatorEditedB64 = "";
            this._annotatorSourceName = uploaded;
            this._annotatorAnnotations = [];  // new image → clear drawings
            this._annotatorNextNumber = 1;
            const editWidget = this.widgets?.find(w => w.name === "_edited_image_b64");
            if (editWidget) editWidget.value = "";
            // Mark source as local (last-write-wins)
            const modeWidget = this.widgets?.find(w => w.name === "_source_mode");
            if (modeWidget) modeWidget.value = "local";

            // Update hidden widget
            const srcWidget = this.widgets?.find(w => w.name === "_source_image_name");
            if (srcWidget) srcWidget.value = uploaded;

            // Load preview
            const url = api.apiURL(`/view?filename=${encodeURIComponent(uploaded)}&type=input&rand=${Date.now()}`);
            const img = new Image();
            img.crossOrigin = "anonymous";
            img.onload = () => {
                this._annotatorSourceImg = img;
                // Show ONLY this image on the node (replace, not append)
                this.imgs = [img];
                this.setSizeForImage?.();
                this.setDirtyCanvas(true, true);
                app.graph.setDirtyCanvas(true, true);
            };
            img.src = url;
        };

        /* ---- Load image from upstream tensor (via preview URL) ---- */
        nodeType.prototype._annotatorLoadFromUpstream = function () {
            // If we have an edited image, use that; otherwise try upstream preview
            if (this._annotatorSourceImg) return;
            // Will be populated if upstream node ran and we have imgs from ComfyUI
        };

        /* ---- Open Editor ---- */
        nodeType.prototype._annotatorOpenEditor = function () {
            let imgEl = this._annotatorSourceImg;

            // If no local source, try to grab preview from upstream connected node
            if (!imgEl && (!this.imgs || this.imgs.length === 0)) {
                const link = this.getInputLink(0); // slot 0 = "image"
                if (link) {
                    const upstreamNode = app.graph.getNodeById(link.origin_id);
                    if (upstreamNode && upstreamNode.imgs && upstreamNode.imgs.length > 0) {
                        imgEl = upstreamNode.imgs[0];
                        this._annotatorSourceImg = imgEl;
                    }
                }
            }

            // If still nothing, check our own imgs (set by ComfyUI after execution)
            if (!imgEl && this.imgs && this.imgs.length > 0) {
                imgEl = this.imgs[0];
                this._annotatorSourceImg = imgEl;
            }

            if (!imgEl) {
                alert("请先上传一张图片或从左侧连接一个图像节点（连接后需先运行一次上游节点）");
                return;
            }

            // Ensure the image is fully loaded
            if (!imgEl.complete || imgEl.naturalWidth === 0) {
                alert("图片尚未加载完成，请稍后再试");
                return;
            }

            new ImageAnnotatorEditor(
                imgEl,
                // onSave
                (base64, annotations, nextNum) => {
                    this._annotatorEditedB64 = base64;
                    this._annotatorAnnotations = annotations;
                    this._annotatorNextNumber = nextNum;
                    // Push to hidden widget
                    const w = this.widgets?.find(w => w.name === "_edited_image_b64");
                    if (w) w.value = base64;

                    // Update preview on node with the edited version
                    const preview = new Image();
                    preview.onload = () => {
                        this.imgs = [preview];
                        this.setSizeForImage?.();
                        this.setDirtyCanvas(true, true);
                        app.graph.setDirtyCanvas(true, true);
                    };
                    preview.src = base64;
                },
                // onClose (cancel) — still cache annotations
                (annotations, nextNum) => {
                    this._annotatorAnnotations = annotations;
                    this._annotatorNextNumber = nextNum;
                },
                // Restore cached annotations
                this._annotatorAnnotations,
                this._annotatorNextNumber,
            );
        };

        /* ---- Handle drag & drop onto the node ---- */
        const origOnDropFile = nodeType.prototype.onDropFile;
        nodeType.prototype.onDropFile = function (file) {
            if (origOnDropFile) origOnDropFile.apply(this, arguments);
            const ext = getExtension(file.name);
            if (IMG_EXTS.has(ext)) {
                this._annotatorLoadFile(file);
                return true;
            }
            return false;
        };

        /* ---- Connection change: detect upstream wire connect/disconnect ---- */
        const origOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (side, slotIndex, connected, linkInfo, ioSlot) {
            origOnConnectionsChange?.apply(this, arguments);
            // side 1 = input, slotIndex 0 = "image"
            if (side === 1 && slotIndex === 0) {
                if (connected) {
                    // Upstream wire just connected → clear local, switch to upstream mode
                    this._annotatorEditedB64 = "";
                    this._annotatorSourceName = "";
                    this._annotatorSourceImg = null;
                    this._annotatorAnnotations = [];  // new source → clear drawings
                    this._annotatorNextNumber = 1;
                    const ew = this.widgets?.find(w => w.name === "_edited_image_b64");
                    if (ew) ew.value = "";
                    const sw = this.widgets?.find(w => w.name === "_source_image_name");
                    if (sw) sw.value = "";
                    const mw = this.widgets?.find(w => w.name === "_source_mode");
                    if (mw) mw.value = "upstream";

                    // Try to show upstream preview immediately
                    const link = this.getInputLink(0);
                    if (link) {
                        const upNode = app.graph.getNodeById(link.origin_id);
                        if (upNode?.imgs?.length > 0) {
                            this._annotatorSourceImg = upNode.imgs[0];
                            this.imgs = [upNode.imgs[0]];
                            this.setSizeForImage?.();
                            this.setDirtyCanvas(true, true);
                        } else {
                            this.imgs = [];
                            this.setDirtyCanvas(true, true);
                        }
                    }
                } else {
                    // Wire disconnected → clear upstream preview, keep any local
                    if (!this._annotatorSourceName) {
                        this._annotatorSourceImg = null;
                        this.imgs = [];
                        this.setDirtyCanvas(true, true);
                    }
                }
            }
        };

        /* ---- Serialisation: persist state across reload ---- */
        const origOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (data) {
            origOnConfigure?.apply(this, arguments);

            // Restore source image preview from widget data
            setTimeout(() => {
                const srcWidget = this.widgets?.find(w => w.name === "_source_image_name");
                const editWidget = this.widgets?.find(w => w.name === "_edited_image_b64");

                if (editWidget?.value) {
                    // Restore edited preview
                    this._annotatorEditedB64 = editWidget.value;
                    const img = new Image();
                    img.onload = () => {
                        this._annotatorSourceImg = img;
                        this.imgs = [img];
                        this.setSizeForImage?.();
                        this.setDirtyCanvas(true, true);
                    };
                    img.src = editWidget.value;
                } else if (srcWidget?.value) {
                    this._annotatorSourceName = srcWidget.value;
                    const url = api.apiURL(`/view?filename=${encodeURIComponent(srcWidget.value)}&type=input`);
                    const img = new Image();
                    img.crossOrigin = "anonymous";
                    img.onload = () => {
                        this._annotatorSourceImg = img;
                        this.imgs = [img];
                        this.setSizeForImage?.();
                        this.setDirtyCanvas(true, true);
                    };
                    img.src = url;
                }
            }, 150);
        };
    },
});

/* ── Allow dropping images ONTO an existing BatchBoxImageAnnotator node ── */
app.registerExtension({
    name: "Batchbox.ImageAnnotator.DropTarget",

    async setup() {
        const canvasEl = document.getElementById("graph-canvas");
        if (!canvasEl) return;

        canvasEl.addEventListener("drop", async (e) => {
            const files = e.dataTransfer?.files;
            if (!files || files.length === 0) return;

            // Only intercept if there is exactly one image file
            const file = files[0];
            const ext = getExtension(file.name);
            if (!IMG_EXTS.has(ext)) return;

            // Check if it was dropped on our node type
            const graphCanvas = app.canvas;
            const [cx, cy] = graphCanvas.convertEventToCanvasOffset(e);
            const node = app.graph.getNodeOnPos(cx, cy);
            if (!node || node.type !== NODE_TYPE) return;

            // It's our node – consume the event
            e.preventDefault();
            e.stopPropagation();
            await node._annotatorLoadFile(file);
        }, true);
    },
});
