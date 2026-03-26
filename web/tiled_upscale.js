import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// --- Endpoint override helpers (mirrored from blur_upscale.js) ---
function syncEndpointOverrideExtraParams(node) {
    const toggleW = node.widgets?.find(w => w.name === "手动选择端点");
    const selectorW = node.widgets?.find(w => w.name === "endpoint_selector");
    const extraParamsWidget = node.widgets?.find(w => w.name === "extra_params");
    if (!extraParamsWidget) return;

    let existing = {};
    try {
        existing = JSON.parse(extraParamsWidget.value || "{}");
    } catch (e) {
        existing = {};
    }

    if (toggleW?.value && selectorW?.value) {
        existing.endpoint_override = selectorW.value;
    } else {
        delete existing.endpoint_override;
    }

    extraParamsWidget.value = JSON.stringify(existing);
}

async function loadUpscaleSettings() {
    try {
        const resp = await api.fetchApi("/api/batchbox/upscale-settings");
        if (resp.ok) {
            const data = await resp.json();
            const model = data.upscale_settings?.model || "";
            const endpoint = data.upscale_settings?.endpoint || "";
            const displayText = endpoint ? (model + " [" + endpoint + "]") : model;

            let endpointOptions = [];
            if (model) {
                try {
                    const schemaResp = await api.fetchApi("/api/batchbox/schema/" + model);
                    if (schemaResp.ok) {
                        const schemaData = await schemaResp.json();
                        endpointOptions = schemaData.endpoint_options || [];
                    }
                } catch (e) {
                    console.warn("[TiledUpscale] Could not load endpoint options:", e);
                }
            }

            return { displayText, model, endpoint, endpointOptions };
        }
    } catch (e) { console.warn("[TiledUpscale] Could not load upscale settings:", e); }
    return { displayText: "", model: "", endpoint: "", endpointOptions: [] };
}

function getGridFromMode(mode) {
    if (mode === "竖切3块") return [3, 1];
    if (mode === "竖切4块") return [4, 1];
    if (mode === "竖切5块") return [5, 1];
    if (mode === "横切3块") return [1, 3];
    if (mode === "横切4块") return [1, 4];
    if (mode === "横切5块") return [1, 5];
    if (mode === "2×2 四等分") return [2, 2];
    if (mode === "3×3 九宫格") return [3, 3];
    return [2, 2];
}

const COLORS = {
    bgActive: "#2a5a8f", borderActive: "#3a7abf",
    text: "#888", textActive: "#fff"
};
const BLUR_PRESETS = ["轻 (σ1-3)", "中 (σ3-6)", "重 (σ6-10)"];
const REPAIR_MODES = ["直出", "降噪"];

function drawButtonGroup(ctx, x, y, w, options, currentValue, label, theme) {
    const gap = 6, btnH = 28, labelH = 14;
    const btnW = (w - gap * (options.length - 1)) / options.length;

    ctx.fillStyle = "#666";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(label, x, y + 10);

    const btnY = y + labelH + 4;
    for (let i = 0; i < options.length; i++) {
        const bx = x + i * (btnW + gap);
        const isActive = options[i] === currentValue;
        ctx.fillStyle = isActive ? theme.bgActive : "#2a2a3a";
        ctx.strokeStyle = isActive ? theme.borderActive : "#3a3a4a";
        roundRect(ctx, bx, btnY, btnW, btnH, 5);
        ctx.fill(); ctx.lineWidth = 1; ctx.stroke();
        ctx.fillStyle = isActive ? theme.textActive : theme.text;
        ctx.font = isActive ? "bold 12px sans-serif" : "12px sans-serif";
        ctx.textAlign = "center";

        let displayStr = options[i];
        if (displayStr.includes(" - ")) {
            displayStr = displayStr.split(" - ")[0];
        }
        ctx.fillText(displayStr, bx + btnW / 2, btnY + btnH / 2 + 4);
    }
    return labelH + 4 + btnH + 6;
}

function hitTestButtonGroup(x, y, w, options, clickX, clickY, startY) {
    const gap = 6, btnH = 28, labelH = 14;
    const btnW = (w - gap * (options.length - 1)) / options.length;
    const btnY = startY + labelH + 4;
    if (clickY < btnY || clickY > btnY + btnH) return null;
    for (let i = 0; i < options.length; i++) {
        const bx = x + i * (btnW + gap);
        if (clickX >= bx && clickX <= bx + btnW) return options[i];
    }
    return null;
}

function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}

function drawCustomButton(ctx, x, y, w, isActive) {
    const btnH = 30;
    if (isActive) {
        ctx.fillStyle = "#1e3a5f";
        ctx.strokeStyle = "#2a5a8f";
        ctx.setLineDash([]);
    } else {
        ctx.fillStyle = "#2a2a3a";
        ctx.strokeStyle = "#3a3a4a";
        ctx.setLineDash([4, 3]);
    }
    roundRect(ctx, x, y, w, btnH, 6);
    ctx.fill(); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = isActive ? "#ddd" : "#888";
    ctx.font = isActive ? "bold 12px sans-serif" : "12px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("⚙️ 自定义设置 (预览模式与拼贴重合度)", x + w / 2, y + btnH / 2 + 4);
    return btnH + 6;
}

function hitTestRect(x, y, w, h, clickX, clickY) {
    return clickX >= x && clickX <= x + w && clickY >= y && clickY <= y + h;
}

// 自定义确认弹窗（替代被 ComfyUI 阻塞的原生 confirm）
function showTiledConfirmDialog(title, message, onConfirm, confirmText, cancelText) {
    // 移除旧弹窗（如果存在）
    const old = document.getElementById("tiled-confirm-dialog-bg");
    if (old) old.remove();

    const bg = document.createElement("div");
    bg.id = "tiled-confirm-dialog-bg";
    Object.assign(bg.style, {
        position: "fixed", top: "0", left: "0", width: "100%", height: "100%",
        zIndex: "99999", background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)",
        display: "flex", alignItems: "center", justifyContent: "center"
    });

    const box = document.createElement("div");
    Object.assign(box.style, {
        background: "#1c1c2e", borderRadius: "12px", padding: "30px 36px",
        maxWidth: "420px", width: "90%", boxShadow: "0 8px 32px rgba(0,0,0,0.6)",
        border: "1px solid #3a3a5a", textAlign: "center"
    });

    const titleEl = document.createElement("div");
    Object.assign(titleEl.style, { fontSize: "18px", fontWeight: "bold", color: "#ffcc00", marginBottom: "16px" });
    titleEl.textContent = title;

    const msgEl = document.createElement("div");
    Object.assign(msgEl.style, { fontSize: "14px", color: "#ccc", marginBottom: "24px", lineHeight: "1.6", whiteSpace: "pre-wrap" });
    msgEl.textContent = message;

    const btnRow = document.createElement("div");
    Object.assign(btnRow.style, { display: "flex", gap: "12px", justifyContent: "center" });

    const cancelBtn = document.createElement("button");
    Object.assign(cancelBtn.style, {
        padding: "10px 28px", background: "#333", color: "#ccc", border: "1px solid #555",
        borderRadius: "6px", cursor: "pointer", fontSize: "14px", fontWeight: "bold"
    });
    cancelBtn.textContent = cancelText || "返回选择";
    cancelBtn.onclick = () => { bg.remove(); };

    const confirmBtn = document.createElement("button");
    Object.assign(confirmBtn.style, {
        padding: "10px 28px", background: "#2a5a8f", color: "#fff", border: "none",
        borderRadius: "6px", cursor: "pointer", fontSize: "14px", fontWeight: "bold"
    });
    confirmBtn.textContent = confirmText || "放大全部";
    confirmBtn.onclick = () => { bg.remove(); if (onConfirm) onConfirm(); };

    btnRow.appendChild(cancelBtn);
    btnRow.appendChild(confirmBtn);
    box.appendChild(titleEl);
    box.appendChild(msgEl);
    box.appendChild(btnRow);
    bg.appendChild(box);
    document.body.appendChild(bg);
}

app.registerExtension({
    name: "Batchbox.TiledUpscale",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "TiledUpscale") {
            const origOnNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (origOnNodeCreated) {
                    origOnNodeCreated.apply(this, arguments);
                }

                this.properties = this.properties || {};
                this._tiledUI = {};
                this._tiledUI._selectedTiles = new Set(); // 存储选中的区块 key: "col_row"

                // 创建 extra_params widget（ComfyUI 的 hidden input 不会自动创建前端 widget）
                let extraParamsW = this.widgets?.find(w => w.name === "extra_params");
                if (!extraParamsW) {
                    extraParamsW = this.addWidget("text", "extra_params", "{}", () => { });
                    extraParamsW.serialize = true;
                    // 隐藏这个 widget（用户不需要看到）
                    extraParamsW.computeSize = () => [0, -4];
                    extraParamsW.type = "converted-widget";
                }

                // Add the Generate Button
                const nodeSelf = this;
                let generateBtn = this.widgets?.find(w => w.name === "▶ 开始生成");
                if (!generateBtn) {
                    generateBtn = this.addWidget("button", "▶ 开始生成", null, () => {
                        // 写入选中区块到 extra_params
                        const selectedSet = nodeSelf._tiledUI ? nodeSelf._tiledUI._selectedTiles : null;
                        const extraW = nodeSelf.widgets?.find(w => w.name === "extra_params");
                        if (extraW) {
                            let ep = {};
                            try { ep = JSON.parse(extraW.value || "{}"); } catch (e) { ep = {}; }
                            if (selectedSet && selectedSet.size > 0) {
                                ep._selected_tiles = Array.from(selectedSet);
                            } else {
                                delete ep._selected_tiles;
                            }
                            extraW.value = JSON.stringify(ep);
                        }

                        const hasSelection = selectedSet && selectedSet.size > 0;

                        function doGenerate() {
                            const seedWidget = nodeSelf.widgets?.find(w => w.name === "seed");
                            if (seedWidget) {
                                seedWidget.value = Math.floor(Math.random() * 2147483647);
                            }

                            // 计算总区块数用于初始显示
                            const selSet = nodeSelf._tiledUI ? nodeSelf._tiledUI._selectedTiles : null;
                            const tileCount = (selSet && selSet.size > 0) ? selSet.size : (() => {
                                const modeW = nodeSelf.widgets?.find(w => w.name === "tile_mode");
                                const grid = getGridFromMode(modeW?.value || "2×2 四等分");
                                return grid[0] * grid[1];
                            })();

                            generateBtn.name = "⏳ 生成中 0/" + tileCount;
                            nodeSelf.setDirtyCanvas(true, true);

                            // 监听 ComfyUI 原生 progress 事件 (由 ProgressBar 发送)
                            const myNodeId = String(nodeSelf.id);
                            function onProgress(evt) {
                                const d = evt.detail;
                                if (d && typeof d.value === "number" && typeof d.max === "number") {
                                    generateBtn.name = "⏳ 生成中 " + d.value + "/" + d.max;
                                    nodeSelf.setDirtyCanvas(true, true);
                                }
                            }
                            function onExecuted(evt) {
                                // 只在本节点执行完毕时恢复按钮
                                const d = evt.detail;
                                if (d && d.node && String(d.node) !== myNodeId) return;
                                cleanup();
                                setTimeout(() => {
                                    generateBtn.name = "▶ 开始生成";
                                    nodeSelf.setDirtyCanvas(true, true);
                                }, 500);
                            }
                            function cleanup() {
                                api.removeEventListener("progress", onProgress);
                                api.removeEventListener("executed", onExecuted);
                                api.removeEventListener("execution_error", onError);
                            }
                            function onError() {
                                cleanup();
                                generateBtn.name = "▶ 开始生成";
                                nodeSelf.setDirtyCanvas(true, true);
                            }
                            api.addEventListener("progress", onProgress);
                            api.addEventListener("executed", onExecuted);
                            api.addEventListener("execution_error", onError);

                            // 安全兜底：120秒后强制恢复
                            setTimeout(() => {
                                cleanup();
                                if (generateBtn.name.startsWith("⏳")) {
                                    generateBtn.name = "▶ 开始生成";
                                    nodeSelf.setDirtyCanvas(true, true);
                                }
                            }, 120000);

                            const queueBtn = document.getElementById("queue-button");
                            if (queueBtn) {
                                queueBtn.click();
                            } else {
                                app.queuePrompt(0, 1);
                            }
                        }

                        if (hasSelection) {
                            // 有选区，直接生成
                            doGenerate();
                        } else {
                            // 无选区，弹出自定义确认框
                            showTiledConfirmDialog(
                                "⚠️ 未选择任何区块",
                                "是否放大全部区块？这将消耗更多算力。\n\n你可以在自定义设置面板中点击区块来选择要放大的区域。",
                                doGenerate
                            );
                        }
                    });
                }

                // Move button to the top
                const widgets = this.widgets;
                const btnIndex = widgets.indexOf(generateBtn);
                if (btnIndex > 0) {
                    widgets.splice(btnIndex, 1);
                    widgets.splice(0, 0, generateBtn);
                }

                // Hide unwanted widgets including style_prompt and new overlap
                const widgetsToHide = ["seed", "control_after_generate", "生成后控制", "style_prompt", "blur_intensity", "repair_mode", "overlap", "tile_mode"];
                const hideWidget = (w) => {
                    w.hidden = true;
                    w.computeSize = () => [0, -4];
                    w.type = "hidden";
                    w.mouse = () => true;
                };

                const hideAllManaged = () => {
                    for (const widget of this.widgets || []) {
                        if (widgetsToHide.includes(widget.name)) {
                            hideWidget(widget);
                            if (widget.name === "control_after_generate" || widget.name === "生成后控制") {
                                widget.value = "randomize";
                            }
                        }
                    }
                };

                hideAllManaged();
                setTimeout(() => { hideAllManaged(); if (this.setDirtyCanvas) this.setDirtyCanvas(true, true); }, 100);

                // Add Canvas Spacer for UI rendering
                const SPACER_HEIGHT = 150;
                const spacer = this.addWidget("custom", "_tiled_spacer", "", () => { });
                spacer._isSpacer = true;
                spacer.serialize = false;
                spacer.computeSize = () => [this.size[0], SPACER_HEIGHT];
                spacer.draw = function () { };
                spacer.mouse = function (event, pos, nodeRef) {
                    if (event.type !== "pointerdown" && event.type !== "mousedown") return true;

                    const padding = 10;
                    const innerW = nodeRef.size[0] - padding * 2;
                    const clickX = pos[0];
                    const clickY = pos[1];
                    const ui = nodeRef._tiledUI;
                    if (!ui) return true;

                    // Blur intensity hit test
                    const blurHit = hitTestButtonGroup(padding, 0, innerW, BLUR_PRESETS, clickX, clickY, ui.blurGroupY);
                    if (blurHit) {
                        const w = nodeRef.widgets?.find(w => w.name === "blur_intensity");
                        if (w) { w.value = blurHit; w.callback?.(blurHit); }
                        nodeRef.setDirtyCanvas(true, true);
                        return true;
                    }

                    // Repair mode hit test
                    const modeHit = hitTestButtonGroup(padding, 0, innerW, REPAIR_MODES, clickX, clickY, ui.modeGroupY);
                    if (modeHit) {
                        const w = nodeRef.widgets?.find(w => w.name === "repair_mode");
                        if (w) { w.value = modeHit; w.callback?.(modeHit); }
                        nodeRef.setDirtyCanvas(true, true);
                        return true;
                    }

                    // Custom Panel button hit test
                    if (hitTestRect(padding, ui.customBtnY - 20, innerW, 30, clickX, clickY)) {
                        openCustomPanel(nodeRef);
                        return true;
                    }

                    return true;
                };

                // Override onDrawForeground to draw buttons
                const origDraw = this.onDrawForeground;
                let _cachedBlurWidget = null;
                let _cachedModeWidget = null;
                let _widgetCacheValid = false;

                function ensureWidgetCache(node) {
                    if (_widgetCacheValid && _cachedBlurWidget && _cachedModeWidget) return;
                    const widgets = node.widgets;
                    if (!widgets) return;
                    _cachedBlurWidget = widgets.find(w => w.name === "blur_intensity") || null;
                    _cachedModeWidget = widgets.find(w => w.name === "repair_mode") || null;
                    _widgetCacheValid = true;
                }

                this.onDrawForeground = function (ctx) {
                    if (origDraw) origDraw.apply(this, arguments);

                    const padding = 10;
                    const innerW = this.size[0] - padding * 2;
                    let startY = (spacer.last_y || 30) + 4;

                    ensureWidgetCache(this);

                    // 1. Blur Intensity
                    const blurVal = _cachedBlurWidget?.value || "轻 (σ1-3)";
                    this._tiledUI.blurGroupY = startY;
                    const h1 = drawButtonGroup(ctx, padding, startY, innerW, BLUR_PRESETS, blurVal, "模糊程度", {
                        bgActive: COLORS.bgActive, borderActive: COLORS.borderActive,
                        text: COLORS.text, textActive: COLORS.textActive,
                    });
                    startY += h1;

                    // 2. Repair Mode
                    const modeVal = _cachedModeWidget?.value || "直出";
                    this._tiledUI.modeGroupY = startY;
                    const h2 = drawButtonGroup(ctx, padding, startY, innerW, REPAIR_MODES, modeVal, "修复模式", {
                        bgActive: COLORS.bgActive, borderActive: COLORS.borderActive,
                        text: COLORS.text, textActive: COLORS.textActive,
                    });
                    startY += h2;

                    // 3. Custom Settings Button
                    this._tiledUI.customBtnY = startY + 20;

                    // Persist highlighted state if customized values exist
                    const isCustomized = this.properties?._tiled_customized || this._tiledUI._isCustomActive;
                    const h3 = drawCustomButton(ctx, padding, startY, innerW, isCustomized);
                    startY += h3;
                };

                // Handle image preview rendering natively on the node canvas
                const origOnExecuted = this.onExecuted;
                this.onExecuted = function (message) {
                    if (origOnExecuted) {
                        origOnExecuted.apply(this, arguments);
                    }
                    if (message && message.images) {
                        this.images = message.images;
                        this.imageIndex = 0;
                        this.imgs = message.images.map(img => {
                            const url = api.apiURL("/view?filename=" + encodeURIComponent(img.filename) + "&subfolder=" + encodeURIComponent(img.subfolder || "") + "&type=" + (img.type || "output"));
                            const imgEl = new Image();
                            imgEl.src = url;
                            return imgEl;
                        });
                        this.setDirtyCanvas(true, true);
                        if (generateBtn) {
                            generateBtn.name = "▶ 开始生成";
                        }
                    }
                };

                // Cleanup on Removal
                const origRemoved = this.onRemoved;
                this.onRemoved = function () {
                    if (origRemoved) origRemoved.apply(this, arguments);
                    closeCustomPanel();
                };

                // --- Load endpoint options and add endpoint selector widgets ---
                const nodeRef = this;
                loadUpscaleSettings().then(({ displayText, model, endpoint, endpointOptions }) => {
                    nodeRef._tiledUI._upscaleModel = model;
                    nodeRef._tiledUI._savedEndpoint = endpoint;
                    nodeRef._tiledUI._modelDisplay = displayText;
                    nodeRef.setDirtyCanvas(true);

                    if (endpointOptions && endpointOptions.length >= 2) {
                        const options = endpointOptions.map(ep => ep.name);
                        const pendingEndpointState = nodeRef._pendingEndpointState;
                        const initialManualEnabled = pendingEndpointState?.manualEnabled || false;
                        const initialEndpoint = (
                            pendingEndpointState?.selectedEndpoint && options.includes(pendingEndpointState.selectedEndpoint)
                        ) ? pendingEndpointState.selectedEndpoint : (
                            endpoint && options.includes(endpoint) ? endpoint : options[0]
                        );
                        if (pendingEndpointState) {
                            delete nodeRef._pendingEndpointState;
                        }

                        const toggleWidget = nodeRef.addWidget("toggle", "手动选择端点", initialManualEnabled, (v) => {
                            if (selectorWidget) {
                                selectorWidget.hidden = !v;
                            }
                            syncEndpointOverrideExtraParams(nodeRef);
                            const currentWidth = nodeRef.size[0];
                            const computedSize = nodeRef.computeSize();
                            nodeRef.setSize([currentWidth, computedSize[1]]);
                        });
                        toggleWidget.serialize = false;

                        const selectorWidget = nodeRef.addWidget("combo", "endpoint_selector", initialEndpoint, () => { }, {
                            values: options
                        });
                        selectorWidget.hidden = !initialManualEnabled;
                        selectorWidget.serialize = false;
                        selectorWidget.callback = () => syncEndpointOverrideExtraParams(nodeRef);

                        syncEndpointOverrideExtraParams(nodeRef);

                        const currentWidth = nodeRef.size[0];
                        const computedSize = nodeRef.computeSize();
                        nodeRef.setSize([currentWidth, computedSize[1]]);
                    }
                });

                // --- Inject endpoint_override into extra_params before execution ---
                const origExecute = this.onExecute;
                this.onExecute = function () {
                    if (origExecute) origExecute.apply(this, arguments);
                    syncEndpointOverrideExtraParams(nodeRef);
                };
            };

            // --- Serialization: persist endpoint toggle state ---
            const origOnSerialize = nodeType.prototype.onSerialize;
            nodeType.prototype.onSerialize = function (o) {
                if (origOnSerialize) origOnSerialize.apply(this, arguments);
                const toggleWidget = this.widgets?.find(w => w.name === "手动选择端点");
                const selectorWidget = this.widgets?.find(w => w.name === "endpoint_selector");
                if (toggleWidget || selectorWidget) {
                    o.endpointState = {
                        manualEnabled: toggleWidget?.value || false,
                        selectedEndpoint: selectorWidget?.value || "",
                    };
                }
            };

            // --- Deserialization: restore endpoint toggle state ---
            const origOnConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (o) {
                if (origOnConfigure) origOnConfigure.apply(this, arguments);
                if (!o.endpointState) return;

                const toggleWidget = this.widgets?.find(w => w.name === "手动选择端点");
                const selectorWidget = this.widgets?.find(w => w.name === "endpoint_selector");
                if (toggleWidget && selectorWidget) {
                    toggleWidget.value = !!o.endpointState.manualEnabled;
                    if (o.endpointState.selectedEndpoint) {
                        selectorWidget.value = o.endpointState.selectedEndpoint;
                    }
                    selectorWidget.hidden = !toggleWidget.value;
                    syncEndpointOverrideExtraParams(this);
                } else {
                    this._pendingEndpointState = o.endpointState;
                }
            };
        }
    }
});

// ----------------------------------------------------------------------
// Custom Panel Logic
// ----------------------------------------------------------------------

function getLinkedInputImageUrl(node) {
    const inputLink = node.inputs?.[0]?.link;
    if (!inputLink || !app.graph) return null;
    const linkInfo = app.graph.links[inputLink];
    if (!linkInfo) return null;
    const srcNode = app.graph.getNodeById(linkInfo.origin_id);
    if (!srcNode) return null;
    if (srcNode.imgs?.length > 0 && srcNode.imgs[0].src) return srcNode.imgs[0].src;
    const previewInfo = srcNode.images?.[0];
    if (previewInfo?.filename) {
        return api.apiURL("/view?filename=" + encodeURIComponent(previewInfo.filename) + "&subfolder=" + encodeURIComponent(previewInfo.subfolder || "") + "&type=" + (previewInfo.type || "output"));
    }
    const imageWidget = srcNode.widgets?.find(w => w.name === "image" && typeof w.value === "string" && w.value);
    if (imageWidget) {
        return api.apiURL("/view?filename=" + encodeURIComponent(imageWidget.value) + "&type=input");
    }
    return null;
}

let activeCustomPanel = null;
let customPanelNodeRef = null;
let activeDocumentListeners = [];

function closeCustomPanel() {
    activeDocumentListeners.forEach(({ type, fn }) => document.removeEventListener(type, fn));
    activeDocumentListeners = [];

    if (activeCustomPanel) {
        activeCustomPanel.remove();
        activeCustomPanel = null;
    }
    const bg = document.getElementById("tiled-upscale-backdrop");
    if (bg) bg.remove();

    if (customPanelNodeRef && customPanelNodeRef._tiledUI) {
        customPanelNodeRef._tiledUI._isCustomActive = false;
        customPanelNodeRef.setDirtyCanvas(true);
        customPanelNodeRef = null;
    }
}

function syncCustomPanelToNode() {
    if (!customPanelNodeRef || !activeCustomPanel) return;
    const blurObj = document.getElementById("tiled-blur-slider");
    const modeObj = document.getElementById("tiled-mode-select");
    const overObj = document.getElementById("tiled-overlap-slider");

    // Mark as customized so the button stays highlighted (per user request)
    customPanelNodeRef.properties = customPanelNodeRef.properties || {};
    customPanelNodeRef.properties._tiled_customized = true;

    // Convert slider (0.0 - 10.0) format to node matching
    if (blurObj) {
        const val = parseFloat(blurObj.value);
        let matching = "轻 (σ1-3)";
        if (val >= 6.0) matching = "重 (σ6-10)";
        else if (val >= 3.0) matching = "中 (σ3-6)";
        else matching = "轻 (σ1-3)";
        const w = customPanelNodeRef.widgets?.find(w => w.name === "blur_intensity");
        if (w) w.value = matching;
    }
    if (modeObj) {
        const w = customPanelNodeRef.widgets?.find(w => w.name === "tile_mode");
        if (w) w.value = modeObj.value;
    }
    if (overObj) {
        const w = customPanelNodeRef.widgets?.find(w => w.name === "overlap");
        if (w) w.value = parseInt(overObj.value);
    }

    // 同步选中的区块到 extra_params
    const selectedSet = customPanelNodeRef._tiledUI ? customPanelNodeRef._tiledUI._selectedTiles : null;
    const extraW = customPanelNodeRef.widgets?.find(w => w.name === "extra_params");
    if (extraW) {
        let ep = {};
        try { ep = JSON.parse(extraW.value || "{}"); } catch (e) { ep = {}; }
        if (selectedSet && selectedSet.size > 0) {
            ep._selected_tiles = Array.from(selectedSet);
        } else {
            delete ep._selected_tiles;
        }
        extraW.value = JSON.stringify(ep);
    }

    customPanelNodeRef.setDirtyCanvas(true, true);
}

function openCustomPanel(node) {
    if (activeCustomPanel) closeCustomPanel();
    customPanelNodeRef = node;
    node._tiledUI._isCustomActive = true;
    node.setDirtyCanvas(true);

    const panel = document.createElement("div");
    panel.className = "tiled-custom-panel";
    Object.assign(panel.style, {
        position: "fixed", zIndex: 9999,
        left: "5vw", top: "5vh",
        width: "90vw", height: "90vh",
        backgroundColor: "#1c1c24", border: "1px solid #3a3a4a",
        borderRadius: "8px", boxShadow: "0 10px 50px rgba(0,0,0,0.8)",
        display: "flex", flexDirection: "column",
        color: "#ddd", fontFamily: "sans-serif", overflow: "hidden"
    });

    const header = document.createElement("div");
    Object.assign(header.style, {
        padding: "10px 15px", backgroundColor: "#2a2a3a", cursor: "grab",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        borderBottom: "1px solid #3a3a4a", userSelect: "none"
    });
    header.innerHTML = "<strong>⚙️ 自定义设置 (预览与拼贴调整)</strong><span style=\"cursor:pointer; font-size: 16px;\">✕</span>";
    panel.appendChild(header);

    const body = document.createElement("div");
    Object.assign(body.style, { display: "flex", flex: 1, overflow: "hidden", position: "relative" });

    // Left Canvas Area
    const leftCol = document.createElement("div");
    Object.assign(leftCol.style, {
        flex: 1, backgroundColor: "#111", display: "flex", minWidth: 0, overflow: "hidden",
        flexDirection: "column", padding: "10px", position: "relative"
    });

    const wrapper = document.createElement("div");
    Object.assign(wrapper.style, {
        flex: 1, overflow: "auto", position: "relative",
        display: "flex", cursor: "grab",
        backgroundImage: "repeating-linear-gradient(45deg, #222 25%, transparent 25%, transparent 75%, #222 75%, #222), repeating-linear-gradient(45deg, #222 25%, #1a1a1a 25%, #1a1a1a 75%, #222 75%, #222)",
        backgroundPosition: "0 0, 10px 10px", backgroundSize: "20px 20px"
    });

    // Sub-wrapper for dual rendering architecture
    const zoomContainer = document.createElement("div");
    Object.assign(zoomContainer.style, { position: "relative", margin: "auto" });

    // Create imgEl without max constraints so it dictates the flow container size when scaled
    const imgEl = document.createElement("img");
    Object.assign(imgEl.style, { display: "block", boxShadow: "0 0 10px rgba(0,0,0,0.8)" });

    const canvas = document.createElement("canvas");
    Object.assign(canvas.style, { position: "absolute", top: "0", left: "0", cursor: "crosshair" });

    // 区块选中状态 (从 node 同步)
    const selectedTiles = node._tiledUI._selectedTiles || new Set();
    node._tiledUI._selectedTiles = selectedTiles;

    zoomContainer.appendChild(imgEl);
    zoomContainer.appendChild(canvas);
    wrapper.appendChild(zoomContainer);

    // Mouse Drag Panning Logic
    let isPanning = false;
    let panStartX, panStartY, startScrollLeft, startScrollTop;

    wrapper.addEventListener('mousedown', (e) => {
        // Prevent pan on slider interactions
        if (e.target.tagName.toLowerCase() === 'input') return;
        isPanning = true;
        wrapper.style.cursor = "grabbing";
        panStartX = e.clientX;
        panStartY = e.clientY;
        startScrollLeft = wrapper.scrollLeft;
        startScrollTop = wrapper.scrollTop;
        e.preventDefault(); // prevents image ghost dragging
    });

    const onPanMove = (e) => {
        if (!isPanning) return;
        const dx = e.clientX - panStartX;
        const dy = e.clientY - panStartY;
        wrapper.scrollLeft = startScrollLeft - dx;
        wrapper.scrollTop = startScrollTop - dy;
    };

    const onPanUp = () => {
        if (isPanning) {
            isPanning = false;
            wrapper.style.cursor = "grab";
        }
    };

    document.addEventListener('mousemove', onPanMove);
    document.addEventListener('mouseup', onPanUp);
    activeDocumentListeners.push({ type: 'mousemove', fn: onPanMove }, { type: 'mouseup', fn: onPanUp });

    // 区块选中计数标签
    const selCountDiv = document.createElement("div");
    Object.assign(selCountDiv.style, { position: "absolute", top: "10px", right: "10px", fontSize: "13px", color: "#4fc", backgroundColor: "rgba(0,0,0,0.7)", padding: "6px 12px", borderRadius: "6px", zIndex: 10, fontWeight: "bold" });
    function updateSelCount() {
        const md = modeSelect ? modeSelect.value : "2×2 四等分";
        const grid = getGridFromMode(md);
        const total = grid[0] * grid[1];
        if (selectedTiles.size > 0) {
            selCountDiv.textContent = "✅ 已选 " + selectedTiles.size + "/" + total + " 块";
            selCountDiv.style.color = "#4fc";
        } else {
            selCountDiv.textContent = "💡 点击区块选择要放大的区域";
            selCountDiv.style.color = "#aaa";
        }
    }

    const statusDiv = document.createElement("div");
    Object.assign(statusDiv.style, { position: "absolute", bottom: "10px", left: "10px", fontSize: "12px", color: "#888", backgroundColor: "rgba(0,0,0,0.6)", padding: "4px 8px", borderRadius: "4px", zIndex: 10 });
    statusDiv.textContent = "正在查找连接图源...";
    leftCol.appendChild(wrapper);
    leftCol.appendChild(statusDiv);
    leftCol.appendChild(selCountDiv);

    // Right Controls Area
    const rightCol = document.createElement("div");
    Object.assign(rightCol.style, {
        width: "280px", minWidth: "280px", flexShrink: 0, padding: "20px", borderLeft: "1px solid #3a3a4a",
        backgroundColor: "#222", overflowY: "auto"
    });

    let currentBlurValue = 2.0;
    const blurW = node.widgets?.find(w => w.name === "blur_intensity");
    if (blurW) {
        if (blurW.value.includes("σ1-3")) currentBlurValue = 2.0;
        else if (blurW.value.includes("σ3-6")) currentBlurValue = 4.5;
        else if (blurW.value.includes("σ6-10")) currentBlurValue = 8.0;
    }

    let currentMode = node.widgets?.find(w => w.name === "tile_mode")?.value || "2×2 四等分";
    let currentOverlap = node.widgets?.find(w => w.name === "overlap")?.value || 16;

    rightCol.innerHTML = `
        <div style="margin-bottom: 25px;">
            <label style="display:block; margin-bottom: 8px; color: #bbb; font-size: 13px;">🔍 预览缩放 (滚轮也可缩放)</label>
            <input type="range" id="tiled-zoom-slider" min="1" max="5" step="0.1" value="1" style="width:100%;">
            <div style="text-align:right; font-size:12px; color:#888; margin-top:4px;" id="tiled-zoom-val">100%</div>
        </div>
        <div style="height:1px; background:#3a3a4a; margin: 20px 0;"></div>
        <div style="margin-bottom: 25px;">
            <label style="display:block; margin-bottom: 8px; color: #bbb; font-size: 13px;">🖼️ 切块模式 (Tile Mode)</label>
            <select id="tiled-mode-select" style="width:100%; padding: 6px; background: #1a1a1a; color: #fff; border: 1px solid #444; border-radius: 4px;">
                <option value="2×2 四等分">2×2 四等分</option>
                <option value="3×3 九宫格">3×3 九宫格</option>
                <option value="竖切3块">竖切3块</option>
                <option value="竖切4块">竖切4块</option>
                <option value="竖切5块">竖切5块</option>
                <option value="横切3块">横切3块</option>
                <option value="横切4块">横切4块</option>
                <option value="横切5块">横切5块</option>
            </select>
        </div>
        <div style="margin-bottom: 25px;">
            <label style="display:block; margin-bottom: 8px; color: #bbb; font-size: 13px;">✂️ 切割重合像素 (Overlap Margin)</label>
            <input type="range" id="tiled-overlap-slider" min="0" max="120" step="8" value="` + currentOverlap + `" style="width:100%;">
            <div style="text-align:right; font-size:12px; color:#888; margin-top:4px;" id="tiled-overlap-val">` + currentOverlap + ` px</div>
        </div>
        <div style="height:1px; background:#3a3a4a; margin: 20px 0;"></div>
        <div style="margin-bottom: 25px;">
            <label style="display:block; margin-bottom: 8px; color: #bbb; font-size: 13px;">💧 模糊强度预览 (CSS Filter)</label>
            <input type="range" id="tiled-blur-slider" min="0" max="10" step="0.5" value="` + currentBlurValue + `" style="width:100%;">
            <div style="text-align:right; font-size:12px; color:#888; margin-top:4px;" id="tiled-blur-val">σ` + currentBlurValue + `</div>
        </div>
        <button id="tiled-apply-btn" style="width:100%; padding:10px; background:#2a5a8f; color:#fff; border:none; border-radius:5px; cursor:pointer; font-weight:bold; margin-top:20px; transition: background 0.2s;">✓ 确认并关闭设置</button>
    `;

    body.appendChild(leftCol);
    body.appendChild(rightCol);
    panel.appendChild(body);

    // Add Backdrop
    const backdrop = document.createElement("div");
    backdrop.id = "tiled-upscale-backdrop";
    Object.assign(backdrop.style, {
        position: "fixed", top: "0", left: "0", width: "100%", height: "100%",
        zIndex: "9998", background: "rgba(0,0,0,0.6)", backdropFilter: "blur(3px)"
    });
    backdrop.onclick = closeCustomPanel;
    document.body.appendChild(backdrop);
    document.body.appendChild(panel);
    activeCustomPanel = panel;

    // Attach dragging
    header.querySelector("span").onclick = closeCustomPanel;
    let isHeaderDragging = false;
    let startX, startY, startLeft, startTop;
    header.onmousedown = (e) => {
        if (e.target.tagName.toLowerCase() === 'span') return;
        isHeaderDragging = true;
        startX = e.clientX; startY = e.clientY;
        const style = window.getComputedStyle(panel);
        startLeft = parseInt(style.left); startTop = parseInt(style.top);
        document.body.style.userSelect = 'none';
    };
    const onHeaderMove = (e) => {
        if (isHeaderDragging) {
            panel.style.left = (startLeft + e.clientX - startX) + "px";
            panel.style.top = (startTop + e.clientY - startY) + "px";
        }
    };
    const onHeaderUp = () => { isHeaderDragging = false; document.body.style.userSelect = ''; };

    document.addEventListener("mousemove", onHeaderMove);
    document.addEventListener("mouseup", onHeaderUp);
    activeDocumentListeners.push({ type: 'mousemove', fn: onHeaderMove }, { type: 'mouseup', fn: onHeaderUp });

    // Destructive closure override removed; handled natively by global module IDs

    // Interactive Previews
    const zoomSlider = document.getElementById("tiled-zoom-slider");
    const zoomVal = document.getElementById("tiled-zoom-val");
    const modeSelect = document.getElementById("tiled-mode-select");
    const overlapSlider = document.getElementById("tiled-overlap-slider");
    const overlapVal = document.getElementById("tiled-overlap-val");
    const blurSlider = document.getElementById("tiled-blur-slider");
    const blurVal = document.getElementById("tiled-blur-val");

    if (Array.from(modeSelect.options).some(opt => opt.value === currentMode)) {
        modeSelect.value = currentMode;
    } else {
        modeSelect.selectedIndex = 0;
    }

    function getGridDims() {
        let cols = 2, rows = 2;
        const md = modeSelect.value;
        if (md === "竖切3块") { cols = 3; rows = 1; }
        else if (md === "竖切4块") { cols = 4; rows = 1; }
        else if (md === "竖切5块") { cols = 5; rows = 1; }
        else if (md === "横切3块") { cols = 1; rows = 3; }
        else if (md === "横切4块") { cols = 1; rows = 4; }
        else if (md === "横切5块") { cols = 1; rows = 5; }
        else if (md === "2×2 四等分") { cols = 2; rows = 2; }
        else if (md === "3×3 九宫格") { cols = 3; rows = 3; }
        return [cols, rows];
    }

    function drawGridOverlay(ctx, w, h) {
        const [cols, rows] = getGridDims();
        const step_x = w / cols;
        const step_y = h / rows;
        const ov = parseInt(overlapSlider.value);

        ctx.clearRect(0, 0, w, h);

        // 1. 绘制选中的区块（绿色高亮）
        let tileIdx = 0;
        for (let r = 0; r < rows; r++) {
            for (let c = 0; c < cols; c++) {
                const key = c + "_" + r;
                if (selectedTiles.has(key)) {
                    ctx.fillStyle = "rgba(0, 200, 100, 0.25)";
                    ctx.fillRect(c * step_x, r * step_y, step_x, step_y);
                    // 绘制选中编号
                    ctx.fillStyle = "rgba(255, 255, 255, 0.95)";
                    ctx.font = "bold 28px sans-serif";
                    ctx.textAlign = "center";
                    ctx.shadowColor = "black";
                    ctx.shadowBlur = 6;
                    ctx.fillText("✓", c * step_x + step_x / 2, r * step_y + step_y / 2 + 10);
                    ctx.shadowBlur = 0;
                    // 绘制绿色边框
                    ctx.strokeStyle = "rgba(0, 220, 120, 0.9)";
                    ctx.lineWidth = 3;
                    ctx.strokeRect(c * step_x + 2, r * step_y + 2, step_x - 4, step_y - 4);
                }
                tileIdx++;
            }
        }

        // 2. 绘制切割线（红色）
        ctx.strokeStyle = "rgba(255, 50, 50, 0.9)";
        ctx.lineWidth = 2.0;
        ctx.beginPath();
        for (let c = 1; c < cols; c++) {
            ctx.moveTo(c * step_x, 0); ctx.lineTo(c * step_x, h);
        }
        for (let r = 1; r < rows; r++) {
            ctx.moveTo(0, r * step_y); ctx.lineTo(w, r * step_y);
        }
        ctx.stroke();

        // 3. 绘制重合区域（黄色虚线）
        if (ov > 0) {
            ctx.fillStyle = "rgba(255, 200, 0, 0.3)";
            ctx.strokeStyle = "rgba(255, 200, 0, 0.8)";
            ctx.lineWidth = 1.0;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();

            for (let c = 1; c < cols; c++) {
                const cx = c * step_x;
                ctx.fillRect(cx - ov, 0, ov * 2, h);
                ctx.moveTo(cx - ov, 0); ctx.lineTo(cx - ov, h);
                ctx.moveTo(cx + ov, 0); ctx.lineTo(cx + ov, h);
            }
            for (let r = 1; r < rows; r++) {
                const cy = r * step_y;
                ctx.fillRect(0, cy - ov, w, ov * 2);
                ctx.moveTo(0, cy - ov); ctx.lineTo(w, cy - ov);
                ctx.moveTo(0, cy + ov); ctx.lineTo(w, cy + ov);
            }
            ctx.stroke();
            ctx.setLineDash([]);

            // Draw overlap indicator text
            ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
            ctx.font = "bold 16px sans-serif";
            ctx.textAlign = "center";
            ctx.shadowColor = "black";
            ctx.shadowBlur = 4;
            if (cols > 1) {
                ctx.fillText("◄ 溢出 " + ov + "px 对齐区 ►", step_x, 30);
            }
            if (rows > 1) {
                ctx.save();
                ctx.translate(30, step_y);
                ctx.rotate(-Math.PI / 2);
                ctx.fillText("◄ 溢出 " + ov + "px 对齐区 ►", 0, 0);
                ctx.restore();
            }
            ctx.shadowBlur = 0;
        }

        // 更新选中计数
        updateSelCount();
    }

    // 点击 canvas 选中/反选区块
    canvas.addEventListener("click", (e) => {
        if (!imgEl.naturalWidth) return;
        const rect = canvas.getBoundingClientRect();
        const clickX = (e.clientX - rect.left) / rect.width * canvas.width;
        const clickY = (e.clientY - rect.top) / rect.height * canvas.height;
        const [cols, rows] = getGridDims();
        const step_x = canvas.width / cols;
        const step_y = canvas.height / rows;
        const col = Math.floor(clickX / step_x);
        const row = Math.floor(clickY / step_y);
        if (col < 0 || col >= cols || row < 0 || row >= rows) return;
        const key = col + "_" + row;
        if (selectedTiles.has(key)) {
            selectedTiles.delete(key);
        } else {
            selectedTiles.add(key);
        }
        // 重绘
        const ctx2 = canvas.getContext("2d");
        drawGridOverlay(ctx2, canvas.width, canvas.height);
    });

    function updateView() {
        if (!imgEl.src) return;

        // Match canvas to image dimensions and redraw grid
        if (imgEl.naturalWidth > 0 && imgEl.naturalHeight > 0) {
            // Calculate base 100% dimensions bounded by wrapper window securely
            if (!zoomContainer._baseW) {
                const padding = 20;
                const fitRatio = Math.min(
                    (wrapper.clientWidth - padding) / imgEl.naturalWidth,
                    (wrapper.clientHeight - padding) / imgEl.naturalHeight
                );
                // The minimum ensures 1x zoom is at most 1:1 original pixels but realistically fits screen 
                zoomContainer._baseW = imgEl.naturalWidth * Math.min(1.0, fitRatio);
                zoomContainer._baseH = imgEl.naturalHeight * Math.min(1.0, fitRatio);
            }

            // Explicit dimensional scale fixes flex bounds and browser overflow mapping natively
            const scale = parseFloat(zoomSlider.value);
            const scaledW = zoomContainer._baseW * scale;
            const scaledH = zoomContainer._baseH * scale;

            zoomContainer.style.width = scaledW + "px";
            zoomContainer.style.height = scaledH + "px";

            imgEl.style.width = scaledW + "px";
            imgEl.style.height = scaledH + "px";

            // CSS Blur approximation using explicit scale ratio memory
            const sigma = parseFloat(blurSlider.value);
            if (sigma > 0) {
                const displayRatio = scaledW / imgEl.naturalWidth;
                const effectiveBlur = Math.max(0.5, sigma * displayRatio);
                imgEl.style.filter = "blur(" + effectiveBlur + "px)";
            } else {
                imgEl.style.filter = "none";
            }

            // Redraw grid scaling the canvas exactly to overlay the image pixel bound
            canvas.width = imgEl.naturalWidth;
            canvas.height = imgEl.naturalHeight;
            canvas.style.width = scaledW + "px";
            canvas.style.height = scaledH + "px";
            const ctx = canvas.getContext("2d");
            drawGridOverlay(ctx, imgEl.naturalWidth, imgEl.naturalHeight);
        }
    }

    zoomSlider.oninput = (e) => { zoomVal.textContent = Math.round(e.target.value * 100) + "%"; updateView(); };
    modeSelect.onchange = () => { selectedTiles.clear(); updateView(); syncCustomPanelToNode(); updateSelCount(); };
    overlapSlider.oninput = (e) => { overlapVal.textContent = e.target.value + " px"; updateView(); syncCustomPanelToNode(); };
    blurSlider.oninput = (e) => {
        blurVal.textContent = "σ" + e.target.value;
        updateView();
        syncCustomPanelToNode();
    };

    // Support standard mouse wheel zooming (no ctrl required)
    wrapper.addEventListener("wheel", (e) => {
        e.preventDefault();

        // Caching mouse scroll position ratio for anchoring before scale layout reflows
        const oldW = zoomContainer.offsetWidth;
        const oldH = zoomContainer.offsetHeight;

        const delta = e.deltaY > 0 ? -0.1 : 0.1;
        const newVal = Math.max(1.0, Math.min(5.0, parseFloat(zoomSlider.value) + delta));
        zoomSlider.value = newVal;
        zoomVal.textContent = Math.round(newVal * 100) + "%";
        updateView();

        // Post-scale origin displacement fix for natural zooming center
        const newW = zoomContainer.offsetWidth;
        const newH = zoomContainer.offsetHeight;
        if (newW !== oldW) {
            const rx = (e.clientX - wrapper.getBoundingClientRect().left + wrapper.scrollLeft) / oldW;
            const ry = (e.clientY - wrapper.getBoundingClientRect().top + wrapper.scrollTop) / oldH;
            wrapper.scrollLeft += (newW - oldW) * rx;
            wrapper.scrollTop += (newH - oldH) * ry;
        }
    }, { passive: false });

    const applyBtn = document.getElementById("tiled-apply-btn");
    applyBtn.onclick = () => {
        syncCustomPanelToNode();
        if (selectedTiles.size === 0) {
            showTiledConfirmDialog(
                "💡 未选择任何区块",
                "你没有选择任何要放大的区块。\n\n点击「关闭并放大全部」将在生成时放大全部区块。\n点击「返回选择」可以在预览图上点击区块来选择。",
                function () { closeCustomPanel(); },  // 确认：关闭面板
                "关闭并放大全部",
                "返回选择"
            );
        } else {
            closeCustomPanel();
        }
    };
    applyBtn.onmouseover = () => applyBtn.style.background = "#3a7abf";
    applyBtn.onmouseout = () => applyBtn.style.background = "#2a5a8f";

    // Grab original image direct from connected upstream node cache
    const imgSrc = getLinkedInputImageUrl(node);
    if (imgSrc) {
        statusDiv.textContent = "⏳ 加载图片...";
        imgEl.onload = () => {
            statusDiv.textContent = "✅ 成功解析未裁切原图";
            updateView();
        };
        imgEl.src = imgSrc;
    } else {
        statusDiv.textContent = "💡 未检测到有效输入连接。请先将【image】端点连接至上游节点并【执行一次该上游节点】。";
    }
}
