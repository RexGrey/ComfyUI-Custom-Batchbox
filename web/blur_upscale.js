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
  const orig = api.queuePrompt;
  api.queuePrompt = async function (index, prompt) {
    if (prompt.output) {
      const filtered = {};
      collectNodeDeps(String(node.id), prompt.output, filtered);
      prompt.output = filtered;
    }
    const result = await orig.apply(api, [index, prompt]);
    api.queuePrompt = orig;
    return result;
  };
  try {
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
  slider.max = "15";
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

  slider.oninput = () => {
    const s = parseFloat(slider.value);
    sigmaVal.textContent = s;
    const w = node.widgets?.find(w => w.name === "custom_sigma");
    if (w) w.value = s;
    const img = panel.querySelector("#blur-preview-img");
    if (img) img.style.filter = `blur(${s * blurScaleRatio}px)`;
  };
  sigmaSection.appendChild(slider);
  panel.appendChild(sigmaSection);

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

  // Load source image once, apply CSS blur for real-time preview
  (async () => {
    const imgSrc = await getInputImageSrc(node);
    if (!imgSrc) return;
    const img = document.createElement("img");
    img.id = "blur-preview-img";
    img.src = imgSrc;
    img.style.cssText = "max-width:100%;max-height:100%;object-fit:contain;border-radius:6px;transition:filter 0.05s;";
    img.onload = () => {
      // Calculate scale ratio: displayed size vs original size
      const displayedW = img.offsetWidth || img.clientWidth;
      const naturalW = img.naturalWidth;
      if (naturalW > 0 && displayedW > 0) {
        blurScaleRatio = displayedW / naturalW;
      }
      img.style.filter = `blur(${currentSigma * blurScaleRatio}px)`;
    };
    previewBox.innerHTML = "";
    previewBox.appendChild(img);
  })();

  // --- Style Prompt ---
  const promptSection = document.createElement("div");
  promptSection.style.marginBottom = "20px";
  const promptLabel = document.createElement("div");
  promptLabel.textContent = "风格提示词";
  promptLabel.style.cssText = "color:#aaa; font-size:13px; margin-bottom:8px;";
  promptSection.appendChild(promptLabel);

  const textarea = document.createElement("textarea");
  textarea.value = node.widgets?.find(w => w.name === "style_prompt")?.value || "";
  textarea.placeholder = "描述你想要的风格效果...";
  Object.assign(textarea.style, {
    width: "100%", minHeight: "70px", background: "#222233", border: "1px solid #3a3a4a",
    borderRadius: "8px", padding: "12px", color: "#ddd", fontSize: "14px",
    resize: "vertical", fontFamily: "inherit", boxSizing: "border-box",
    transition: "border-color 0.2s", outline: "none",
  });
  textarea.onfocus = () => textarea.style.borderColor = "#5a8abf";
  textarea.onblur = () => textarea.style.borderColor = "#3a3a4a";
  textarea.oninput = () => {
    const w = node.widgets?.find(w => w.name === "style_prompt");
    if (w) w.value = textarea.value;
  };
  promptSection.appendChild(textarea);

  // Style preset chips
  const chipsRow = document.createElement("div");
  chipsRow.style.cssText = "display:flex; flex-wrap:wrap; gap:8px; margin-top:10px;";
  for (const [name, prompt] of Object.entries(stylePresets)) {
    const chip = document.createElement("button");
    chip.textContent = name;
    Object.assign(chip.style, {
      padding: "6px 14px", background: "#2a2a3a", border: "1px solid #3a3a4a",
      borderRadius: "14px", color: "#aaa", fontSize: "12px", cursor: "pointer",
      transition: "all 0.15s",
    });
    chip.onmouseenter = () => { chip.style.background = "#3a3a4f"; chip.style.color = "#ddd"; };
    chip.onmouseleave = () => {
      if (!chip.classList.contains("sel")) { chip.style.background = "#2a2a3a"; chip.style.color = "#aaa"; }
    };
    chip.onclick = () => {
      textarea.value = prompt;
      const w = node.widgets?.find(w => w.name === "style_prompt");
      if (w) w.value = prompt;
      chipsRow.querySelectorAll("button").forEach(b => {
        b.classList.remove("sel"); b.style.borderColor = "#3a3a4a"; b.style.color = "#aaa"; b.style.background = "#2a2a3a";
      });
      chip.classList.add("sel");
      chip.style.borderColor = "#8f5a2a";
      chip.style.color = "#fff";
      chip.style.background = "#5f3a1e";
    };
    chipsRow.appendChild(chip);
  }
  promptSection.appendChild(chipsRow);
  panel.appendChild(promptSection);

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
  applyBtn.onclick = () => {
    if (textarea.value.trim()) {
      const mw = node.widgets?.find(w => w.name === "repair_mode");
      if (mw) mw.value = "风格";
    }
    node._blurUI._isCustomActive = true;
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
      // Set repair_mode to 风格
      const mw = node.widgets?.find(w => w.name === "repair_mode");
      if (mw) mw.value = "风格";
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

function getInputImageSrc(node) {
  const inputLink = node.inputs?.[0]?.link;
  if (inputLink && app.graph) {
    const linkInfo = app.graph.links[inputLink];
    if (linkInfo) {
      const srcNode = app.graph.getNodeById(linkInfo.origin_id);
      if (srcNode?.imgs?.length > 0 && srcNode.imgs[0].src) {
        return srcNode.imgs[0].src;
      }
    }
  }
  if (node.imgs?.length > 0 && node.imgs[0].src) {
    return node.imgs[0].src;
  }
  return null;
}

async function getInputImageBase64(node) {
  const inputLink = node.inputs?.[0]?.link;
  if (inputLink && app.graph) {
    const linkInfo = app.graph.links[inputLink];
    if (linkInfo) {
      const srcNode = app.graph.getNodeById(linkInfo.origin_id);
      if (srcNode?.imgs?.length > 0 && srcNode.imgs[0].src) {
        return await imgToBase64(srcNode.imgs[0].src);
      }
    }
  }
  if (node.imgs?.length > 0 && node.imgs[0].src) {
    return await imgToBase64(node.imgs[0].src);
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
  let ox = 0, oy = 0, dragging = false;
  handle.addEventListener("mousedown", (e) => {
    if (e.target.tagName === "BUTTON") return;
    dragging = true;
    const rect = el.getBoundingClientRect();
    ox = e.clientX - rect.left; oy = e.clientY - rect.top;
    handle.style.cursor = "grabbing"; e.preventDefault();
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    el.style.left = `${e.clientX - ox}px`;
    el.style.top = `${e.clientY - oy}px`;
    el.style.transform = "none";
  });
  document.addEventListener("mouseup", () => { dragging = false; handle.style.cursor = "grab"; });
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
      node._blurUI = { blurGroupY: 0, modeGroupY: 0, customBtnY: 0, drawStartY: 0, model: "", _isCustomActive: false };

      // --- Hide widgets we manage ourselves (same approach as dynamic_params.js) ---
      const widgetsToHide = ["blur_intensity", "repair_mode", "custom_sigma", "style_prompt", "seed", "control_after_generate", "生成后控制"];
      const hideWidget = (w) => {
        w.hidden = true;
        w.computeSize = () => [0, -4];
        w.type = "hidden";
        w.mouse = () => true;  // Consume clicks to prevent "Value" dialog
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

      // --- Add "▶ 开始生成" button ---
      if (!node.widgets?.find(w => w._isGenerateButton)) {
        const generateBtn = node.addWidget("button", "▶ 开始生成", null, () => {
          // Randomize seed before execution
          const seedWidget = node.widgets?.find(w => w.name === "seed");
          if (seedWidget) {
            seedWidget.value = Math.floor(Math.random() * 2147483647);
          }
          // Scoped execution: only queue this node + its upstream deps
          // so unrelated nodes with invalid configs won't block execution
          executeScopedToNode(node);
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
      }

      // --- Spacer widget to reserve space for canvas-drawn UI ---
      // Manually create widget object (NOT via addWidget) to avoid LiteGraph
      // registering it as an editable "text" widget that triggers "Value" dialog
      const spacer = {
        type: "custom",
        name: "_blur_spacer",
        value: "",
        options: {},
        last_y: 0,
        _isSpacer: true,
        serialize: false,
        computeSize: () => [0, 140],
        draw: function () {},
        mouse: function () { return true; },
        callback: function () {},
      };
      if (!node.widgets) node.widgets = [];
      node.widgets.push(spacer);

      // --- Load model info and style presets ---
      loadUpscaleModel().then(m => {
        node._blurUI.model = m;
        node.setDirtyCanvas(true);
      });
      loadStylePresets();

      // --- Ensure minimum node size ---
      const minH = 280;
      if (node.size[1] < minH) node.size[1] = minH;

      // ---- onDrawForeground ----
      const origDraw = node.onDrawForeground;
      node.onDrawForeground = function (ctx) {
        if (origDraw) origDraw.apply(this, arguments);

        const padding = 10;
        const innerW = node.size[0] - padding * 2;

        // Calculate start Y after visible widgets (skip spacer — we draw INSIDE it)
        let startY = 30;
        if (node.widgets) {
          for (const w of node.widgets) {
            if (w.type !== "hidden" && !w._isSpacer && w.last_y !== undefined) {
              const wBottom = w.last_y + (w.computeSize ? w.computeSize()[1] : 20) + 4;
              if (wBottom > startY) startY = wBottom;
            }
          }
        }
        startY += 8;
        node._blurUI.drawStartY = startY;

        // 1. Blur Intensity
        const blurVal = node.widgets?.find(w => w.name === "blur_intensity")?.value || "轻 (σ1-3)";
        node._blurUI.blurGroupY = startY;
        const h1 = drawButtonGroup(ctx, padding, startY, innerW, BLUR_PRESETS, blurVal, "模糊程度", {
          bgActive: COLORS.bgActive, borderActive: COLORS.borderActive,
          text: COLORS.text, textActive: COLORS.textActive,
        });
        startY += h1;

        // 2. Repair Mode
        const modeVal = node.widgets?.find(w => w.name === "repair_mode")?.value || "直出";
        node._blurUI.modeGroupY = startY;
        const h2 = drawButtonGroup(ctx, padding, startY, innerW, REPAIR_MODES, modeVal, "修复模式", {
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
        startY += 20;

        // Dynamically update spacer height to match actual custom UI height
        // This pushes ComfyUI's image preview below our canvas-drawn buttons
        const uiHeight = startY - node._blurUI.drawStartY + 10;
        spacer.computeSize = () => [0, uiHeight];

        if (startY + 10 > node.size[1]) node.size[1] = startY + 10;
      };

      // ---- onMouseDown ----
      const origMouseDown = node.onMouseDown;
      node.onMouseDown = function (e, localPos, canvas) {
        if (origMouseDown) {
          const result = origMouseDown.apply(this, arguments);
          if (result) return result;
        }

        const padding = 10;
        const innerW = node.size[0] - padding * 2;
        const [clickX, clickY] = localPos;
        const ui = node._blurUI;
        if (!ui) return false;

        // Blur intensity buttons
        const blurHit = hitTestButtonGroup(padding, 0, innerW, BLUR_PRESETS, clickX, clickY, ui.blurGroupY);
        if (blurHit) {
          const w = node.widgets?.find(w => w.name === "blur_intensity");
          if (w) { w.value = blurHit; w.callback?.(blurHit); }
          node._blurUI._isCustomActive = false;
          node.setDirtyCanvas(true, true);
          return true;
        }

        // Repair mode buttons
        const modeHit = hitTestButtonGroup(padding, 0, innerW, REPAIR_MODES, clickX, clickY, ui.modeGroupY);
        if (modeHit) {
          if (modeHit === "风格") {
            // Show style preset popup at mouse position
            openStylePopup(node, e.clientX, e.clientY);
          } else {
            const w = node.widgets?.find(w => w.name === "repair_mode");
            if (w) { w.value = modeHit; w.callback?.(modeHit); }
            node._blurUI._isCustomActive = false;
          }
          node.setDirtyCanvas(true, true);
          return true;
        }

        // Custom settings button
        if (hitTestRect(padding, ui.customBtnY, innerW, 30, clickX, clickY)) {
          openCustomPanel(node);
          return true;
        }

        // Consume all clicks within the custom UI area to prevent
        // LiteGraph from opening the "Value" edit dialog on the spacer widget
        if (ui.drawStartY && clickY >= ui.drawStartY) {
          return true;
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
      };
    };
  },
});


// ================================================================
// SECTION 6: HELPERS
// ================================================================

async function loadUpscaleModel() {
  try {
    const resp = await api.fetchApi("/api/batchbox/upscale-settings");
    if (resp.ok) {
      const data = await resp.json();
      return data.upscale_settings?.model || "";
    }
  } catch (e) { console.warn("[BlurUpscale] Could not load upscale settings:", e); }
  return "";
}


console.log("[ComfyUI-Custom-Batchbox] Gaussian Blur Upscale extension loaded");
