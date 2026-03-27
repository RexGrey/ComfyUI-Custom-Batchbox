/**
 * @fileoverview Gaussian Blur Upscale Node UI Extension
 * 
 * Custom UI for the GaussianBlurUpscale node:
 * - Canvas-drawn button groups for blur intensity and repair mode
 * - Hidden seed/randomize widgets (auto-managed)
 * - "▶ 开始生成" button (reuses batchboxAPI from dynamic_params.js)
 * - Custom settings → large floating DOM panel with σ slider + realtime preview
 * - Right-click canvas menu entry (added in dynamic_params.js)
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ================================================================
// SECTION 1: CONSTANTS
// ================================================================

const BLUR_PRESETS = ["轻 (σ1-3)", "中 (σ3-6)", "重 (σ6-10)"];
const REPAIR_MODES = ["直出", "降噪", "风格"];

// Dynamic style presets loaded from backend
let stylePresets = {
  "电影写实": "以电影级写实风格处理，保持自然光影和真实质感",
  "复古油画": "以古典油画风格处理，带有厚重的笔触感和温暖的色调",
  "现代数字艺术": "以现代数字艺术风格处理，色彩鲜艳，细节丰富",
  "日式动漫": "以日式动漫风格处理，线条清晰，色彩明快",
  "水墨国风": "以中国传统水墨画风格处理，注重意境和留白",
};

async function loadStylePresets() {
  try {
    const resp = await api.fetchApi("/api/batchbox/style-presets");
    if (resp.ok) {
      const data = await resp.json();
      if (data.style_presets && Object.keys(data.style_presets).length > 0) {
        stylePresets = data.style_presets;
      }
    }
  } catch (e) {
    console.warn("[BlurUpscale] Could not load style presets:", e);
  }
}

async function saveStylePresets() {
  try {
    const resp = await api.fetchApi("/api/batchbox/style-presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ style_presets: stylePresets }),
    });
    return resp.ok;
  } catch (e) {
    console.warn("[BlurUpscale] Could not save style presets:", e);
    return false;
  }
}

function requestNodeCanvasRefresh(node) {
  if (!node) return;
  if (node._batchboxCanvasRefreshPending) return;
  node._batchboxCanvasRefreshPending = true;

  requestAnimationFrame(() => {
    node._batchboxCanvasRefreshPending = false;
    if (!node.graph) return;
    node.setDirtyCanvas(true, true);
    if (app.graph) {
      app.graph.setDirtyCanvas(true, true);
    }
  });
}

function syncEndpointOverrideExtraParams(node) {
  const toggleW = node.widgets?.find(w => w.name === "手动选择端点");
  const selectorW = node.widgets?.find(w => w.name === "endpoint_selector");
  const extraParamsWidget = node.widgets?.find(w => w.name === "extra_params");
  if (!extraParamsWidget) return;

  let existing = {};
  try {
    existing = JSON.parse(extraParamsWidget.value || "{}");
  } catch {
    existing = {};
  }

  if (toggleW?.value && selectorW?.value) {
    existing.endpoint_override = selectorW.value;
  } else {
    delete existing.endpoint_override;
  }

  extraParamsWidget.value = JSON.stringify(existing);
}

// ================================================================
// SECTION 1.5: SCOPED EXECUTION (only queue target node + deps)
// ================================================================

function collectNodeDeps(nodeId, allOutputs, filtered) {
  const id = String(nodeId);
  if (!allOutputs[id] || filtered[id]) return;
  filtered[id] = allOutputs[id];
  const inputs = allOutputs[id].inputs;
  if (inputs) {
    for (const v of Object.values(inputs)) {
      if (Array.isArray(v)) collectNodeDeps(v[0], allOutputs, filtered);
    }
  }
}

async function executeScopedToNode(node) {
  // One-shot wrapper: patches api.queuePrompt for exactly ONE call,
  // then restores immediately — so other nodes aren't blocked.
  const orig = api.queuePrompt;
  api.queuePrompt = async function (index, prompt) {
    // Restore IMMEDIATELY (before awaiting) so other nodes can queue
    api.queuePrompt = orig;
    if (prompt.output) {
      const filtered = {};
      collectNodeDeps(String(node.id), prompt.output, filtered);
      prompt.output = filtered;
    }
    return await orig.apply(api, [index, prompt]);
  };
  try {
    window.batchboxAPI?.markButtonTriggeredExecution?.();
    await app.queuePrompt();
  } catch (e) {
    console.error("[BlurUpscale] Scoped execution error:", e);
    api.queuePrompt = orig;
  }
}

const COLORS = {
  bg: "#1e1e2e",
  bgHover: "#2a2a3f",
  bgActive: "#1e3a5f",
  borderActive: "#2a5a8f",
  borderStyle: "#8f5a2a",
  bgStyle: "#5f3a1e",
  text: "#aaa",
  textActive: "#fff",
  accent: "#4CAF50",
};


// ================================================================
// SECTION 2: FLOATING CUSTOM SETTINGS PANEL (DOM)
// ================================================================

let activePanel = null;

function openCustomPanel(node) {
  closeCustomPanel();

  // Custom confirm dialog (reusable)
  function showBlurConfirmDialog(title, message, onConfirm, confirmText, cancelText) {
    const old = document.getElementById("blur-confirm-dialog-bg");
    if (old) old.remove();
    const bg = document.createElement("div");
    bg.id = "blur-confirm-dialog-bg";
    Object.assign(bg.style, {
      position: "fixed", top: "0", left: "0", width: "100%", height: "100%",
      zIndex: "999999", background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)",
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
    Object.assign(cancelBtn.style, { padding: "10px 28px", background: "#333", color: "#ccc", border: "1px solid #555", borderRadius: "6px", cursor: "pointer", fontSize: "14px", fontWeight: "bold" });
    cancelBtn.textContent = cancelText || "返回选择";
    cancelBtn.onclick = () => { bg.remove(); };
    const cfmBtn = document.createElement("button");
    Object.assign(cfmBtn.style, { padding: "10px 28px", background: "#2a5a8f", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "14px", fontWeight: "bold" });
    cfmBtn.textContent = confirmText || "确定";
    cfmBtn.onclick = () => { bg.remove(); if (onConfirm) onConfirm(); };
    btnRow.append(cancelBtn, cfmBtn);
    box.append(titleEl, msgEl, btnRow);
    bg.appendChild(box);
    document.body.appendChild(bg);
  }

  const panel = document.createElement("div");
  panel.id = "blur-upscale-custom-panel";
  Object.assign(panel.style, {
    position: "fixed",
    zIndex: "99999",
    left: "2vw",
    top: "2vh",
    width: "96vw",
    height: "96vh",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
    background: "#1a1a2aee",
    border: "1px solid #3a3a4a",
    borderRadius: "14px",
    boxShadow: "0 16px 64px rgba(0,0,0,0.8)",
    padding: "24px",
    fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif",
    color: "#ddd",
    backdropFilter: "blur(10px)",
    boxSizing: "border-box",
  });

  // --- Header ---
  const header = document.createElement("div");
  Object.assign(header.style, {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    marginBottom: "20px", paddingBottom: "12px", borderBottom: "1px solid #2a2a3a",
    cursor: "grab",
  });
  const title = document.createElement("span");
  title.textContent = "🔍 自定义模糊设置";
  title.style.cssText = "font-size:16px; font-weight:600;";
  header.appendChild(title);

  const closeBtn = document.createElement("button");
  closeBtn.textContent = "✕";
  Object.assign(closeBtn.style, {
    width: "30px", height: "30px", background: "#2a2a3a", border: "1px solid #3a3a4a",
    borderRadius: "50%", color: "#888", fontSize: "15px", cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
    transition: "all 0.2s ease",
  });
  closeBtn.onmouseenter = () => { closeBtn.style.background = "#3a3a4a"; closeBtn.style.color = "#ddd"; };
  closeBtn.onmouseleave = () => { closeBtn.style.background = "#2a2a3a"; closeBtn.style.color = "#888"; };
  closeBtn.onclick = () => closeCustomPanel();
  header.appendChild(closeBtn);
  panel.appendChild(header);

  // --- Sigma Slider ---
  const sigmaSection = document.createElement("div");
  sigmaSection.style.marginBottom = "20px";

  const currentSigma = node.widgets?.find(w => w.name === "custom_sigma")?.value || 2.0;

  const sigmaLabel = document.createElement("div");
  sigmaLabel.style.cssText = "display:flex; justify-content:space-between; margin-bottom:10px; font-size:14px; color:#aaa;";
  const sigmaText = document.createElement("span");
  sigmaText.textContent = "模糊程度 (σ)";
  const sigmaVal = document.createElement("span");
  sigmaVal.textContent = currentSigma;
  sigmaVal.style.cssText = "color:#5a8abf; font-weight:700; font-size:18px;";
  sigmaLabel.append(sigmaText, sigmaVal);
  sigmaSection.appendChild(sigmaLabel);

  const slider = document.createElement("input");
  slider.type = "range";
  slider.min = "0.5";
  slider.max = "100";
  slider.step = "0.5";
  slider.value = currentSigma;
  Object.assign(slider.style, {
    width: "100%", height: "6px", borderRadius: "3px",
    WebkitAppearance: "none", outline: "none",
    background: "linear-gradient(90deg, #1a3a5f, #5f3a1a)",
  });
  // Scale ratio: CSS blur operates on display pixels, not original pixels.
  // To match real Gaussian blur on the original image:
  //   cssBlurPx = sigma * (displayedWidth / naturalWidth)
  let blurScaleRatio = 1;

  // Sigma-to-preset mapping
  const SIGMA_TO_PRESET = {
    "轻 (σ1-3)": 2.0, "中 (σ3-6)": 4.0, "重 (σ6-10)": 7.0
  };
  function sigmaToPresetLabel(sigma) {
    if (sigma <= 3) return "轻 (σ1-3)";
    if (sigma <= 6) return "中 (σ3-6)";
    return "重 (σ6-10)";
  }

  slider.oninput = () => {
    const s = parseFloat(slider.value);
    sigmaVal.textContent = s;
    const w = node.widgets?.find(w => w.name === "custom_sigma");
    if (w) w.value = s;
    // Sync: update blur_intensity preset to match sigma range
    const biw = node.widgets?.find(w => w.name === "blur_intensity");
    if (biw) { biw.value = sigmaToPresetLabel(s); }
    node.setDirtyCanvas?.(true, true);
    if (blurMode === "global" || blurMode === "tiled") {
      const img = panel.querySelector("#blur-preview-img");
      if (img) img.style.filter = `blur(${s * blurScaleRatio}px)`;
    } else if (blurMode === "mask") {
      updateMaskPreview();
    }
  };
  sigmaSection.appendChild(slider);
  panel.appendChild(sigmaSection);

  // --- Mode Toggle (全局 / 区域 / 分块 模糊) ---
  const modeSection = document.createElement("div");
  Object.assign(modeSection.style, {
    display: "flex", gap: "8px", marginBottom: "16px", alignItems: "center",
  });

  let blurMode = node.properties?._blur_mode || (node.properties?._blur_mask ? "mask" : "global");

  const modeGlobalBtn = document.createElement("button");
  modeGlobalBtn.textContent = "全局模糊";
  const modeMaskBtn = document.createElement("button");
  modeMaskBtn.textContent = "区域模糊";
  const modeSelectionBtn = document.createElement("button");
  modeSelectionBtn.textContent = "选区模糊";
  const modeTiledBtn = document.createElement("button");
  modeTiledBtn.textContent = "分块模糊";

  function styleModeBtn(btn, active) {
    Object.assign(btn.style, {
      padding: "8px 18px", fontSize: "13px", fontWeight: "500",
      border: active ? "1px solid #3a7abf" : "1px solid #3a3a4a",
      background: active ? "linear-gradient(135deg, #2a5a8f, #1a3a5f)" : "#2a2a3a",
      color: active ? "#fff" : "#888", borderRadius: "8px", cursor: "pointer",
      transition: "all 0.2s",
    });
  }
  styleModeBtn(modeGlobalBtn, blurMode === "global");
  styleModeBtn(modeMaskBtn, blurMode === "mask");
  styleModeBtn(modeSelectionBtn, blurMode === "selection");
  styleModeBtn(modeTiledBtn, blurMode === "tiled");

  // Brush size controls (only visible in mask mode)
  const brushLabel = document.createElement("span");
  brushLabel.textContent = "笔刷:";
  brushLabel.style.cssText = "color:#888; font-size:12px; margin-left:auto;";
  const brushSlider = document.createElement("input");
  brushSlider.type = "range"; brushSlider.min = "5"; brushSlider.max = "100";
  brushSlider.step = "1"; brushSlider.value = "30";
  Object.assign(brushSlider.style, {
    width: "100px", height: "4px", cursor: "pointer",
  });
  const brushVal = document.createElement("span");
  brushVal.textContent = "30";
  brushVal.style.cssText = "color:#5a8abf; font-size:12px; width:24px;";
  brushSlider.oninput = () => { brushVal.textContent = brushSlider.value; };

  // Eraser toggle
  let isEraser = false;
  const eraserBtn = document.createElement("button");
  eraserBtn.textContent = "橡皮擦";
  Object.assign(eraserBtn.style, {
    padding: "4px 10px", fontSize: "11px", border: "1px solid #3a3a4a",
    background: "#2a2a3a", color: "#888", borderRadius: "6px", cursor: "pointer",
  });
  eraserBtn.onclick = () => {
    isEraser = !isEraser;
    eraserBtn.style.background = isEraser ? "#5f3a1e" : "#2a2a3a";
    eraserBtn.style.borderColor = isEraser ? "#8f5a2a" : "#3a3a4a";
    eraserBtn.style.color = isEraser ? "#fff" : "#888";
  };

  function updateBrushVisibility() {
    const show = blurMode === "mask";
    brushLabel.style.display = show ? "" : "none";
    brushSlider.style.display = show ? "" : "none";
    brushVal.style.display = show ? "" : "none";
    eraserBtn.style.display = show ? "" : "none";
  }
  updateBrushVisibility();

  modeSection.append(modeGlobalBtn, modeMaskBtn, modeSelectionBtn, modeTiledBtn, brushLabel, brushSlider, brushVal, eraserBtn);
  panel.appendChild(modeSection);

  // === SELECTION BLUR: ratio-locked draggable boxes ===
  const SEL_RATIOS = [
    { label: "1:1", v: 1 }, { label: "4:3", v: 4 / 3 }, { label: "3:4", v: 3 / 4 },
    { label: "3:2", v: 3 / 2 }, { label: "2:3", v: 2 / 3 }, { label: "16:9", v: 16 / 9 },
    { label: "9:16", v: 9 / 16 }, { label: "21:9", v: 21 / 9 },
  ];
  let selBoxes = []; // [{id, ratio, ratioValue, sigma, x, y, w, h}]  (x/y/w/h in 0-1 normalized)
  let selActiveIdx = -1;
  let selBoxIdCounter = 0;
  let selOverlayCanvas = null;

  // Restore saved boxes
  if (node.properties?._selection_boxes) {
    try { selBoxes = JSON.parse(node.properties._selection_boxes); selBoxIdCounter = selBoxes.length; } catch (e) { }
  }

  // --- Selection params section ---
  const selParamsSection = document.createElement("div");
  Object.assign(selParamsSection.style, {
    display: blurMode === "selection" ? "flex" : "none",
    flexDirection: "column", gap: "8px", marginBottom: "12px",
    padding: "10px 14px", background: "#222233", borderRadius: "8px",
    border: "1px solid #2a2a3a",
  });

  // Ratio buttons row
  const selRatioRow = document.createElement("div");
  selRatioRow.style.cssText = "display:flex; gap:6px; flex-wrap:wrap; align-items:center;";
  const selRatioLabel = document.createElement("span");
  selRatioLabel.textContent = "添加选区:";
  selRatioLabel.style.cssText = "color:#aaa; font-size:12px; white-space:nowrap;";
  selRatioRow.appendChild(selRatioLabel);
  for (const r of SEL_RATIOS) {
    const btn = document.createElement("button");
    btn.textContent = r.label;
    Object.assign(btn.style, {
      padding: "4px 10px", fontSize: "11px", border: "1px solid #3a5a7a",
      background: "#1a2a3a", color: "#7ab", borderRadius: "6px", cursor: "pointer",
    });
    btn.onmouseenter = () => { btn.style.background = "#2a4a6a"; };
    btn.onmouseleave = () => { btn.style.background = "#1a2a3a"; };
    btn.onclick = () => {
      // Create a new box centered, accounting for image aspect ratio
      // Normalized coords: bw is fraction of imgW, bh is fraction of imgH
      // We want pixel ratio: (bw*imgW)/(bh*imgH) = r.v
      // So bw/bh = r.v * imgH/imgW = r.v / imgAR
      const img = panel.querySelector("#blur-preview-img");
      const imgAR = img?.naturalWidth && img?.naturalHeight ? img.naturalWidth / img.naturalHeight : 1.5;
      const normRatio = r.v / imgAR; // w/h in normalized 0-1 space
      const area = 0.12; // ~35% of image area (sqrt = ~0.35)
      const bh = Math.min(0.9, Math.sqrt(area / normRatio));
      const bw = Math.min(0.9, bh * normRatio);
      selBoxes.push({
        id: "box_" + (selBoxIdCounter++),
        ratio: r.label, ratioValue: r.v,
        sigma: parseFloat(slider.value) || 5,
        x: Math.max(0, 0.5 - bw / 2), y: Math.max(0, 0.5 - bh / 2), w: bw, h: bh,
      });
      selActiveIdx = selBoxes.length - 1;
      saveSelBoxes();
      rebuildSelBoxList();
      updateSelOverlay();
    };
    selRatioRow.appendChild(btn);
  }
  selParamsSection.appendChild(selRatioRow);

  // Box list
  const selBoxListContainer = document.createElement("div");
  selBoxListContainer.style.cssText = "display:flex; flex-direction:column; gap:4px; max-height:120px; overflow-y:auto;";
  selParamsSection.appendChild(selBoxListContainer);

  // Per-box sigma slider
  const selSigmaRow = document.createElement("div");
  selSigmaRow.style.cssText = "display:flex; align-items:center; gap:8px;";
  const selSigmaLabel = document.createElement("span");
  selSigmaLabel.textContent = "选区模糊:";
  selSigmaLabel.style.cssText = "color:#aaa; font-size:12px; white-space:nowrap;";
  const selSigmaSlider = document.createElement("input");
  selSigmaSlider.type = "range"; selSigmaSlider.min = "0.5"; selSigmaSlider.max = "100"; selSigmaSlider.step = "0.5"; selSigmaSlider.value = "5";
  selSigmaSlider.style.cssText = "flex:1; height:4px; cursor:pointer;";
  const selSigmaVal = document.createElement("span");
  selSigmaVal.textContent = "5";
  selSigmaVal.style.cssText = "color:#5a8abf; font-size:12px; width:30px;";
  selSigmaSlider.oninput = () => {
    selSigmaVal.textContent = selSigmaSlider.value;
    if (selActiveIdx >= 0 && selActiveIdx < selBoxes.length) {
      selBoxes[selActiveIdx].sigma = parseFloat(selSigmaSlider.value);
      saveSelBoxes();
      rebuildSelBoxList();
      updateSelOverlay();
    }
  };
  selSigmaRow.append(selSigmaLabel, selSigmaSlider, selSigmaVal);
  selParamsSection.appendChild(selSigmaRow);

  panel.appendChild(selParamsSection);

  function saveSelBoxes() {
    if (!node.properties) node.properties = {};
    node.properties._selection_boxes = JSON.stringify(selBoxes);
  }

  function rebuildSelBoxList() {
    selBoxListContainer.innerHTML = "";
    selBoxes.forEach((box, idx) => {
      const row = document.createElement("div");
      row.style.cssText = `display:flex; align-items:center; gap:6px; padding:4px 8px; border-radius:6px; cursor:pointer;
        background:${idx === selActiveIdx ? "#2a4a6a" : "#1a1a2a"}; border:1px solid ${idx === selActiveIdx ? "#4a8abf" : "#2a2a3a"};`;
      row.onclick = () => {
        selActiveIdx = idx;
        selSigmaSlider.value = box.sigma;
        selSigmaVal.textContent = box.sigma;
        rebuildSelBoxList();
        updateSelOverlay();
      };
      const label = document.createElement("span");
      label.textContent = `选区${idx + 1}  ${box.ratio}  σ=${box.sigma}`;
      label.style.cssText = "color:#ddd; font-size:12px; flex:1;";

      const delBtn = document.createElement("span");
      delBtn.textContent = "✕";
      delBtn.title = "删除此选区";
      Object.assign(delBtn.style, {
        cursor: "pointer", fontSize: "16px", color: "#ff5555", fontWeight: "bold",
        padding: "2px 6px", borderRadius: "4px", lineHeight: "1",
      });
      delBtn.onmouseenter = () => { delBtn.style.background = "rgba(255,50,50,0.2)"; };
      delBtn.onmouseleave = () => { delBtn.style.background = "transparent"; };
      delBtn.onclick = (e) => {
        e.stopPropagation();
        selBoxes.splice(idx, 1);
        if (selActiveIdx >= selBoxes.length) selActiveIdx = selBoxes.length - 1;
        saveSelBoxes();
        rebuildSelBoxList();
        updateSelOverlay();
      };
      row.append(label, delBtn);
      selBoxListContainer.appendChild(row);

      // Reference image input — separate row below the box, full width
      const refRow = document.createElement("div");
      refRow.style.cssText = `display:flex; align-items:center; gap:8px; padding:4px 12px; margin-top:2px; margin-bottom:4px;
        background:#151520; border-radius:4px; border:1px solid #222;`;
      refRow.onclick = (e) => e.stopPropagation();
      const refLabel = document.createElement("span");
      refLabel.textContent = `  📷 参考图编号:`;
      refLabel.style.cssText = "color:#8ab4f8; font-size:12px; white-space:nowrap;";
      const refInput = document.createElement("input");
      refInput.type = "text";
      refInput.value = box.refRange || "";
      refInput.placeholder = "如 2-4 或 2,3,4（输入槽编号）";
      refInput.title = "输入此人对应的参考图输入槽编号（从image2开始），如 2-4 或 2,3,4";
      refInput.style.cssText = `flex:1; background:#0a0a15; color:#ddd; border:1px solid #333; border-radius:4px;
        padding:4px 8px; font-size:12px;`;
      refInput.oninput = (e) => {
        e.stopPropagation();
        box.refRange = refInput.value.trim();
        saveSelBoxes();
      };
      refRow.append(refLabel, refInput);
      selBoxListContainer.appendChild(refRow);
    });
    // Show/hide sigma row
    selSigmaRow.style.display = selBoxes.length > 0 ? "flex" : "none";
  }
  rebuildSelBoxList();

  function updateSelParamsVisibility() {
    selParamsSection.style.display = blurMode === "selection" ? "flex" : "none";
  }

  // --- Selection overlay: use overlayRef + getImageRect (same as mask mode) ---
  function updateSelOverlay() {
    if (!overlayRef || blurMode !== "selection" || !previewImg) return;
    const w = overlayRef.width, h = overlayRef.height;
    const ctx = overlayRef.getContext("2d");
    ctx.clearRect(0, 0, w, h);

    if (!previewImg.naturalWidth) return;
    const ir = getImageRect();

    // Phase 1: Draw blur for each box using offscreen canvas 
    // Sort by sigma ascending so larger sigma overwrites overlaps (matches backend logic)
    const sortedBoxes = [...selBoxes].sort((a, b) => (parseFloat(a.sigma) || 5) - (parseFloat(b.sigma) || 5));
    sortedBoxes.forEach((box) => {
      const bx = ir.left + box.x * ir.width;
      const by = ir.top + box.y * ir.height;
      const bw = box.w * ir.width;
      const bh = box.h * ir.height;
      const blurPx = box.sigma * blurScaleRatio;

      // Full blurred image on offscreen, then copy box region
      const off = document.createElement("canvas");
      off.width = w; off.height = h;
      const oCtx = off.getContext("2d");

      const pad = Math.ceil(blurPx * 2);
      const padCanvas = document.createElement("canvas");
      padCanvas.width = ir.width + pad * 2;
      padCanvas.height = ir.height + pad * 2;
      const pCtx = padCanvas.getContext("2d");

      // Draw main image
      pCtx.drawImage(previewImg, pad, pad, ir.width, ir.height);
      // Top & Bottom pad
      pCtx.drawImage(previewImg, 0, 0, previewImg.naturalWidth, 1, pad, 0, ir.width, pad);
      pCtx.drawImage(previewImg, 0, previewImg.naturalHeight - 1, previewImg.naturalWidth, 1, pad, pad + ir.height, ir.width, pad);
      // Left & Right pad
      pCtx.drawImage(previewImg, 0, 0, 1, previewImg.naturalHeight, 0, pad, pad, ir.height);
      pCtx.drawImage(previewImg, previewImg.naturalWidth - 1, 0, 1, previewImg.naturalHeight, pad + ir.width, pad, pad, ir.height);
      // Corners
      pCtx.drawImage(previewImg, 0, 0, 1, 1, 0, 0, pad, pad);
      pCtx.drawImage(previewImg, previewImg.naturalWidth - 1, 0, 1, 1, pad + ir.width, 0, pad, pad);
      pCtx.drawImage(previewImg, 0, previewImg.naturalHeight - 1, 1, 1, 0, pad + ir.height, pad, pad);
      pCtx.drawImage(previewImg, previewImg.naturalWidth - 1, previewImg.naturalHeight - 1, 1, 1, pad + ir.width, pad + ir.height, pad, pad);

      oCtx.filter = `blur(${Math.max(0.5, blurPx)}px)`;
      // Draw padded image shifted so the main image lands at ir.left, ir.top
      oCtx.drawImage(padCanvas, ir.left - pad, ir.top - pad, padCanvas.width, padCanvas.height);

      ctx.drawImage(off,
        Math.round(bx), Math.round(by), Math.round(bw), Math.round(bh),
        Math.round(bx), Math.round(by), Math.round(bw), Math.round(bh));
    });

    // Phase 2: Draw borders + handles + labels ON TOP
    selBoxes.forEach((box, idx) => {
      const bx = ir.left + box.x * ir.width;
      const by = ir.top + box.y * ir.height;
      const bw = box.w * ir.width;
      const bh = box.h * ir.height;
      const isActive = idx === selActiveIdx;

      ctx.strokeStyle = isActive ? "#00ff55" : "rgba(255,255,255,0.85)";
      ctx.lineWidth = isActive ? 4 : 3;
      if (!isActive) { ctx.setLineDash([8, 4]); }
      ctx.strokeRect(bx + 1, by + 1, bw - 2, bh - 2);
      ctx.setLineDash([]);

      if (isActive) {
        const hs = 10;
        ctx.fillStyle = "#00ff55";
        [[bx, by], [bx + bw, by], [bx, by + bh], [bx + bw, by + bh]].forEach(([cx, cy]) => {
          ctx.fillRect(cx - hs / 2, cy - hs / 2, hs, hs);
        });
      }

      ctx.fillStyle = "#fff";
      ctx.font = "bold 13px sans-serif";
      ctx.textAlign = "left";
      ctx.shadowColor = "rgba(0,0,0,0.9)"; ctx.shadowBlur = 6;
      ctx.fillText(`${box.ratio} σ=${box.sigma}`, bx + 8, by + 18);
      ctx.shadowBlur = 0;
    });
  }

  // Drag state
  let selDragState = null; // {type: 'move'|'resize', idx, startMx, startMy, origBox}

  function initSelOverlayEvents(canvas) {
    const getPos = (e) => {
      if (!overlayRef) return { mx: 0, my: 0 };
      const rect = overlayRef.getBoundingClientRect();
      const sx = overlayRef.width / rect.width;
      const sy = overlayRef.height / rect.height;
      const px = (e.clientX - rect.left) * sx;
      const py = (e.clientY - rect.top) * sy;
      const ir = getImageRect();
      return { mx: (px - ir.left) / ir.width, my: (py - ir.top) / ir.height };
    };

    canvas.addEventListener("mousedown", (e) => {
      if (blurMode !== "selection") return;
      const { mx, my } = getPos(e);
      const CORNER_R = 0.025; // corner hit radius (normalized)

      // Check corners of active box first (resize)
      if (selActiveIdx >= 0 && selActiveIdx < selBoxes.length) {
        const box = selBoxes[selActiveIdx];
        const corners = [[box.x, box.y], [box.x + box.w, box.y], [box.x, box.y + box.h], [box.x + box.w, box.y + box.h]];
        for (let ci = 0; ci < corners.length; ci++) {
          if (Math.abs(mx - corners[ci][0]) < CORNER_R && Math.abs(my - corners[ci][1]) < CORNER_R) {
            selDragState = {
              type: "resize", idx: selActiveIdx, corner: ci, startMx: mx, startMy: my,
              origBox: { ...box }
            };
            e.preventDefault();
            return;
          }
        }
      }

      // Check all boxes for click (reverse order = front first)
      for (let i = selBoxes.length - 1; i >= 0; i--) {
        const box = selBoxes[i];
        if (mx >= box.x && mx <= box.x + box.w && my >= box.y && my <= box.y + box.h) {
          selActiveIdx = i;
          selSigmaSlider.value = box.sigma;
          selSigmaVal.textContent = box.sigma;
          rebuildSelBoxList();
          selDragState = {
            type: "move", idx: i, startMx: mx, startMy: my,
            origBox: { ...box }
          };
          updateSelOverlay();
          e.preventDefault();
          return;
        }
      }
      // Clicked empty space
      selActiveIdx = -1;
      rebuildSelBoxList();
      updateSelOverlay();
    });

    canvas.addEventListener("mousemove", (e) => {
      if (!selDragState) return;
      const { mx, my } = getPos(e);
      const s = selDragState;
      const box = selBoxes[s.idx];
      if (!box) return;

      if (s.type === "move") {
        const dx = mx - s.startMx, dy = my - s.startMy;
        box.x = Math.max(0, Math.min(1 - box.w, s.origBox.x + dx));
        box.y = Math.max(0, Math.min(1 - box.h, s.origBox.y + dy));
      } else if (s.type === "resize") {
        // Ratio-locked resize from corner
        const dx = mx - s.startMx, dy = my - s.startMy;
        const ob = s.origBox;
        let nw = ob.w, nh = ob.h, nx = ob.x, ny = ob.y;
        // Which corner?
        const isRight = s.corner === 1 || s.corner === 3;
        const isBottom = s.corner === 2 || s.corner === 3;
        // Use the dominant axis for ratio-locked scaling
        const scale = isRight ? (ob.w + dx) / ob.w : (ob.w - dx) / ob.w;
        const scaleY = isBottom ? (ob.h + dy) / ob.h : (ob.h - dy) / ob.h;
        const finalScale = Math.max(0.05, (Math.abs(dx) > Math.abs(dy)) ? scale : scaleY);
        nw = ob.w * finalScale;
        nh = ob.h * finalScale;
        if (!isRight) nx = ob.x + ob.w - nw;
        if (!isBottom) ny = ob.y + ob.h - nh;
        // Clamp
        nw = Math.max(0.03, Math.min(1, nw));
        nh = Math.max(0.03, Math.min(1, nh));
        nx = Math.max(0, Math.min(1 - nw, nx));
        ny = Math.max(0, Math.min(1 - nh, ny));
        box.x = nx; box.y = ny; box.w = nw; box.h = nh;
      }
      updateSelOverlay();
    });

    const endDrag = () => {
      if (selDragState) {
        selDragState = null;
        saveSelBoxes();
      }
    };
    canvas.addEventListener("mouseup", endDrag);
    canvas.addEventListener("mouseleave", endDrag);
  }

  // --- Tiled Mode Parameters (below mode toggle, hidden unless tiled mode) ---
  const tiledParamsSection = document.createElement("div");
  Object.assign(tiledParamsSection.style, {
    display: blurMode === "tiled" ? "flex" : "none",
    gap: "16px", alignItems: "center", marginBottom: "12px",
    padding: "10px 14px", background: "#222233", borderRadius: "8px",
    border: "1px solid #2a2a3a",
  });

  // Helper
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

  // Tile mode dropdown
  const tileModeLabel = document.createElement("span");
  tileModeLabel.textContent = "切块模式";
  tileModeLabel.style.cssText = "color:#aaa; font-size:12px; white-space:nowrap;";
  const tileModeSelect = document.createElement("select");
  Object.assign(tileModeSelect.style, {
    background: "#1a1a2a", color: "#ddd", border: "1px solid #3a3a4a",
    borderRadius: "6px", padding: "4px 8px", fontSize: "12px", cursor: "pointer",
  });

  // === Ratio-correction tile system ===
  // For each grid, calculate X/Y overlap to correct tiles to exact API ratios
  const API_RATIOS = [
    { label: "1:1", v: 1.0 },
    { label: "5:4", v: 5 / 4 },
    { label: "4:5", v: 4 / 5 },
    { label: "4:3", v: 4 / 3 },
    { label: "3:4", v: 3 / 4 },
    { label: "3:2", v: 3 / 2 },
    { label: "2:3", v: 2 / 3 },
    { label: "16:9", v: 16 / 9 },
    { label: "9:16", v: 9 / 16 },
    { label: "21:9", v: 21 / 9 },
    { label: "9:21", v: 9 / 21 },
  ];
  const MIN_SEAM_OV = 16;
  const MAX_CORRECTION_OV = 200;

  function findBestRatio(tileW, tileH) {
    const r = tileW / tileH;
    let best = API_RATIOS[0], bestD = Infinity;
    for (const ar of API_RATIOS) {
      const d = Math.abs(r - ar.v);
      if (d < bestD) { bestD = d; best = ar; }
    }
    return best;
  }

  function calcCorrectedGrid(imgW, imgH, cols, rows) {
    const baseTileW = imgW / cols;
    const baseTileH = imgH / rows;
    const target = findBestRatio(baseTileW, baseTileH);
    const R = target.v;
    let ovX = MIN_SEAM_OV, ovY = MIN_SEAM_OV;
    const currentR = baseTileW / baseTileH;

    if (Math.abs(currentR - R) < 0.01) {
      // Already close enough
    } else if (currentR > R) {
      // Tile too wide -> increase height
      ovY = Math.round((baseTileW + MIN_SEAM_OV) / R - baseTileH);
      ovY = Math.max(MIN_SEAM_OV, Math.min(MAX_CORRECTION_OV, ovY));
    } else {
      // Tile too tall -> increase width
      ovX = Math.round(R * (baseTileH + MIN_SEAM_OV) - baseTileW);
      ovX = Math.max(MIN_SEAM_OV, Math.min(MAX_CORRECTION_OV, ovX));
    }

    const finalW = Math.floor(baseTileW) + (cols > 1 ? ovX : 0);
    const finalH = Math.floor(baseTileH) + (rows > 1 ? ovY : 0);
    const finalRatio = findBestRatio(finalW, finalH);

    return {
      cols, rows, total: cols * rows,
      baseTileW: Math.floor(baseTileW), baseTileH: Math.floor(baseTileH),
      ovX, ovY, finalW, finalH,
      ratio: finalRatio.label,
      deviation: Math.abs(finalW / finalH - finalRatio.v)
    };
  }

  function buildAllGridOptions(imgW, imgH) {
    const results = [];
    const seen = new Set();
    for (let c = 1; c <= 5; c++) {
      for (let r = 1; r <= 5; r++) {
        if (c === 1 && r === 1) continue;
        if (c * r > 12) continue;
        const key = `${c}x${r}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const g = calcCorrectedGrid(imgW, imgH, c, r);
        // Filter: reject if correction overlap is too aggressive (>30% of base tile)
        if (g.ovX > g.baseTileW * 0.3 || g.ovY > g.baseTileH * 0.3) continue;
        // Filter: reject if corrected ratio still deviates > 15% from target
        const finalR = g.finalW / g.finalH;
        const targetR = API_RATIOS.find(a => a.label === g.ratio)?.v || 1;
        if (Math.abs(finalR - targetR) / targetR > 0.15) continue;
        results.push(g);
      }
    }
    results.sort((a, b) => a.total - b.total || a.deviation - b.deviation);
    return results;
  }

  let _allGrids = [];
  let _selectedGrid = null;

  function rebuildTileModeOptions() {
    const img = panel.querySelector("#blur-preview-img");
    const imgW = img?.naturalWidth || 1920;
    const imgH = img?.naturalHeight || 960;
    const prevValue = tileModeSelect.value;
    tileModeSelect.innerHTML = "";

    _allGrids = buildAllGridOptions(imgW, imgH);
    if (_allGrids.length === 0) {
      _allGrids = [calcCorrectedGrid(imgW, imgH, 2, 2)];
    }

    for (const g of _allGrids) {
      const o = document.createElement("option");
      o.value = `${g.cols}x${g.rows}`;
      o.textContent = `${g.cols}×${g.rows} → ${g.ratio} (${g.total}块, ${g.finalW}×${g.finalH})`;
      tileModeSelect.appendChild(o);
    }

    // Restore: prioritize saved property (persists across panel open/close)
    const saved = node.properties?._tile_mode;
    if (saved && [...tileModeSelect.options].some(o => o.value === saved)) {
      tileModeSelect.value = saved;
    } else if (prevValue && [...tileModeSelect.options].some(o => o.value === prevValue)) {
      tileModeSelect.value = prevValue;
    }
    _selectedGrid = _allGrids.find(g => `${g.cols}x${g.rows}` === tileModeSelect.value) || _allGrids[0];
  }
  rebuildTileModeOptions();

  const _origGetGrid = getGridFromMode;
  getGridFromMode = function (mode) {
    const m = mode.match(/^(\d+)x(\d+)$/);
    if (m) return [parseInt(m[1]), parseInt(m[2])];
    return _origGetGrid(mode);
  };

  function recalcAutoOverlap() {
    _selectedGrid = _allGrids.find(g => `${g.cols}x${g.rows}` === tileModeSelect.value) || _allGrids[0];
    if (_selectedGrid) {
      tileInfoText.textContent = `重合 X:${_selectedGrid.ovX}px Y:${_selectedGrid.ovY}px`;
    }
  }

  const tileInfoText = document.createElement("span");
  tileInfoText.style.cssText = "color:#5a8abf; font-size:11px; white-space:nowrap;";

  // Selection counter
  const tiledSelCount = document.createElement("span");
  tiledSelCount.style.cssText = "color:#4CAF50; font-size:12px; margin-left:auto; white-space:nowrap;";
  const selectedTiles = new Set();
  if (node.properties?._selected_tiles_list) {
    try {
      const saved = JSON.parse(node.properties._selected_tiles_list);
      if (Array.isArray(saved)) saved.forEach(k => selectedTiles.add(k));
    } catch (e) { }
  }
  function updateTiledSelCount() {
    const [cols, rows] = getGridFromMode(tileModeSelect.value);
    const total = cols * rows;
    tiledSelCount.textContent = selectedTiles.size > 0 ? `✅ 已选 ${selectedTiles.size}/${total} 块` : `共 ${total} 块 (点击图片选择)`;
  }
  updateTiledSelCount();
  recalcAutoOverlap();

  tileModeSelect.onchange = () => {
    selectedTiles.clear();
    // Save immediately so it persists across panel open/close
    if (!node.properties) node.properties = {};
    node.properties._tile_mode = tileModeSelect.value;
    updateTiledSelCount();
    recalcAutoOverlap();
    updateTiledOverlay();
  };

  tiledParamsSection.append(tileModeLabel, tileModeSelect, tileInfoText, tiledSelCount);
  panel.appendChild(tiledParamsSection);

  // Tiled overlay canvas (sits on top of preview image, for grid lines + selection)
  function updateTiledOverlay() {
    if (!overlayRef || blurMode !== "tiled" || !previewImg) return;
    const ctx = overlayRef.getContext("2d");
    ctx.clearRect(0, 0, overlayRef.width, overlayRef.height);

    if (!previewImg.naturalWidth) return;
    const ir = getImageRect();
    const w = ir.width, h = ir.height;

    const [cols, rows] = getGridFromMode(tileModeSelect.value);
    const stepX = w / cols, stepY = h / rows;
    // Get per-axis overlaps from selected grid
    const sg = _selectedGrid || { ovX: 16, ovY: 16 };
    // Scale overlap to preview canvas size (overlap is in original image pixels)
    const scaleX = w / previewImg.naturalWidth;
    const scaleY = h / previewImg.naturalHeight;
    const ovXpx = sg.ovX * scaleX;
    const ovYpx = sg.ovY * scaleY;

    ctx.save();
    ctx.translate(ir.left, ir.top);

    // 1. Selected tiles — green highlight shows actual upload area (with overlap)
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (selectedTiles.has(c + "_" + r)) {
          // Calculate actual tile bounds (matching backend split_image_tiles logic)
          let x0 = c * stepX, y0 = r * stepY;
          let x1 = (c === cols - 1) ? w : (c + 1) * stepX + ovXpx;
          let y1 = (r === rows - 1) ? h : (r + 1) * stepY + ovYpx;
          if (c > 0) x0 -= ovXpx;
          if (r > 0) y0 -= ovYpx;
          x0 = Math.max(0, x0); y0 = Math.max(0, y0);
          x1 = Math.min(w, x1); y1 = Math.min(h, y1);
          const tw = x1 - x0, th = y1 - y0;

          // Fill the actual tile area
          ctx.fillStyle = "rgba(0, 200, 100, 0.2)";
          ctx.fillRect(x0, y0, tw, th);
          // Solid border around actual upload area
          ctx.strokeStyle = "rgba(0, 220, 120, 0.9)";
          ctx.lineWidth = 2.5;
          ctx.strokeRect(x0 + 1, y0 + 1, tw - 2, th - 2);
          // Checkmark at cell center
          ctx.fillStyle = "rgba(255,255,255,0.95)";
          ctx.font = "bold 28px sans-serif";
          ctx.textAlign = "center";
          ctx.shadowColor = "black"; ctx.shadowBlur = 6;
          ctx.fillText("✓", c * stepX + stepX / 2, r * stepY + stepY / 2 + 10);
          ctx.shadowBlur = 0;
        }
      }
    }

    // 2. Grid lines (red)
    ctx.strokeStyle = "rgba(255, 50, 50, 0.9)";
    ctx.lineWidth = 2.0;
    ctx.beginPath();
    for (let c = 1; c < cols; c++) { ctx.moveTo(c * stepX, 0); ctx.lineTo(c * stepX, h); }
    for (let r = 1; r < rows; r++) { ctx.moveTo(0, r * stepY); ctx.lineTo(w, r * stepY); }
    ctx.stroke();

    // 3. Overlap zones (yellow, X/Y independent)
    ctx.fillStyle = "rgba(255, 200, 0, 0.15)";
    ctx.strokeStyle = "rgba(255, 200, 0, 0.6)";
    ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
    ctx.beginPath();
    if (ovXpx > 0) {
      for (let c = 1; c < cols; c++) {
        ctx.fillRect(c * stepX - ovXpx, 0, ovXpx * 2, h);
        ctx.moveTo(c * stepX - ovXpx, 0); ctx.lineTo(c * stepX - ovXpx, h);
        ctx.moveTo(c * stepX + ovXpx, 0); ctx.lineTo(c * stepX + ovXpx, h);
      }
    }
    if (ovYpx > 0) {
      for (let r = 1; r < rows; r++) {
        ctx.fillRect(0, r * stepY - ovYpx, w, ovYpx * 2);
        ctx.moveTo(0, r * stepY - ovYpx); ctx.lineTo(w, r * stepY - ovYpx);
        ctx.moveTo(0, r * stepY + ovYpx); ctx.lineTo(w, r * stepY + ovYpx);
      }
    }
    ctx.stroke(); ctx.setLineDash([]);
    ctx.restore();
  }

  function updateTiledParamsVisibility() {
    tiledParamsSection.style.display = blurMode === "tiled" ? "flex" : "none";
  }

  // --- Preview Area ---
  const previewBox = document.createElement("div");
  Object.assign(previewBox.style, {
    position: "relative", flex: "1", minHeight: "0", background: "#111",
    borderRadius: "10px", overflow: "hidden", display: "flex",
    alignItems: "center", justifyContent: "center", marginBottom: "16px",
    border: "1px solid #2a2a3a",
  });
  previewBox.innerHTML = `<span style="color:#555;font-size:14px">连接图片输入后可预览模糊效果</span>`;
  previewBox.id = "blur-preview-area";
  panel.appendChild(previewBox);

  // Mask canvas reference (created when image loads)
  let maskCanvas = null;
  let maskCtx = null;
  let isPainting = false;
  let previewImg = null;
  let overlayRef = null;

  // Helper: get image position in CANVAS pixel space (not CSS space)
  function getImageRect() {
    if (!previewImg || !overlayRef) return { left: 0, top: 0, width: 1, height: 1 };
    const ir = previewImg.getBoundingClientRect();
    const or = overlayRef.getBoundingClientRect();
    // Scale from CSS pixels to canvas pixel coordinates
    const sx = overlayRef.width / or.width;
    const sy = overlayRef.height / or.height;
    return {
      left: (ir.left - or.left) * sx,
      top: (ir.top - or.top) * sy,
      width: ir.width * sx,
      height: ir.height * sy,
    };
  }

  function updateMaskPreview() {
    if (!previewImg || !maskCanvas || blurMode !== "mask" || !overlayRef) return;
    const octx = overlayRef.getContext("2d");
    const w = overlayRef.width;
    const h = overlayRef.height;
    octx.clearRect(0, 0, w, h);

    const ir = getImageRect();
    const sigma = parseFloat(slider?.value || 0);
    const blurPx = sigma * blurScaleRatio;

    // Step 1: Draw blurred image clipped to mask area (within the image region)
    if (blurPx > 0) {
      octx.save();
      octx.filter = `blur(${blurPx}px)`;
      octx.drawImage(previewImg, ir.left, ir.top, ir.width, ir.height);
      octx.filter = "none";
      // Create clip mask at the image's position within overlay
      const clipCanvas = document.createElement("canvas");
      clipCanvas.width = w; clipCanvas.height = h;
      const cctx = clipCanvas.getContext("2d");
      cctx.drawImage(maskCanvas, ir.left, ir.top, ir.width, ir.height);
      octx.globalCompositeOperation = "destination-in";
      octx.drawImage(clipCanvas, 0, 0);
      octx.restore();
    }

    // Step 2: Thick red contour with outward gradient (multi-pass shadow glow)
    const tc = document.createElement("canvas");
    tc.width = w; tc.height = h;
    const tctx = tc.getContext("2d");
    // Draw mask at image position with red shadow passes
    tctx.shadowColor = "rgba(255, 50, 50, 0.4)";
    tctx.shadowBlur = 16;
    tctx.drawImage(maskCanvas, ir.left, ir.top, ir.width, ir.height);
    tctx.shadowColor = "rgba(255, 50, 50, 0.6)";
    tctx.shadowBlur = 8;
    tctx.drawImage(maskCanvas, ir.left, ir.top, ir.width, ir.height);
    tctx.shadowColor = "rgba(255, 80, 80, 0.9)";
    tctx.shadowBlur = 3;
    tctx.drawImage(maskCanvas, ir.left, ir.top, ir.width, ir.height);
    // Cut out interior
    tctx.globalCompositeOperation = "destination-out";
    tctx.shadowBlur = 0;
    tctx.shadowColor = "transparent";
    tctx.drawImage(maskCanvas, ir.left, ir.top, ir.width, ir.height);
    octx.drawImage(tc, 0, 0);
  }

  function drawBrushCursor(e) {
    if (!overlayRef || blurMode !== "mask") return;
    const rect = overlayRef.getBoundingClientRect();
    // Convert mouse CSS coords to canvas pixel coords
    const sx = overlayRef.width / rect.width;
    const sy = overlayRef.height / rect.height;
    const cx = (e.clientX - rect.left) * sx;
    const cy = (e.clientY - rect.top) * sy;
    const displayRadius = parseInt(brushSlider.value) * sx;
    updateMaskPreview();
    const octx = overlayRef.getContext("2d");
    octx.save();
    octx.strokeStyle = isEraser ? "#ffaa44" : "#44aaff";
    octx.lineWidth = 2;
    octx.setLineDash([4, 4]);
    octx.beginPath();
    octx.arc(cx, cy, displayRadius, 0, Math.PI * 2);
    octx.stroke();
    octx.fillStyle = isEraser ? "#ffaa44" : "#44aaff";
    octx.beginPath();
    octx.arc(cx, cy, 2, 0, Math.PI * 2);
    octx.fill();
    octx.restore();
  }

  function saveMaskToProperties() {
    if (!node.properties) node.properties = {};
    if (maskCanvas && blurMode === "mask") {
      // Check alpha channel for painted content (transparent bg + white paint)
      const mdata = maskCanvas.getContext("2d").getImageData(0, 0, maskCanvas.width, maskCanvas.height).data;
      let hasContent = false;
      for (let i = 3; i < mdata.length; i += 4) {
        if (mdata[i] > 0) { hasContent = true; break; }
      }
      if (hasContent) {
        // Export as black/white for backend (PIL L-mode)
        const exportCanvas = document.createElement("canvas");
        exportCanvas.width = maskCanvas.width;
        exportCanvas.height = maskCanvas.height;
        const ectx = exportCanvas.getContext("2d");
        ectx.fillStyle = "black";
        ectx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);
        ectx.drawImage(maskCanvas, 0, 0);
        node.properties._blur_mask = exportCanvas.toDataURL("image/png");
      } else {
        node.properties._blur_mask = "";
      }
    } else {
      node.properties._blur_mask = "";
    }
  }

  // Load source image, set up overlay canvas
  (async () => {
    const imgSrc = getLinkedInputImageUrl(node);
    if (!imgSrc) return;

    const img = document.createElement("img");
    img.id = "blur-preview-img";
    img.src = imgSrc;
    img.style.cssText = "max-width:100%; max-height:100%; object-fit:contain; border-radius:6px; transition:filter 0.05s;";

    img.onload = () => {
      previewImg = img;
      const naturalW = img.naturalWidth;
      const naturalH = img.naturalHeight;

      // Double-rAF to ensure layout is fully settled
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const imgRect = img.getBoundingClientRect();
        const boxRect = previewBox.getBoundingClientRect();
        if (imgRect.width > 0 && naturalW > 0) {
          blurScaleRatio = imgRect.width / naturalW;
        }
        if (blurMode === "global" || blurMode === "tiled") {
          img.style.filter = `blur(${currentSigma * blurScaleRatio}px)`;
        }
        // Recalculate auto-overlap now that image natural size is known
        rebuildTileModeOptions();
        recalcAutoOverlap();

        // Mask canvas: TRANSPARENT bg + white paint for mask areas
        maskCanvas = document.createElement("canvas");
        maskCanvas.width = naturalW;
        maskCanvas.height = naturalH;
        maskCtx = maskCanvas.getContext("2d");

        // Restore saved mask (stored as black/white, convert to transparent/white)
        if (node.properties?._blur_mask) {
          const savedMask = new window.Image();
          savedMask.onload = () => {
            maskCtx.drawImage(savedMask, 0, 0, naturalW, naturalH);
            const imgData = maskCtx.getImageData(0, 0, naturalW, naturalH);
            for (let p = 0; p < imgData.data.length; p += 4) {
              if (imgData.data[p] < 128) {
                imgData.data[p] = 0; imgData.data[p + 1] = 0;
                imgData.data[p + 2] = 0; imgData.data[p + 3] = 0;
              }
            }
            maskCtx.putImageData(imgData, 0, 0);
            updateMaskPreview();
          };
          savedMask.src = node.properties._blur_mask;
        }

        // Overlay covers ENTIRE previewBox — all coords are computed dynamically
        const overlay = document.createElement("canvas");
        overlay.id = "blur-mask-overlay";
        Object.assign(overlay.style, {
          position: "absolute",
          left: "0", top: "0",
          width: "100%", height: "100%",
          cursor: blurMode === "mask" ? "none" : "default",
          pointerEvents: blurMode === "mask" ? "auto" : "none",
          borderRadius: "10px",
        });
        previewBox.appendChild(overlay);
        // Set canvas resolution AFTER DOM insertion to match CSS display size exactly
        // This ensures 1:1 mapping: CSS coordinates = canvas pixel coordinates
        overlay.width = overlay.clientWidth;
        overlay.height = overlay.clientHeight;
        overlayRef = overlay;

        // Tiled mode uses overlayRef as well

        // Selection mode uses overlayRef (same canvas as mask mode)
        initSelOverlayEvents(overlay);
        if (blurMode === "selection") {
          overlay.style.pointerEvents = "auto";
          overlay.style.cursor = "default";
          updateSelOverlay();
        }

        // Click to select/deselect tiles
        overlay.addEventListener("click", (e) => {
          if (blurMode !== "tiled") return;
          const rect = overlay.getBoundingClientRect();
          const sx = overlay.width / rect.width;
          const sy = overlay.height / rect.height;
          const px = (e.clientX - rect.left) * sx;
          const py = (e.clientY - rect.top) * sy;
          const ir = getImageRect();

          const clickX = px - ir.left;
          const clickY = py - ir.top;
          if (clickX < 0 || clickX > ir.width || clickY < 0 || clickY > ir.height) return;

          const [cols, rows] = getGridFromMode(tileModeSelect.value);
          const stepX = ir.width / cols, stepY = ir.height / rows;
          const col = Math.floor(clickX / stepX);
          const row = Math.floor(clickY / stepY);

          if (col < 0 || col >= cols || row < 0 || row >= rows) return;
          const key = col + "_" + row;
          if (selectedTiles.has(key)) selectedTiles.delete(key); else selectedTiles.add(key);
          updateTiledSelCount();
          updateTiledOverlay();
        });

        // Initial render if in tiled mode
        if (blurMode === "tiled") {
          updateTiledOverlay();
        }

        // Convert mouse event → mask canvas coordinates (scale-aware)
        function getCanvasPos(e) {
          const ir = getImageRect(); // already in canvas pixel space
          const or = overlay.getBoundingClientRect();
          // Convert mouse CSS coords to canvas pixel coords
          const sx = overlay.width / or.width;
          const sy = overlay.height / or.height;
          const canvasX = (e.clientX - or.left) * sx;
          const canvasY = (e.clientY - or.top) * sy;
          // Position relative to image in canvas space
          const relX = canvasX - ir.left;
          const relY = canvasY - ir.top;
          // Scale to mask canvas (natural image resolution)
          const scaleX = maskCanvas.width / ir.width;
          const scaleY = maskCanvas.height / ir.height;
          return { x: relX * scaleX, y: relY * scaleY };
        }

        function paint(e) {
          if (!isPainting || blurMode !== "mask") return;
          const pos = getCanvasPos(e);
          const ir = getImageRect();
          const displayRadius = parseInt(brushSlider.value);
          const scaledRadius = displayRadius * (maskCanvas.width / ir.width);
          if (isEraser) {
            maskCtx.save();
            maskCtx.globalCompositeOperation = "destination-out";
            maskCtx.beginPath();
            maskCtx.arc(pos.x, pos.y, scaledRadius, 0, Math.PI * 2);
            maskCtx.fillStyle = "white";
            maskCtx.fill();
            maskCtx.restore();
          } else {
            maskCtx.beginPath();
            maskCtx.arc(pos.x, pos.y, scaledRadius, 0, Math.PI * 2);
            maskCtx.fillStyle = "white";
            maskCtx.fill();
          }
          drawBrushCursor(e);
        }

        overlay.onmousedown = (e) => {
          e.preventDefault();
          isPainting = true;
          paint(e);
        };
        overlay.onmousemove = (e) => {
          if (isPainting) {
            paint(e);
          } else {
            drawBrushCursor(e);
          }
        };
        overlay.onmouseup = () => { isPainting = false; };
        overlay.onmouseleave = () => {
          isPainting = false;
          updateMaskPreview(); // Clear cursor circle
        };

        updateMaskPreview();
      }));
    };

    previewBox.innerHTML = "";
    previewBox.appendChild(img);
  })();

  // --- Mask Action Buttons (visible in mask mode) ---
  const maskActionsRow = document.createElement("div");
  maskActionsRow.style.cssText = "display:flex; gap:8px; margin-bottom:12px;";

  const clearMaskBtn = document.createElement("button");
  clearMaskBtn.textContent = "🗑️ 清除遮罩";
  Object.assign(clearMaskBtn.style, {
    padding: "6px 14px", background: "#2a2a3a", border: "1px solid #3a3a4a",
    borderRadius: "6px", color: "#888", fontSize: "12px", cursor: "pointer",
  });
  clearMaskBtn.onclick = () => {
    if (maskCtx && maskCanvas) {
      maskCtx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);
      updateMaskPreview();
    }
  };

  const invertMaskBtn = document.createElement("button");
  invertMaskBtn.textContent = "🔄 反转遮罩";
  Object.assign(invertMaskBtn.style, {
    padding: "6px 14px", background: "#2a2a3a", border: "1px solid #3a3a4a",
    borderRadius: "6px", color: "#888", fontSize: "12px", cursor: "pointer",
  });
  invertMaskBtn.onclick = () => {
    if (maskCtx && maskCanvas) {
      const imgData = maskCtx.getImageData(0, 0, maskCanvas.width, maskCanvas.height);
      for (let i = 0; i < imgData.data.length; i += 4) {
        // Invert alpha: painted (a=255) → transparent, transparent (a=0) → white
        if (imgData.data[i + 3] > 0) {
          imgData.data[i] = 0; imgData.data[i + 1] = 0;
          imgData.data[i + 2] = 0; imgData.data[i + 3] = 0;
        } else {
          imgData.data[i] = 255; imgData.data[i + 1] = 255;
          imgData.data[i + 2] = 255; imgData.data[i + 3] = 255;
        }
      }
      maskCtx.putImageData(imgData, 0, 0);
      updateMaskPreview();
    }
  };

  maskActionsRow.append(clearMaskBtn, invertMaskBtn);
  function updateMaskActionsVisibility() {
    maskActionsRow.style.display = blurMode === "mask" ? "flex" : "none";
  }
  updateMaskActionsVisibility();
  // Insert mask actions BEFORE preview area (above the image)
  panel.insertBefore(maskActionsRow, previewBox);

  // Mode switch logic
  function switchBlurMode(newMode) {
    blurMode = newMode;
    styleModeBtn(modeGlobalBtn, blurMode === "global");
    styleModeBtn(modeMaskBtn, blurMode === "mask");
    styleModeBtn(modeSelectionBtn, blurMode === "selection");
    styleModeBtn(modeTiledBtn, blurMode === "tiled");
    updateBrushVisibility();
    updateMaskActionsVisibility();
    updateTiledParamsVisibility();
    updateSelParamsVisibility();

    // Overlay & preview updates per mode
    if (blurMode === "global") {
      if (overlayRef) { overlayRef.style.pointerEvents = "none"; overlayRef.style.cursor = "default"; const octx = overlayRef.getContext("2d"); octx.clearRect(0, 0, overlayRef.width, overlayRef.height); }
      if (previewImg) { const s = parseFloat(slider.value); previewImg.style.filter = `blur(${s * blurScaleRatio}px)`; }
    } else if (blurMode === "mask") {
      if (overlayRef) { overlayRef.style.pointerEvents = "auto"; overlayRef.style.cursor = "none"; }
      if (previewImg) previewImg.style.filter = "none";
      updateMaskPreview();
    } else if (blurMode === "selection") {
      if (overlayRef) { overlayRef.style.pointerEvents = "none"; overlayRef.style.cursor = "default"; const octx = overlayRef.getContext("2d"); octx.clearRect(0, 0, overlayRef.width, overlayRef.height); }
      if (previewImg) previewImg.style.filter = "none";
      if (overlayRef) { overlayRef.style.pointerEvents = "auto"; overlayRef.style.cursor = "default"; updateSelOverlay(); }
    } else if (blurMode === "tiled") {
      if (overlayRef) { overlayRef.style.pointerEvents = "auto"; overlayRef.style.cursor = "crosshair"; const octx = overlayRef.getContext("2d"); octx.clearRect(0, 0, overlayRef.width, overlayRef.height); }
      if (previewImg) { const s = parseFloat(slider.value); previewImg.style.filter = `blur(${s * blurScaleRatio}px)`; }
      updateTiledOverlay();
    }
  }
  modeGlobalBtn.onclick = () => switchBlurMode("global");
  modeMaskBtn.onclick = () => switchBlurMode("mask");
  modeSelectionBtn.onclick = () => switchBlurMode("selection");
  modeTiledBtn.onclick = () => switchBlurMode("tiled");

  // --- Style Prompt Input ---
  const promptLabel = document.createElement("div");
  promptLabel.textContent = "提示词 (Prompt)";
  Object.assign(promptLabel.style, {
    fontSize: "11px", color: "#888", marginTop: "12px", marginBottom: "4px",
  });
  panel.appendChild(promptLabel);

  const promptTextarea = document.createElement("textarea");
  const spWidget = node.widgets?.find(w => w.name === "style_prompt");
  promptTextarea.value = spWidget?.value || "";
  promptTextarea.placeholder = "输入自定义提示词，或通过下方风格预设按钮填入...";
  Object.assign(promptTextarea.style, {
    width: "100%", minHeight: "60px", maxHeight: "120px", resize: "vertical",
    background: "#1a1a2e", border: "1px solid #2a2a3a", borderRadius: "8px",
    color: "#ddd", fontSize: "12px", padding: "8px", boxSizing: "border-box",
    fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif",
    lineHeight: "1.4", transition: "border-color 0.2s",
  });
  promptTextarea.onfocus = () => promptTextarea.style.borderColor = "#5a8abf";
  promptTextarea.onblur = () => promptTextarea.style.borderColor = "#2a2a3a";
  promptTextarea.oninput = () => {
    if (spWidget) spWidget.value = promptTextarea.value;
  };
  panel.appendChild(promptTextarea);
  // Expose for style preset buttons to update
  node._blurUI._promptTextarea = promptTextarea;

  // --- Apply Button ---
  const applyBtn = document.createElement("button");
  applyBtn.textContent = "✓ 应用设置";
  Object.assign(applyBtn.style, {
    width: "100%", padding: "14px", fontSize: "15px", fontWeight: "500",
    background: "linear-gradient(135deg, #2a5a8f, #1a3a5f)", border: "1px solid #3a7abf",
    borderRadius: "10px", color: "#fff", cursor: "pointer", transition: "all 0.2s",
  });
  applyBtn.onmouseenter = () => applyBtn.style.boxShadow = "0 0 20px rgba(42,90,143,0.5)";
  applyBtn.onmouseleave = () => applyBtn.style.boxShadow = "none";
  applyBtn.onclick = async () => {
    saveMaskToProperties();
    if (!node.properties) node.properties = {};
    node.properties._blur_mode = blurMode;
    node._blurUI._isCustomActive = true;

    // Save selection mode settings
    let currentSelectionBoxes = [];
    if (blurMode === "selection") {
      saveSelBoxes();

      // Compute pixel coords for backend independently of extra_params widget
      const img = panel.querySelector("#blur-preview-img");
      const iw = img?.naturalWidth || 1920, ih = img?.naturalHeight || 960;
      currentSelectionBoxes = selBoxes.map(b => ({
        sigma: parseFloat(b.sigma) || 5, ratio: b.ratio,
        x: Math.round(b.x * iw), y: Math.round(b.y * ih),
        w: Math.round(b.w * iw), h: Math.round(b.h * ih),
      }));

      const extraW = node.widgets?.find(w => w.name === "extra_params");
      if (extraW) {
        let ep = {};
        try { ep = JSON.parse(extraW.value || "{}"); } catch (e) { ep = {}; }
        ep._blur_mode = "selection";
        ep._selection_boxes = currentSelectionBoxes;
        extraW.value = JSON.stringify(ep);
      }
      // Do NOT return here — fall through to apply API call below so preview updates
    }

    // Save tiled mode settings
    if (blurMode === "tiled") {
      const resolvedTileMode = tileModeSelect.value; // Already NxM format
      node.properties._tile_mode = resolvedTileMode;
      node.properties._tile_overlap_x = _selectedGrid?.ovX || 16;
      node.properties._tile_overlap_y = _selectedGrid?.ovY || 16;
      node.properties._selected_tiles_list = JSON.stringify(Array.from(selectedTiles));
      // Write selected tiles to extra_params
      const extraW = node.widgets?.find(w => w.name === "extra_params");
      if (extraW) {
        let ep = {};
        try { ep = JSON.parse(extraW.value || "{}"); } catch (e) { ep = {}; }
        ep._blur_mode = "tiled";
        ep._tile_mode = resolvedTileMode;
        ep._tile_overlap_x = _selectedGrid?.ovX || 16;
        ep._tile_overlap_y = _selectedGrid?.ovY || 16;
        if (selectedTiles.size > 0) {
          ep._selected_tiles = Array.from(selectedTiles);
        } else {
          delete ep._selected_tiles;
        }
        extraW.value = JSON.stringify(ep);
      }
      // Confirm dialog if no tiles selected
      if (selectedTiles.size === 0) {
        showBlurConfirmDialog(
          "未选择任何区块",
          "是否放大全部区块？这将消耗更多算力。\n\n你可以在预览图上点击区块来选择要放大的区域。",
          () => { closeCustomPanel(); node.setDirtyCanvas?.(true, true); },
          "关闭并放大全部", "返回选择"
        );
        return;
      }
      closeCustomPanel();
      node.setDirtyCanvas?.(true, true);
      return;
    }

    // Global/Mask mode: clear tiled params from extra_params
    const extraWClean = node.widgets?.find(w => w.name === "extra_params");
    if (extraWClean) {
      let ep = {};
      try { ep = JSON.parse(extraWClean.value || "{}"); } catch (e) { ep = {}; }
      delete ep._blur_mode;
      delete ep._tile_mode;
      delete ep._tile_overlap;
      delete ep._selected_tiles;
      extraWClean.value = JSON.stringify(ep);
    }

    // Global/Mask/Selection mode: apply blur API
    const sigma = parseFloat(slider.value) || 0;
    if (sigma > 0 || blurMode === "selection") {
      try {
        applyBtn.textContent = "⏳ 正在应用模糊...";
        applyBtn.style.pointerEvents = "none";

        let allImages = [];
        if (window.batchboxAPI?.collectImageInputsBase64) {
          allImages = await window.batchboxAPI.collectImageInputsBase64(node);
        }
        // Only send the first image (blur target) — reference face images should NOT be blurred/previewed
        const blurTargetOnly = allImages.length > 0 ? [allImages[0]] : [];
        if (blurTargetOnly.length > 0) {
          const selectedIndexWidget = node.widgets?.find(w => w.name === "_selected_image_index");
          const selectedIndex = selectedIndexWidget ? selectedIndexWidget.value : 0;
          const resp = await api.fetchApi("/api/batchbox/apply-blur", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              node_id: String(node.id),
              sigma: sigma,
              blur_mode: blurMode,
              blur_mask: node.properties?._blur_mask || "",
              selection_boxes: currentSelectionBoxes,
              images_base64: blurTargetOnly,
              selected_index: selectedIndex,
            }),
          });
          const result = await resp.json();
          if (result.success) {
            console.log("[BlurUpscale] Blur applied and cached:", result);
            if (result.preview_images) {
              node.properties._last_images = JSON.stringify(result.preview_images);
            }
          } else {
            console.error("[BlurUpscale] Apply blur failed:", result.error);
          }
        }
      } catch (e) {
        console.error("[BlurUpscale] Apply blur error:", e);
      }
    }

    closeCustomPanel();
    node.setDirtyCanvas?.(true, true);
  };
  panel.appendChild(applyBtn);

  // --- Make draggable ---
  makeDraggable(panel, header);

  // --- Backdrop ---
  const backdrop = document.createElement("div");
  backdrop.id = "blur-upscale-backdrop";
  Object.assign(backdrop.style, {
    position: "fixed", top: "0", left: "0", width: "100%", height: "100%",
    zIndex: "99998", background: "rgba(0,0,0,0.4)",
  });
  backdrop.onclick = () => closeCustomPanel();
  document.body.appendChild(backdrop);
  document.body.appendChild(panel);
  activePanel = { panel, backdrop };
}


function closeCustomPanel() {
  if (activePanel) {
    activePanel.panel.remove();
    activePanel.backdrop.remove();
    activePanel = null;
  }
}

// ================================================================
// SECTION 2.5: STYLE PRESET POPUP
// ================================================================

let activeStylePopup = null;

function openStylePopup(node, screenX, screenY) {
  closeStylePopup();

  const popup = document.createElement("div");
  popup.id = "blur-upscale-style-popup";
  Object.assign(popup.style, {
    position: "fixed",
    zIndex: "99999",
    width: "240px",
    background: "#1a1a2aee",
    border: "1px solid #3a3a4a",
    borderRadius: "10px",
    boxShadow: "0 8px 32px rgba(0,0,0,0.7)",
    padding: "8px",
    fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif",
    color: "#ddd",
    backdropFilter: "blur(10px)",
    animation: "blur-upscale-fadeIn 0.15s ease",
  });

  // Title
  const title = document.createElement("div");
  title.textContent = "选择风格预设";
  title.style.cssText = "font-size:12px; color:#888; padding:4px 8px 8px; border-bottom:1px solid #2a2a3a; margin-bottom:4px;";
  popup.appendChild(title);

  // Preset items
  for (const [name, prompt] of Object.entries(stylePresets)) {
    const item = document.createElement("div");
    item.className = "blur-upscale-style-item";
    Object.assign(item.style, {
      padding: "8px 12px",
      background: "transparent",
      border: "1px solid transparent",
      borderRadius: "6px",
      color: "#aaa",
      fontSize: "12px",
      cursor: "pointer",
      transition: "all 0.15s ease",
      marginBottom: "2px",
    });

    // Check if this preset is currently active
    const currentPrompt = node.widgets?.find(w => w.name === "style_prompt")?.value || "";
    if (currentPrompt === prompt) {
      item.style.background = "linear-gradient(135deg, #3a2a1e, #2a1a0d)";
      item.style.borderColor = "#8f5a2a";
      item.style.color = "#fff";
    }

    const nameSpan = document.createElement("div");
    nameSpan.textContent = name;
    nameSpan.style.fontWeight = "500";
    item.appendChild(nameSpan);

    const descSpan = document.createElement("div");
    descSpan.textContent = prompt;
    descSpan.style.cssText = "font-size:10px; color:#666; margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;";
    item.appendChild(descSpan);

    item.onmouseenter = () => {
      if (currentPrompt !== prompt) {
        item.style.background = "#2a2a3f";
        item.style.borderColor = "#4a4a5a";
        item.style.color = "#ddd";
      }
    };
    item.onmouseleave = () => {
      if (currentPrompt !== prompt) {
        item.style.background = "transparent";
        item.style.borderColor = "transparent";
        item.style.color = "#aaa";
      }
    };

    item.onclick = () => {
      // Set style_prompt widget
      const pw = node.widgets?.find(w => w.name === "style_prompt");
      if (pw) pw.value = prompt;
      // Sync prompt textarea
      if (node._blurUI?._promptTextarea) node._blurUI._promptTextarea.value = prompt;
      // Set repair_mode to 风格
      const mw = node.widgets?.find(w => w.name === "repair_mode");
      if (mw) mw.value = "风格";
      // Store selected style name for button display
      node._blurUI._selectedStyleName = name;
      // Clear custom active state
      node._blurUI._isCustomActive = false;
      node.setDirtyCanvas(true, true);
      closeStylePopup();
    };

    popup.appendChild(item);
  }

  // "自定义" option at bottom — opens the full custom panel
  const customItem = document.createElement("div");
  Object.assign(customItem.style, {
    padding: "8px 12px",
    borderTop: "1px solid #2a2a3a",
    marginTop: "4px",
    color: "#5a8abf",
    fontSize: "12px",
    cursor: "pointer",
    borderRadius: "6px",
    transition: "all 0.15s ease",
  });
  customItem.textContent = "⚙️ 管理风格预设...";
  customItem.onmouseenter = () => { customItem.style.background = "#2a2a3f"; };
  customItem.onmouseleave = () => { customItem.style.background = "transparent"; };
  customItem.onclick = () => {
    closeStylePopup();
    openStyleEditor(node);
  };
  popup.appendChild(customItem);

  // Position: try to place near the click, but keep within viewport
  document.body.appendChild(popup);
  const rect = popup.getBoundingClientRect();
  let left = screenX;
  let top = screenY + 8;
  if (left + rect.width > window.innerWidth - 10) left = window.innerWidth - rect.width - 10;
  if (top + rect.height > window.innerHeight - 10) top = screenY - rect.height - 8;
  if (left < 10) left = 10;
  if (top < 10) top = 10;
  popup.style.left = `${left}px`;
  popup.style.top = `${top}px`;

  // Backdrop to close on outside click
  const backdrop = document.createElement("div");
  backdrop.id = "blur-upscale-style-backdrop";
  Object.assign(backdrop.style, {
    position: "fixed", top: "0", left: "0", width: "100%", height: "100%",
    zIndex: "99998", background: "transparent",
  });
  backdrop.onclick = () => closeStylePopup();
  document.body.appendChild(backdrop);

  activeStylePopup = { popup, backdrop };
}

function closeStylePopup() {
  if (activeStylePopup) {
    activeStylePopup.popup.remove();
    activeStylePopup.backdrop.remove();
    activeStylePopup = null;
  }
}

// ================================================================
// SECTION 2.6: STYLE EDITOR PANEL
// ================================================================

let activeStyleEditor = null;

function openStyleEditor(node) {
  closeStyleEditor();

  const panel = document.createElement("div");
  panel.id = "blur-upscale-style-editor";
  Object.assign(panel.style, {
    position: "fixed", zIndex: "99999",
    left: "50%", top: "50%", transform: "translate(-50%, -50%)",
    width: "520px", maxWidth: "90vw", maxHeight: "85vh",
    display: "flex", flexDirection: "column",
    background: "#1a1a2aee", border: "1px solid #3a3a4a",
    borderRadius: "14px", boxShadow: "0 16px 64px rgba(0,0,0,0.8)",
    padding: "20px", fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif",
    color: "#ddd", backdropFilter: "blur(10px)", boxSizing: "border-box",
  });

  // --- Header ---
  const header = document.createElement("div");
  Object.assign(header.style, {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    marginBottom: "16px", paddingBottom: "10px", borderBottom: "1px solid #2a2a3a",
  });
  const title = document.createElement("span");
  title.textContent = "风格预设管理";
  title.style.cssText = "font-size:15px; font-weight:600;";
  header.appendChild(title);

  const closeBtn = document.createElement("button");
  closeBtn.textContent = "✕";
  Object.assign(closeBtn.style, {
    width: "28px", height: "28px", background: "#2a2a3a", border: "1px solid #3a3a4a",
    borderRadius: "50%", color: "#888", fontSize: "14px", cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
  });
  closeBtn.onclick = () => closeStyleEditor();
  header.appendChild(closeBtn);
  panel.appendChild(header);

  // --- Preset List (scrollable) ---
  const listBox = document.createElement("div");
  listBox.id = "style-editor-list";
  Object.assign(listBox.style, {
    flex: "1", overflowY: "auto", marginBottom: "12px",
    display: "flex", flexDirection: "column", gap: "8px",
  });
  panel.appendChild(listBox);

  // Working copy of presets as ordered array for drag reordering
  const draft = Object.entries(stylePresets).map(([name, prompt]) => ({ name, prompt }));

  // Drag state
  let dragIdx = -1;

  function renderList() {
    listBox.innerHTML = "";
    if (draft.length === 0) {
      listBox.innerHTML = '<div style="color:#555;text-align:center;padding:20px">暂无风格预设，点击下方按钮添加</div>';
      return;
    }
    for (let i = 0; i < draft.length; i++) {
      listBox.appendChild(createPresetRow(i));
    }
  }

  function createPresetRow(idx) {
    const item = draft[idx];
    const row = document.createElement("div");
    row.draggable = true;
    row.dataset.idx = idx;
    Object.assign(row.style, {
      background: "#222233", border: "1px solid #3a3a4a", borderRadius: "8px",
      padding: "10px 12px", display: "flex", flexDirection: "column", gap: "6px",
      transition: "border-color 0.15s, opacity 0.15s",
    });

    // --- Drag events ---
    row.ondragstart = (e) => {
      dragIdx = idx;
      row.style.opacity = "0.4";
      e.dataTransfer.effectAllowed = "move";
    };
    row.ondragend = () => {
      row.style.opacity = "1";
      dragIdx = -1;
      // Clear all drop indicators
      listBox.querySelectorAll("[data-idx]").forEach(r => {
        r.style.borderTop = ""; r.style.borderBottom = "";
      });
    };
    row.ondragover = (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      const targetIdx = parseInt(row.dataset.idx);
      if (targetIdx === dragIdx) return;
      // Show drop indicator
      const rect = row.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      listBox.querySelectorAll("[data-idx]").forEach(r => {
        r.style.borderTop = ""; r.style.borderBottom = "";
      });
      if (e.clientY < midY) {
        row.style.borderTop = "2px solid #5a8abf";
      } else {
        row.style.borderBottom = "2px solid #5a8abf";
      }
    };
    row.ondragleave = () => {
      row.style.borderTop = ""; row.style.borderBottom = "";
    };
    row.ondrop = (e) => {
      e.preventDefault();
      const targetIdx = parseInt(row.dataset.idx);
      if (dragIdx < 0 || dragIdx === targetIdx) return;
      const rect = row.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      const insertBefore = e.clientY < midY;
      // Move item in draft array
      const [moved] = draft.splice(dragIdx, 1);
      let newIdx = insertBefore ? targetIdx : targetIdx + 1;
      if (dragIdx < targetIdx) newIdx--;
      draft.splice(newIdx, 0, moved);
      dragIdx = -1;
      renderList();
    };

    // Top: drag handle + name + delete button
    const topRow = document.createElement("div");
    topRow.style.cssText = "display:flex; align-items:center; gap:6px;";

    // Drag handle
    const handle = document.createElement("span");
    handle.textContent = "☰";
    Object.assign(handle.style, {
      cursor: "grab", color: "#555", fontSize: "14px", userSelect: "none",
      padding: "0 2px", flexShrink: "0",
    });
    handle.onmouseenter = () => handle.style.color = "#aaa";
    handle.onmouseleave = () => handle.style.color = "#555";
    topRow.appendChild(handle);

    const nameInput = document.createElement("input");
    nameInput.value = item.name;
    Object.assign(nameInput.style, {
      flex: "1", background: "transparent", border: "none", color: "#ddd",
      fontSize: "13px", fontWeight: "600", outline: "none", padding: "2px 0",
    });
    nameInput.onfocus = () => nameInput.style.borderBottom = "1px solid #5a8abf";
    nameInput.onblur = () => {
      nameInput.style.borderBottom = "none";
      const newName = nameInput.value.trim();
      if (newName) draft[idx].name = newName;
    };
    topRow.appendChild(nameInput);

    const delBtn = document.createElement("button");
    delBtn.textContent = "删除";
    Object.assign(delBtn.style, {
      padding: "3px 10px", background: "transparent", border: "1px solid #5a3a3a",
      borderRadius: "4px", color: "#c55", fontSize: "11px", cursor: "pointer",
      flexShrink: "0",
    });
    delBtn.onclick = () => { draft.splice(idx, 1); renderList(); };
    topRow.appendChild(delBtn);
    row.appendChild(topRow);

    // Bottom: prompt textarea
    const promptArea = document.createElement("textarea");
    promptArea.value = item.prompt;
    Object.assign(promptArea.style, {
      width: "100%", minHeight: "40px", background: "#1a1a2a", border: "1px solid #2a2a3a",
      borderRadius: "4px", padding: "6px 8px", color: "#aaa", fontSize: "12px",
      resize: "vertical", fontFamily: "inherit", boxSizing: "border-box", outline: "none",
    });
    promptArea.onfocus = () => promptArea.style.borderColor = "#5a8abf";
    promptArea.onblur = () => {
      promptArea.style.borderColor = "#2a2a3a";
      draft[idx].prompt = promptArea.value;
    };
    row.appendChild(promptArea);

    return row;
  }

  renderList();

  // --- Add Button ---
  const addBtn = document.createElement("button");
  addBtn.textContent = "+ 添加新风格";
  Object.assign(addBtn.style, {
    width: "100%", padding: "10px", background: "#2a2a3a", border: "1px dashed #4a4a5a",
    borderRadius: "8px", color: "#888", fontSize: "13px", cursor: "pointer",
    marginBottom: "12px",
  });
  addBtn.onclick = () => {
    let idx = draft.length + 1;
    let newName = `新风格 ${idx}`;
    while (draft.some(d => d.name === newName)) { idx++; newName = `新风格 ${idx}`; }
    draft.push({ name: newName, prompt: "" });
    renderList();
    listBox.scrollTop = listBox.scrollHeight;
  };
  panel.appendChild(addBtn);

  // --- Save Button ---
  const saveBtn = document.createElement("button");
  saveBtn.textContent = "保存";
  Object.assign(saveBtn.style, {
    width: "100%", padding: "12px", fontSize: "14px", fontWeight: "500",
    background: "linear-gradient(135deg, #2a5a8f, #1a3a5f)", border: "1px solid #3a7abf",
    borderRadius: "8px", color: "#fff", cursor: "pointer",
  });
  saveBtn.onclick = async () => {
    // Convert array back to ordered object
    const obj = {};
    for (const item of draft) {
      const name = item.name.trim();
      if (name) obj[name] = item.prompt;
    }
    stylePresets = obj;
    saveBtn.textContent = "保存中...";
    saveBtn.disabled = true;
    const ok = await saveStylePresets();
    saveBtn.textContent = ok ? "已保存" : "保存失败";
    setTimeout(() => closeStyleEditor(), 600);
  };
  panel.appendChild(saveBtn);

  // --- Backdrop ---
  const backdrop = document.createElement("div");
  backdrop.id = "blur-upscale-style-editor-backdrop";
  Object.assign(backdrop.style, {
    position: "fixed", top: "0", left: "0", width: "100%", height: "100%",
    zIndex: "99998", background: "rgba(0,0,0,0.4)",
  });
  backdrop.onclick = () => closeStyleEditor();
  document.body.appendChild(backdrop);
  document.body.appendChild(panel);
  activeStyleEditor = { panel, backdrop };
}

function closeStyleEditor() {
  if (activeStyleEditor) {
    activeStyleEditor.panel.remove();
    activeStyleEditor.backdrop.remove();
    activeStyleEditor = null;
  }
}

function getLinkedInputImageUrl(node) {
  const inputLink = node.inputs?.[0]?.link;
  if (!inputLink || !app.graph) {
    return null;
  }

  const linkInfo = app.graph.links[inputLink];
  if (!linkInfo) {
    return null;
  }

  const srcNode = app.graph.getNodeById(linkInfo.origin_id);
  if (!srcNode) {
    return null;
  }

  if (srcNode.imgs?.length > 0 && srcNode.imgs[0].src) {
    return srcNode.imgs[0].src;
  }

  const previewInfo = srcNode.images?.[0];
  if (previewInfo?.filename) {
    return `/view?filename=${encodeURIComponent(previewInfo.filename)}&subfolder=${encodeURIComponent(previewInfo.subfolder || "")}&type=${previewInfo.type || "output"}`;
  }

  const imageWidget = srcNode.widgets?.find(w =>
    w.name === "image" && typeof w.value === "string" && w.value
  );
  if (imageWidget) {
    return `/view?filename=${encodeURIComponent(imageWidget.value)}&type=input`;
  }

  return null;
}

function getInputImageSrc(node) {
  return getLinkedInputImageUrl(node);
}

async function getInputImageBase64(node) {
  const imageUrl = getLinkedInputImageUrl(node);
  if (imageUrl) {
    return await imgToBase64(imageUrl);
  }
  return null;
}

async function imgToBase64(src) {
  try {
    const resp = await fetch(src);
    const blob = await resp.blob();
    return new Promise(r => { const rd = new FileReader(); rd.onloadend = () => r(rd.result); rd.readAsDataURL(blob); });
  } catch { return null; }
}

function makeDraggable(el, handle) {
  let ox = 0, oy = 0;
  // ⚡ PERF: Only attach mousemove/mouseup during active drag, remove on mouseup
  const onMouseMove = (e) => {
    el.style.left = `${e.clientX - ox}px`;
    el.style.top = `${e.clientY - oy}px`;
    el.style.transform = "none";
  };
  const onMouseUp = () => {
    handle.style.cursor = "grab";
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", onMouseUp);
  };
  handle.addEventListener("mousedown", (e) => {
    if (e.target.tagName === "BUTTON") return;
    const rect = el.getBoundingClientRect();
    ox = e.clientX - rect.left; oy = e.clientY - rect.top;
    handle.style.cursor = "grabbing"; e.preventDefault();
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  });
}


// ================================================================
// SECTION 3: INJECT STYLES
// ================================================================

function injectStyles() {
  if (document.getElementById("blur-upscale-styles")) return;
  const style = document.createElement("style");
  style.id = "blur-upscale-styles";
  style.textContent = `@keyframes blur-spin { to { transform: rotate(360deg); } }`;
  document.head.appendChild(style);
}


// ================================================================
// SECTION 4: CANVAS-DRAWN BUTTON GROUPS
// ================================================================

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
    ctx.fillText(options[i].replace(/ \(.*\)/, ""), bx + btnW / 2, btnY + btnH / 2 + 4);
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
  ctx.fillText("⚙️ 自定义设置（预览 + 精确调节）", x + w / 2, y + btnH / 2 + 4);
  return btnH + 6;
}

function hitTestRect(x, y, w, h, clickX, clickY) {
  return clickX >= x && clickX <= x + w && clickY >= y && clickY <= y + h;
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


// ================================================================
// SECTION 5: NODE REGISTRATION
// ================================================================

app.registerExtension({
  name: "Comfy.BatchBox.GaussianBlurUpscale",

  async beforeRegisterNodeDef(nodeType, nodeData, _app) {
    if (nodeData.name !== "GaussianBlurUpscale") return;

    injectStyles();

    const origOnNodeCreated = nodeType.prototype.onNodeCreated;

    nodeType.prototype.onNodeCreated = function () {
      if (origOnNodeCreated) {
        origOnNodeCreated.apply(this, arguments);
      }

      const node = this;
      node._blurUI = { blurGroupY: 0, modeGroupY: 0, customBtnY: 0, drawStartY: 0, model: "", _isCustomActive: false, _selectedStyleName: "" };

      // --- Hide widgets we manage ourselves (same approach as dynamic_params.js) ---
      const widgetsToHide = ["blur_intensity", "repair_mode", "custom_sigma", "style_prompt", "seed", "control_after_generate", "生成后控制", "extra_params", "手动选择端点", "endpoint_selector"];
      const hideWidget = (w) => {
        w.hidden = true;
        w.computeSize = () => [0, -4];
        w.type = "hidden";
        w.mouse = () => true;  // Consume clicks to prevent "Value" dialog
        // Hide any DOM element (textarea/input) that ComfyUI creates for multiline widgets
        if (w.inputEl) {
          w.inputEl.style.display = "none";
          w.inputEl.style.pointerEvents = "none";
          w.inputEl.style.position = "absolute";
          w.inputEl.style.left = "-9999px";
        }
      };
      const hideAllManaged = () => {
        for (const widget of node.widgets || []) {
          if (widgetsToHide.includes(widget.name)) {
            hideWidget(widget);
            if (widget.name === "control_after_generate" || widget.name === "生成后控制") {
              widget.value = "fixed";
            }
          }
        }
      };
      hideAllManaged();
      // Retry: ComfyUI may add control_after_generate AFTER onNodeCreated
      setTimeout(() => { hideAllManaged(); node.setDirtyCanvas?.(true); }, 100);

      let extraParamsWidget = node.widgets?.find(w => w.name === "extra_params");
      if (!extraParamsWidget) {
        extraParamsWidget = node.addWidget("string", "extra_params", "{}", () => { });
        extraParamsWidget.serialize = true;
      }
      // Always hide + clean up any leftover DOM textarea from old "text" type widget
      hideWidget(extraParamsWidget);
      if (extraParamsWidget.inputEl) {
        extraParamsWidget.inputEl.remove();
        delete extraParamsWidget.inputEl;
      }

      // --- Remove non-image input slots (prevent combo/widget connectors overlapping image inputs) ---
      setTimeout(() => {
        if (node.inputs) {
          for (let i = node.inputs.length - 1; i >= 0; i--) {
            if (node.inputs[i].name && !node.inputs[i].name.startsWith("image")) {
              node.removeInput(i);
            }
          }
        }
      }, 50);

      // --- Add "▶ 开始生成" button ---
      if (!node.widgets?.find(w => w._isGenerateButton)) {
        const generateBtn = node.addWidget("button", "▶ 开始生成", null, async () => {
          // Prevent double-click
          if (generateBtn._isGenerating) return;

          // Update button state
          generateBtn._isGenerating = true;
          generateBtn.name = "⏳ 生成中...";
          node.setDirtyCanvas(true, true);

          // Randomize seed
          const seedWidget = node.widgets?.find(w => w.name === "seed");
          if (seedWidget) {
            seedWidget.value = Math.floor(Math.random() * 2147483647);
          }

          // Check if tiled mode — must use queue execution (independent API doesn't support tiled)
          const extraW = node.widgets?.find(w => w.name === "extra_params");
          let isTiledMode = false;
          if (extraW) {
            try {
              const ep = JSON.parse(extraW.value || "{}");
              isTiledMode = ep._blur_mode === "tiled";
            } catch (e) { }
          }

          if (isTiledMode) {
            console.log("[BlurUpscale] Tiled mode detected, using queue execution...");
            // Listen for progress
            const myNodeId = String(node.id);
            function onProgress(evt) {
              const d = evt.detail;
              if (d && typeof d.value === "number" && typeof d.max === "number") {
                generateBtn.name = `\u23f3 \u751f\u6210\u4e2d ${d.value}/${d.max}`;
                requestNodeCanvasRefresh(node);
              }
            }
            function onExecuted(evt) {
              const d = evt.detail;
              if (d && d.node && String(d.node) !== myNodeId) return;
              api.removeEventListener("progress", onProgress);
              api.removeEventListener("executed", onExecuted);
              generateBtn._isGenerating = false;
              generateBtn.name = "\u25b6 \u5f00\u59cb\u751f\u6210";
              node.setDirtyCanvas(true, true);
            }
            api.addEventListener("progress", onProgress);
            api.addEventListener("executed", onExecuted);
            executeScopedToNode(node);
            return;
          }

          // Try independent generation (concurrent), fallback to queue
          let progressHandler = null;
          try {
            // Collect all connected image inputs via shared API
            let allImagesBase64 = [];
            if (window.batchboxAPI?.collectImageInputsBase64) {
              allImagesBase64 = await window.batchboxAPI.collectImageInputsBase64(node);
            } else {
              // Fallback to legacy single-image method
              const singleB64 = await getInputImageBase64(node);
              if (singleB64) allImagesBase64 = [singleB64];
            }
            if (allImagesBase64.length === 0) {
              throw new Error("无法获取输入图片，请确保已连接加载图像节点");
            }

            // Split: first image = blur target, rest = reference face images
            const blurTargetImages = [allImagesBase64[0]];
            const referenceImages = allImagesBase64.slice(1);
            if (referenceImages.length > 0) {
              console.log(`[BlurUpscale] ${blurTargetImages.length} blur target(s) + ${referenceImages.length} reference image(s)`);
            }

            const generationToken = `blur_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

            // Collect widget values
            const getVal = (name, def) => node.widgets?.find(w => w.name === name)?.value ?? def;

            // Check endpoint override from toggle + selector
            const toggleW = node.widgets?.find(w => w.name === "手动选择端点");
            const selectorW = node.widgets?.find(w => w.name === "endpoint_selector");
            const endpointOverride = (toggleW?.value && selectorW) ? selectorW.value : null;

            const requestBody = {
              node_id: String(node.id),
              generation_token: generationToken,
              blur_intensity: getVal("blur_intensity", "轻 (σ1-3)"),
              custom_sigma: parseFloat(getVal("custom_sigma", 0)),
              repair_mode: getVal("repair_mode", "直出"),
              style_prompt: getVal("style_prompt", ""),
              seed: getVal("seed", 0),
              batch_count: getVal("batch_count", 1),
              aspect_ratio: getVal("aspect_ratio", "auto"),
              images_base64: blurTargetImages,
              reference_images_base64: referenceImages,
              endpoint_override: endpointOverride,
              blur_mask: node.properties?._blur_mask || "",
            };

            // Extract blur_mode and selection_boxes from extra_params or node.properties
            if (extraW) {
              try {
                const ep = JSON.parse(extraW.value || "{}");
                if (ep._blur_mode) requestBody.blur_mode = ep._blur_mode;
              } catch (e) { }
            }
            // Fallback: read from node.properties if not found in extra_params
            if (!requestBody.blur_mode && node.properties?._blur_mode) {
              requestBody.blur_mode = node.properties._blur_mode;
            }
            // Always read selection_boxes from node.properties (has latest refRange data)
            if (node.properties?._selection_boxes) {
              try {
                requestBody.selection_boxes = JSON.parse(node.properties._selection_boxes);
              } catch (e) { }
            }
            // Fallback to extra_params if node.properties has nothing
            if (!requestBody.selection_boxes && extraW) {
              try {
                const ep = JSON.parse(extraW.value || "{}");
                if (ep._selection_boxes) requestBody.selection_boxes = ep._selection_boxes;
              } catch (e) { }
            }
            if (requestBody.selection_boxes?.length) {
              // Auto-set blur_mode to "selection" if we have boxes but no explicit mode
              if (!requestBody.blur_mode) requestBody.blur_mode = "selection";
              console.log(`[BlurUpscale] Selection mode: ${requestBody.selection_boxes.length} boxes`);

              // Build selection_ref_mapping from each box's refRange
              // refRange format: "2-4" (range) or "2,3,4" (list) — slot numbers starting from 2
              // Convert to 0-based indices into reference_images_base64 (slot 2 = index 0)
              if (referenceImages.length > 0) {
                const refMapping = {};
                requestBody.selection_boxes.forEach((box, idx) => {
                  if (!box.refRange) return;
                  const range = box.refRange.trim();
                  let indices = [];
                  if (range.includes("-")) {
                    // Range: "2-4" → [2,3,4] → indices [0,1,2]
                    const parts = range.split("-").map(s => parseInt(s.trim()));
                    if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
                      for (let n = parts[0]; n <= parts[1]; n++) {
                        indices.push(n - 2); // slot 2 → ref index 0
                      }
                    }
                  } else {
                    // Comma list: "2,3,4" → indices [0,1,2]
                    indices = range.split(",").map(s => parseInt(s.trim()) - 2).filter(n => !isNaN(n));
                  }
                  if (indices.length > 0) {
                    refMapping[String(idx)] = indices;
                  }
                });
                if (Object.keys(refMapping).length > 0) {
                  requestBody.selection_ref_mapping = refMapping;
                  console.log(`[BlurUpscale] Reference mapping:`, refMapping);
                }
              }
            }

            // Register progress listener
            const nodeIdStr = String(node.id);
            progressHandler = (event) => {
              const d = event.detail;
              if (String(d.node_id) !== nodeIdStr) return;
              if (d.generation_token && d.generation_token !== generationToken) return;
              generateBtn.name = `⏳ 生成中 ${d.completed}/${d.total}`;
              requestNodeCanvasRefresh(node);
            };
            api.addEventListener("batchbox:progress", progressHandler);

            console.log("[BlurUpscale] Starting independent generation...");
            const response = await api.fetchApi("/api/batchbox/generate-blur-upscale", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(requestBody)
            });
            const result = await response.json();

            if (result.success) {
              console.log("[BlurUpscale] Generation complete:", result.response_info);
              // Store cache metadata
              if (!node.properties) node.properties = {};
              node.properties._last_images = JSON.stringify(result.preview_images);
              if (result.params_hash) {
                node.properties._cached_hash = result.params_hash;
              }
            } else {
              console.error("[BlurUpscale] Generation failed:", result.error);
              alert(`生成失败: ${result.error}`);
            }
          } catch (e) {
            console.error("[BlurUpscale] Independent generation error:", e);
            // Fallback: use ComfyUI queue
            console.log("[BlurUpscale] Falling back to queue execution");
            executeScopedToNode(node);
          } finally {
            if (progressHandler) {
              api.removeEventListener("batchbox:progress", progressHandler);
            }
            generateBtn._isGenerating = false;
            generateBtn.name = "▶ 开始生成";
            node.setDirtyCanvas(true, true);
          }
        });
        generateBtn._isGenerateButton = true;
        generateBtn._isGenerating = false;

        // Move button to position 1 (after batch_count or early in list)
        const widgets = node.widgets;
        const btnIndex = widgets.indexOf(generateBtn);
        if (btnIndex > 1) {
          widgets.splice(btnIndex, 1);
          widgets.splice(1, 0, generateBtn);
        }

        // Listen for execution complete (for Queue Prompt fallback path)
        // ⚡ PERF: Store refs for cleanup in onRemoved (prevent listener accumulation)
        const onExecuted = (e) => {
          if (String(e.detail?.node) === String(node.id)) {
            generateBtn._isGenerating = false;
            generateBtn.name = "▶ 开始生成";
            node.setDirtyCanvas(true, true);
          }
        };
        const onExecutionError = () => {
          generateBtn._isGenerating = false;
          generateBtn.name = "▶ 开始生成";
          node.setDirtyCanvas(true, true);
        };
        api.addEventListener("executed", onExecuted);
        api.addEventListener("execution_error", onExecutionError);
        // Store refs for cleanup
        node._blurExecutedHandler = onExecuted;
        node._blurExecutionErrorHandler = onExecutionError;
      }

      // --- Spacer widget to reserve space for canvas-drawn UI ---
      // Use addWidget so LiteGraph properly accounts for this widget's height
      // in its layout calculations (including image preview positioning).
      // Button hit-testing lives here since LiteGraph intercepts widget clicks
      // BEFORE onMouseDown.
      const SPACER_HEIGHT = 160;
      const spacer = node.addWidget("custom", "_blur_spacer", "", () => { });
      spacer._isSpacer = true;
      spacer.serialize = false;
      spacer.computeSize = () => [node.size[0], SPACER_HEIGHT];
      spacer.draw = function () { };
      spacer.mouse = function (event, pos, nodeRef) {
        if (event.type !== "pointerdown" && event.type !== "mousedown") return true;

        const padding = 10;
        const innerW = nodeRef.size[0] - padding * 2;
        const clickX = pos[0];
        const clickY = pos[1];
        const ui = nodeRef._blurUI;
        if (!ui) return true;

        // Blur intensity buttons
        const blurHit = hitTestButtonGroup(padding, 0, innerW, BLUR_PRESETS, clickX, clickY, ui.blurGroupY);
        if (blurHit) {
          const w = nodeRef.widgets?.find(w => w.name === "blur_intensity");
          if (w) { w.value = blurHit; w.callback?.(blurHit); }
          // Sync: set custom_sigma to preset's default value
          const presetSigma = { "轻 (σ1-3)": 2.0, "中 (σ3-6)": 4.0, "重 (σ6-10)": 7.0 };
          const csw = nodeRef.widgets?.find(w => w.name === "custom_sigma");
          if (csw && presetSigma[blurHit] !== undefined) { csw.value = presetSigma[blurHit]; }
          nodeRef.setDirtyCanvas(true, true);
          return true;
        }

        // Repair mode buttons
        const modeHit = hitTestButtonGroup(padding, 0, innerW, REPAIR_MODES, clickX, clickY, ui.modeGroupY);
        if (modeHit) {
          if (modeHit === "风格") {
            openStylePopup(nodeRef, event.clientX, event.clientY);
          } else {
            const w = nodeRef.widgets?.find(w => w.name === "repair_mode");
            if (w) { w.value = modeHit; w.callback?.(modeHit); }
            // Clear selected style name when switching away from 风格
            nodeRef._blurUI._selectedStyleName = "";
          }
          nodeRef.setDirtyCanvas(true, true);
          return true;
        }

        // Custom settings button
        if (hitTestRect(padding, ui.customBtnY, innerW, 30, clickX, clickY)) {
          openCustomPanel(nodeRef);
          return true;
        }

        return true;
      };

      // --- Load model info, endpoint options, and style presets ---
      loadUpscaleSettings().then(({ displayText, model, endpoint, endpointOptions }) => {
        node._blurUI.model = displayText;
        node._blurUI._upscaleModel = model;
        node._blurUI._savedEndpoint = endpoint;
        node.setDirtyCanvas(true);

        // Add endpoint selector if model has multiple endpoints
        if (endpointOptions && endpointOptions.length >= 2) {
          const options = endpointOptions.map(ep => ep.name);
          const pendingEndpointState = node._pendingEndpointState;
          const initialManualEnabled = pendingEndpointState?.manualEnabled || false;
          const initialEndpoint = (
            pendingEndpointState?.selectedEndpoint && options.includes(pendingEndpointState.selectedEndpoint)
          ) ? pendingEndpointState.selectedEndpoint : (
            endpoint && options.includes(endpoint) ? endpoint : options[0]
          );
          if (pendingEndpointState) {
            delete node._pendingEndpointState;
          }

          const toggleWidget = node.addWidget("toggle", "手动选择端点", initialManualEnabled, (v) => {
            if (selectorWidget) {
              selectorWidget.hidden = !v;
            }
            syncEndpointOverrideExtraParams(node);
            // Recalc node size
            const currentWidth = node.size[0];
            const computedSize = node.computeSize();
            node.setSize([currentWidth, computedSize[1]]);
          });
          toggleWidget.serialize = false;

          const selectorWidget = node.addWidget("combo", "endpoint_selector", initialEndpoint, () => { }, {
            values: options
          });
          selectorWidget.hidden = !initialManualEnabled;
          selectorWidget.serialize = false;
          selectorWidget.callback = () => syncEndpointOverrideExtraParams(node);

          syncEndpointOverrideExtraParams(node);

          // Recalc node size
          const currentWidth = node.size[0];
          const computedSize = node.computeSize();
          node.setSize([currentWidth, computedSize[1]]);
        }
      });
      loadStylePresets();

      // --- Inject endpoint_override into extra_params before execution ---
      const origExecute = node.onExecute;
      node.onExecute = function () {
        if (origExecute) origExecute.apply(this, arguments);
        syncEndpointOverrideExtraParams(node);
      };

      // --- Ensure minimum node size ---
      const minH = 280;
      if (node.size[1] < minH) node.size[1] = minH;

      // ---- onDrawForeground ----
      // Draw custom buttons inside the spacer area.
      // Image preview is handled natively by LiteGraph AFTER the spacer.
      const origDraw = node.onDrawForeground;

      // ⚡ PERF: Cache widget refs ONCE outside the per-frame draw loop.
      // onDrawForeground runs 30-60× /sec — find() would be extremely wasteful.
      let _cachedBlurWidget = null;
      let _cachedModeWidget = null;
      let _cachedStyleWidget = null;
      let _widgetCacheValid = false;

      function ensureWidgetCache() {
        if (_widgetCacheValid && _cachedBlurWidget && _cachedModeWidget) return;
        const widgets = node.widgets;
        if (!widgets) return;
        _cachedBlurWidget = widgets.find(w => w.name === "blur_intensity") || null;
        _cachedModeWidget = widgets.find(w => w.name === "repair_mode") || null;
        _cachedStyleWidget = widgets.find(w => w.name === "style_prompt") || null;
        _widgetCacheValid = true;
      }

      // ⚡ PERF: Pre-compute style entries once (Object.entries is allocation-heavy)
      const _styleEntries = Object.entries(stylePresets);

      node.onDrawForeground = function (ctx) {
        if (origDraw) origDraw.apply(this, arguments);

        const padding = 10;
        const innerW = node.size[0] - padding * 2;

        // Anchor to spacer's actual position (set by LiteGraph layout)
        let startY = (spacer.last_y || 30) + 4;
        node._blurUI.drawStartY = startY;

        // ⚡ Lazy-init widget cache (widgets may not exist at node creation time)
        ensureWidgetCache();

        // 1. Blur Intensity
        const blurVal = _cachedBlurWidget?.value || "轻 (σ1-3)";
        node._blurUI.blurGroupY = startY;
        const h1 = drawButtonGroup(ctx, padding, startY, innerW, BLUR_PRESETS, blurVal, "模糊程度", {
          bgActive: COLORS.bgActive, borderActive: COLORS.borderActive,
          text: COLORS.text, textActive: COLORS.textActive,
        });
        startY += h1;

        // 2. Repair Mode
        const modeVal = _cachedModeWidget?.value || "直出";
        node._blurUI.modeGroupY = startY;
        // If style is selected, initialize _selectedStyleName from style_prompt (for load/reload)
        if (modeVal === "风格" && !node._blurUI._selectedStyleName) {
          const sp = _cachedStyleWidget?.value || "";
          for (const [sName, sPrompt] of _styleEntries) {
            if (sp === sPrompt) { node._blurUI._selectedStyleName = sName; break; }
          }
        }
        // Show selected style name on the "风格" button
        const displayModes = node._blurUI._selectedStyleName
          ? REPAIR_MODES.map(m => m === "风格" ? node._blurUI._selectedStyleName : m)
          : REPAIR_MODES;
        const h2 = drawButtonGroup(ctx, padding, startY, innerW, displayModes,
          node._blurUI._selectedStyleName || modeVal, "修复模式", {
          bgActive: modeVal === "风格" ? COLORS.bgStyle : COLORS.bgActive,
          borderActive: modeVal === "风格" ? COLORS.borderStyle : COLORS.borderActive,
          text: COLORS.text, textActive: COLORS.textActive,
        });
        startY += h2;

        // 3. Custom Settings Button
        node._blurUI.customBtnY = startY;
        const h3 = drawCustomButton(ctx, padding, startY, innerW, node._blurUI._isCustomActive);
        startY += h3;

        // 4. Model Info
        ctx.fillStyle = node._blurUI.model ? "#555" : "#f55";
        ctx.font = "10px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(
          node._blurUI.model ? `放大模型: ${node._blurUI.model}` : "⚠️ 未配置放大模型 (请在 Manager 设置中配置)",
          node.size[0] / 2, startY + 12
        );
      };

      // ---- onMouseDown (fallback for clicks outside spacer area) ----
      const origMouseDown = node.onMouseDown;
      node.onMouseDown = function (e, localPos, canvas) {
        if (origMouseDown) {
          const result = origMouseDown.apply(this, arguments);
          if (result) return result;
        }
        return false;
      };

      // Cleanup
      const origRemoved = node.onRemoved;
      node.onRemoved = function () {
        if (origRemoved) origRemoved.apply(this, arguments);
        closeCustomPanel();
        closeStylePopup();
        closeStyleEditor();
        // ⚡ PERF: Remove api event listeners to prevent leaks
        if (node._blurExecutedHandler) {
          api.removeEventListener("executed", node._blurExecutedHandler);
        }
        if (node._blurExecutionErrorHandler) {
          api.removeEventListener("execution_error", node._blurExecutionErrorHandler);
        }
      };
    };

    const origOnSerialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onSerialize = function (o) {
      if (origOnSerialize) {
        origOnSerialize.apply(this, arguments);
      }

      const toggleWidget = this.widgets?.find(w => w.name === "手动选择端点");
      const selectorWidget = this.widgets?.find(w => w.name === "endpoint_selector");
      if (toggleWidget || selectorWidget) {
        o.endpointState = {
          manualEnabled: toggleWidget?.value || false,
          selectedEndpoint: selectorWidget?.value || "",
        };
      }
    };

    const origOnConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (o) {
      if (origOnConfigure) {
        origOnConfigure.apply(this, arguments);
      }

      if (!o.endpointState) {
        return;
      }

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
  },
});


// ================================================================
// SECTION 6: HELPERS
// ================================================================

async function loadUpscaleSettings() {
  try {
    const resp = await api.fetchApi("/api/batchbox/upscale-settings");
    if (resp.ok) {
      const data = await resp.json();
      const model = data.upscale_settings?.model || "";
      const endpoint = data.upscale_settings?.endpoint || "";
      const displayText = endpoint ? `${model} [${endpoint}]` : model;

      // Also fetch endpoint options from model schema
      let endpointOptions = [];
      if (model) {
        try {
          const schemaResp = await api.fetchApi(`/api/batchbox/schema/${model}`);
          if (schemaResp.ok) {
            const schemaData = await schemaResp.json();
            endpointOptions = schemaData.endpoint_options || [];
          }
        } catch (e) {
          console.warn("[BlurUpscale] Could not load endpoint options:", e);
        }
      }

      return { displayText, model, endpoint, endpointOptions };
    }
  } catch (e) { console.warn("[BlurUpscale] Could not load upscale settings:", e); }
  return { displayText: "", model: "", endpoint: "", endpointOptions: [] };
}


console.log("[ComfyUI-Custom-Batchbox] Gaussian Blur Upscale extension loaded");
