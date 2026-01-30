/**
 * @fileoverview Custom Image Panel V2 for ComfyUI-Custom-Batchbox
 * 
 * Uses DOM overlay approach to create custom UI elements that properly
 * overlay on top of LiteGraph nodes. This solves the z-order issues
 * with canvas-based drawing.
 * 
 * Features:
 * - Custom prompt textarea
 * - Horizontal toolbar (model, resolution, batch, settings, generate)
 * - Advanced settings panel
 * - Thumbnail gallery
 */

import { app } from "../../scripts/app.js";

// ================================================================
// SECTION 1: THEME CONFIGURATION
// ================================================================

const THEME = {
  // Colors
  bgPrimary: "#1e1e2e",
  bgSecondary: "#181825",
  bgTertiary: "#313244",
  accent: "#4CAF50",
  accentHover: "#66BB6A",
  text: "#cdd6f4",
  textMuted: "#6c7086",
  border: "rgba(255,255,255,0.1)",
  
  // Sizing
  toolbarHeight: 44,
  buttonHeight: 32,
  buttonRadius: 6,
  promptHeight: 100,
  padding: 10,
  
  // Typography
  fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  fontSize: 13,
};

// ================================================================
// SECTION 2: DOM OVERLAY CONTAINER
// ================================================================

let overlayContainer = null;

function getOverlayContainer() {
  if (!overlayContainer) {
    overlayContainer = document.createElement("div");
    overlayContainer.id = "batchbox-overlay-container";
    overlayContainer.style.cssText = `
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 100;
    `;
    document.body.appendChild(overlayContainer);
  }
  return overlayContainer;
}

// ================================================================
// SECTION 3: NODE OVERLAY CLASS
// ================================================================

class NodeOverlay {
  constructor(node) {
    this.node = node;
    this.container = null;
    this.promptInput = null;
    this.toolbar = null;
    this.advancedPanel = null;
    this.isAdvancedOpen = false;
    
    this.createElements();
    this.attachToCanvas();
    this.updatePosition();
  }
  
  createElements() {
    // Main container
    this.container = document.createElement("div");
    this.container.className = "batchbox-node-overlay";
    this.container.style.cssText = `
      position: absolute;
      pointer-events: auto;
      font-family: ${THEME.fontFamily};
      font-size: ${THEME.fontSize}px;
      color: ${THEME.text};
    `;
    
    // Image preview area
    this.imagePreview = document.createElement("div");
    this.imagePreview.className = "batchbox-image-preview";
    this.imagePreview.style.cssText = `
      width: 100%;
      height: 200px;
      background: ${THEME.bgSecondary};
      border: 1px solid ${THEME.border};
      border-radius: ${THEME.buttonRadius}px;
      margin-bottom: ${THEME.padding}px;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      position: relative;
    `;
    this.imagePreview.innerHTML = `
      <span style="color: ${THEME.textMuted}; font-size: 12px;">图片预览区</span>
    `;
    
    // Actual image element (hidden initially)
    this.previewImg = document.createElement("img");
    this.previewImg.style.cssText = `
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      display: none;
    `;
    this.imagePreview.appendChild(this.previewImg);
    
    // Thumbnail gallery for multiple images
    this.thumbnailGallery = document.createElement("div");
    this.thumbnailGallery.className = "batchbox-thumbnails";
    this.thumbnailGallery.style.cssText = `
      display: none;
      flex-wrap: nowrap;
      gap: 6px;
      padding: 6px;
      background: ${THEME.bgSecondary};
      border-radius: ${THEME.buttonRadius}px;
      border: 1px solid ${THEME.border};
      margin-bottom: ${THEME.padding}px;
      overflow-x: auto;
      max-height: 70px;
    `;
    
    // Prompt textarea
    this.promptInput = document.createElement("textarea");
    this.promptInput.className = "batchbox-prompt";
    this.promptInput.placeholder = "输入提示词...";
    this.promptInput.style.cssText = `
      width: 100%;
      height: ${THEME.promptHeight}px;
      padding: 10px;
      background: ${THEME.bgSecondary};
      border: 1px solid ${THEME.border};
      border-radius: ${THEME.buttonRadius}px;
      color: ${THEME.text};
      font-family: ${THEME.fontFamily};
      font-size: ${THEME.fontSize}px;
      resize: vertical;
      box-sizing: border-box;
      margin-bottom: ${THEME.padding}px;
    `;
    this.promptInput.addEventListener("input", () => this.syncPromptToWidget());
    
    // Toolbar
    this.toolbar = this.createToolbar();
    
    // Advanced panel (initially hidden)
    this.advancedPanel = this.createAdvancedPanel();
    
    // Assemble
    this.container.appendChild(this.imagePreview);
    this.container.appendChild(this.thumbnailGallery);
    this.container.appendChild(this.promptInput);
    this.container.appendChild(this.toolbar);
    this.container.appendChild(this.advancedPanel);
    
    getOverlayContainer().appendChild(this.container);
    
    // Start watching for image updates
    this.startImageWatcher();
  }
  
  createToolbar() {
    const toolbar = document.createElement("div");
    toolbar.className = "batchbox-toolbar";
    toolbar.style.cssText = `
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 6px;
      background: ${THEME.bgSecondary};
      border-radius: ${THEME.buttonRadius}px;
      border: 1px solid ${THEME.border};
    `;
    
    // Main row: model, style, resolution, ratio, batch, generate
    const mainRow = document.createElement("div");
    mainRow.style.cssText = `
      display: flex;
      gap: 6px;
    `;
    
    const mainButtons = [
      { id: "model", icon: "🍌", label: "Model", onClick: () => this.onModelClick() },
      { id: "style", icon: "🎨", label: "风格", onClick: () => this.onStyleClick() },
      { id: "resolution", icon: "📐", label: "分辨率", onClick: () => this.onResolutionClick() },
      { id: "ratio", icon: "📏", label: "比例", onClick: () => this.onRatioClick() },
      { id: "batch", icon: "🔢", label: "1x", onClick: () => this.onBatchClick() },
      { id: "generate", icon: "▶", label: "生成", isAccent: true, onClick: () => this.onGenerateClick() },
    ];
    
    mainButtons.forEach(btn => {
      const button = this.createButton(btn);
      mainRow.appendChild(button);
    });
    
    // Settings row: full width 高级设置 button
    const settingsBtn = this.createButton({
      id: "settings",
      icon: "⚙️",
      label: "高级设置",
      isFullWidth: true,
      onClick: () => this.toggleAdvanced()
    });
    
    toolbar.appendChild(mainRow);
    toolbar.appendChild(settingsBtn);
    
    return toolbar;
  }
  
  createButton(btn) {
    const button = document.createElement("button");
    button.className = `batchbox-btn ${btn.isAccent ? 'accent' : ''}`;
    button.dataset.id = btn.id;
    button.innerHTML = `${btn.icon} ${btn.label}`;
    button.style.cssText = `
      flex: ${btn.isFullWidth ? '1 1 100%' : btn.isAccent ? '0 0 auto' : '1'};
      padding: 8px 12px;
      border: none;
      border-radius: ${THEME.buttonRadius}px;
      background: ${btn.isAccent ? THEME.accent : THEME.bgTertiary};
      color: ${THEME.text};
      font-family: ${THEME.fontFamily};
      font-size: ${THEME.fontSize}px;
      cursor: pointer;
      transition: background 0.2s;
      ${btn.isFullWidth ? 'width: 100%;' : ''}
    `;
    button.addEventListener("click", btn.onClick);
    button.addEventListener("mouseenter", () => {
      button.style.background = btn.isAccent ? THEME.accentHover : "#45475a";
    });
    button.addEventListener("mouseleave", () => {
      button.style.background = btn.isAccent ? THEME.accent : THEME.bgTertiary;
    });
    return button;
  }
  
  createAdvancedPanel() {
    const panel = document.createElement("div");
    panel.className = "batchbox-advanced";
    panel.style.cssText = `
      display: none;
      margin-top: ${THEME.padding}px;
      padding: 10px;
      background: ${THEME.bgSecondary};
      border-radius: ${THEME.buttonRadius}px;
      border: 1px solid ${THEME.border};
    `;
    panel.innerHTML = `<div style="color: ${THEME.textMuted}; text-align: center;">高级设置 (开发中)</div>`;
    return panel;
  }
  
  toggleAdvanced() {
    this.isAdvancedOpen = !this.isAdvancedOpen;
    this.advancedPanel.style.display = this.isAdvancedOpen ? "block" : "none";
    // Update button label
    const btn = this.toolbar.querySelector('[data-id="settings"]');
    if (btn) {
      btn.innerHTML = `⚙️ ${this.isAdvancedOpen ? "收起" : "设置"}`;
    }
  }
  
  // Sync prompt to hidden widget
  syncPromptToWidget() {
    const promptWidget = this.node.widgets?.find(w => w.name === "prompt");
    if (promptWidget) {
      promptWidget.value = this.promptInput.value;
    }
  }
  
  // Sync from widget to textarea
  syncFromWidget() {
    const promptWidget = this.node.widgets?.find(w => w.name === "prompt");
    if (promptWidget && promptWidget.value !== this.promptInput.value) {
      this.promptInput.value = promptWidget.value || "";
    }
  }
  
  // Button handlers
  onModelClick() {
    // Find model widget and show its options
    const modelWidget = this.node.widgets?.find(w => w.name === "model" || w.name === "preset");
    if (modelWidget && modelWidget.options?.values) {
      const values = modelWidget.options.values;
      const currentIdx = values.indexOf(modelWidget.value);
      const nextIdx = (currentIdx + 1) % values.length;
      modelWidget.value = values[nextIdx];
      this.updateButtonLabels();
    }
  }
  
  onStyleClick() {
    // Find style widget from dynamic params
    const styleWidget = this.findDynamicWidget("style") || 
                       this.node.widgets?.find(w => w.name?.includes("风格"));
    if (styleWidget && styleWidget.options?.values) {
      const values = styleWidget.options.values;
      const currentIdx = values.indexOf(styleWidget.value);
      const nextIdx = (currentIdx + 1) % values.length;
      styleWidget.value = values[nextIdx];
      this.updateButtonLabels();
    }
  }
  
  onResolutionClick() {
    // Find resolution widget from dynamic params
    const resWidget = this.findDynamicWidget("resolution") ||
                      this.node.widgets?.find(w => w.name?.includes("分辨率"));
    if (resWidget && resWidget.options?.values) {
      const values = resWidget.options.values;
      const currentIdx = values.indexOf(resWidget.value);
      const nextIdx = (currentIdx + 1) % values.length;
      resWidget.value = values[nextIdx];
      this.updateButtonLabels();
    }
  }
  
  onRatioClick() {
    // Find ratio/aspect widget from dynamic params
    const ratioWidget = this.findDynamicWidget("ratio") ||
                        this.findDynamicWidget("aspect") ||
                        this.node.widgets?.find(w => w.name?.includes("比例"));
    if (ratioWidget && ratioWidget.options?.values) {
      const values = ratioWidget.options.values;
      const currentIdx = values.indexOf(ratioWidget.value);
      const nextIdx = (currentIdx + 1) % values.length;
      ratioWidget.value = values[nextIdx];
      this.updateButtonLabels();
    }
  }
  
  findDynamicWidget(apiNamePattern) {
    return this.node._dynamicParamManager?.dynamicWidgets?.find(
      w => w._paramDef?.api_name?.toLowerCase().includes(apiNamePattern)
    );
  }
  
  onBatchClick() {
    const batchWidget = this.node.widgets?.find(w => w.name === "batch_count");
    if (batchWidget) {
      const current = batchWidget.value || 1;
      batchWidget.value = current >= 8 ? 1 : current + 1;
      this.updateButtonLabels();
    }
  }
  
  onGenerateClick() {
    const generateBtn = this.node.widgets?.find(w => w._isGenerateButton);
    if (generateBtn && generateBtn.callback) {
      // Record current image URL to detect when a NEW image arrives
      this._imageUrlBeforeGenerate = this.previewImg.src || "";
      // Start loading animation
      this.setGeneratingState(true);
      generateBtn.callback();
    }
  }
  
  setGeneratingState(isGenerating) {
    const generateBtnEl = this.toolbar.querySelector('[data-id="generate"]');
    
    if (isGenerating) {
      this._isGenerating = true;
      
      // Update generate button with spinner
      if (generateBtnEl) {
        generateBtnEl.innerHTML = `
          <span class="spinner" style="
            display: inline-block;
            width: 14px;
            height: 14px;
            border: 2px solid rgba(255,255,255,0.3);
            border-top-color: white;
            border-radius: 50%;
            animation: spin 1s linear infinite;
          "></span> 生成中`;
        generateBtnEl.style.pointerEvents = "none";
        generateBtnEl.style.opacity = "0.7";
      }
      
      // Add scanning animation to image preview
      this.imagePreview.style.position = "relative";
      this.imagePreview.style.overflow = "hidden";
      
      // Create scan line
      if (!this._scanLine) {
        this._scanLine = document.createElement("div");
        this._scanLine.style.cssText = `
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          height: 4px;
          background: linear-gradient(90deg, transparent, ${THEME.accent}, transparent);
          animation: scanDown 2s ease-in-out infinite;
        `;
        this.imagePreview.appendChild(this._scanLine);
      }
      
      // Add CSS animation keyframes if not exists
      if (!document.getElementById("batchbox-animations")) {
        const style = document.createElement("style");
        style.id = "batchbox-animations";
        style.textContent = `
          @keyframes spin {
            to { transform: rotate(360deg); }
          }
          @keyframes scanDown {
            0%, 100% { top: 0; opacity: 0; }
            10% { opacity: 1; }
            90% { opacity: 1; }
            100% { top: calc(100% - 4px); opacity: 0; }
          }
        `;
        document.head.appendChild(style);
      }
      
      // Auto-stop after timeout
      this._generateTimeout = setTimeout(() => this.setGeneratingState(false), 30000);
      
    } else {
      this._isGenerating = false;
      
      // Restore generate button
      if (generateBtnEl) {
        generateBtnEl.innerHTML = "▶ 生成";
        generateBtnEl.style.pointerEvents = "auto";
        generateBtnEl.style.opacity = "1";
      }
      
      // Remove scan line
      if (this._scanLine && this._scanLine.parentNode) {
        this._scanLine.parentNode.removeChild(this._scanLine);
        this._scanLine = null;
      }
      
      if (this._generateTimeout) {
        clearTimeout(this._generateTimeout);
        this._generateTimeout = null;
      }
    }
  }
  
  // Position overlay to match node
  updatePosition() {
    if (!this.container || !this.node) return;
    
    const canvas = app.canvas;
    if (!canvas) return;
    
    // Get node position in screen coordinates
    const scale = canvas.ds?.scale || 1;
    const offset = canvas.ds?.offset || [0, 0];
    
    const nodeX = (this.node.pos[0] + offset[0]) * scale;
    const nodeY = (this.node.pos[1] + offset[1]) * scale;
    
    // Add title height offset (LiteGraph title is about 30px)
    const titleHeight = (LiteGraph.NODE_TITLE_HEIGHT || 30) * scale;
    
    // Use fixed base width - scale will be applied via CSS transform
    const baseWidth = 380;
    
    // Position at scaled coordinates
    this.container.style.left = `${nodeX + 10 * scale}px`;
    this.container.style.top = `${nodeY + titleHeight + 40 * scale}px`;
    
    // Set base width (before scaling)
    this.container.style.width = `${baseWidth}px`;
    
    // Apply scale transform for proportional scaling
    this.container.style.transform = `scale(${scale})`;
    this.container.style.transformOrigin = "top left";
  }
  
  attachToCanvas() {
    // Update position on canvas changes
    const updatePos = () => this.updatePosition();
    
    // Hook into LiteGraph events
    const origOnMouse = this.node.onMouseMove;
    this.node.onMouseMove = function() {
      updatePos();
      if (origOnMouse) origOnMouse.apply(this, arguments);
    };
    
    // Also update on draw
    const origDraw = this.node.onDrawForeground;
    this.node.onDrawForeground = function(ctx) {
      if (origDraw) origDraw.call(this, ctx);
      updatePos();
    };
    
    // Global canvas events for zoom/pan
    const canvasEl = document.querySelector("canvas.graphcanvas") || 
                     document.querySelector("#graph-canvas") ||
                     document.querySelector("canvas");
    if (canvasEl) {
      canvasEl.addEventListener("wheel", updatePos);
      canvasEl.addEventListener("mousemove", updatePos);
    }
    
    // Use requestAnimationFrame for smooth updates
    let lastScale = 0;
    let lastOffsetX = 0;
    let lastOffsetY = 0;
    
    const checkForChanges = () => {
      if (!this.container) return; // Stop if destroyed
      
      const canvas = app.canvas;
      if (canvas && canvas.ds) {
        const currentScale = canvas.ds.scale || 1;
        const currentOffsetX = canvas.ds.offset?.[0] || 0;
        const currentOffsetY = canvas.ds.offset?.[1] || 0;
        
        // Only update if something changed
        if (currentScale !== lastScale || 
            currentOffsetX !== lastOffsetX || 
            currentOffsetY !== lastOffsetY) {
          lastScale = currentScale;
          lastOffsetX = currentOffsetX;
          lastOffsetY = currentOffsetY;
          updatePos();
        }
      }
      
      requestAnimationFrame(checkForChanges);
    };
    
    requestAnimationFrame(checkForChanges);
  }
  
  updateButtonLabels() {
    const truncate = (str, len) => str?.length > len ? str.slice(0, len) + "..." : str;
    
    // Model
    const modelWidget = this.node.widgets?.find(w => w.name === "model" || w.name === "preset");
    const modelBtn = this.toolbar.querySelector('[data-id="model"]');
    if (modelBtn && modelWidget) {
      modelBtn.innerHTML = `🍌 ${truncate(modelWidget.value, 10) || "Model"}`;
    }
    
    // Style
    const styleWidget = this.findDynamicWidget("style") || 
                        this.node.widgets?.find(w => w.name?.includes("风格"));
    const styleBtn = this.toolbar.querySelector('[data-id="style"]');
    if (styleBtn && styleWidget) {
      styleBtn.innerHTML = `🎨 ${truncate(styleWidget.value, 8) || "风格"}`;
    }
    
    // Resolution
    const resWidget = this.findDynamicWidget("resolution") ||
                      this.node.widgets?.find(w => w.name?.includes("分辨率"));
    const resBtn = this.toolbar.querySelector('[data-id="resolution"]');
    if (resBtn && resWidget) {
      resBtn.innerHTML = `📐 ${truncate(resWidget.value, 6) || "分辨率"}`;
    }
    
    // Ratio
    const ratioWidget = this.findDynamicWidget("ratio") ||
                        this.findDynamicWidget("aspect") ||
                        this.node.widgets?.find(w => w.name?.includes("比例"));
    const ratioBtn = this.toolbar.querySelector('[data-id="ratio"]');
    if (ratioBtn && ratioWidget) {
      ratioBtn.innerHTML = `📏 ${truncate(ratioWidget.value, 6) || "比例"}`;
    }
    
    // Batch
    const batchWidget = this.node.widgets?.find(w => w.name === "batch_count");
    const batchBtn = this.toolbar.querySelector('[data-id="batch"]');
    if (batchBtn) {
      batchBtn.innerHTML = `🔢 ${batchWidget?.value || 1}x`;
    }
  }
  
  startImageWatcher() {
    // Watch for image updates on the node
    this._imageWatchInterval = setInterval(() => {
      this.updateImagePreview();
    }, 500);
    
    // Initial check
    this.updateImagePreview();
  }
  
  updateImagePreview() {
    // Primary source: node.imgs (HTMLImageElement array, set by updateNodePreview after loading)
    // Secondary source: node.images (filename objects array, set immediately after generation)
    
    // Use node.imgs first (actual loaded images), fall back to node.images (filename objects)
    const cachedImages = this.node.imgs || this.node.images;
    const selectedIdx = this.node._selectedImageIndex || this.node.imageIndex || 0;
    
    // Detect if the image array itself changed (new generation)
    const arrayChanged = cachedImages !== this._lastCachedImages;
    if (arrayChanged && cachedImages) {
      this._lastCachedImages = cachedImages;
      this._lastThumbnailCount = 0; // Force gallery rebuild
      console.log("[NodeOverlay] Image array changed, count:", cachedImages.length);
    }
    
    if (cachedImages && cachedImages.length > 0) {
      const image = cachedImages[selectedIdx] || cachedImages[0];
      
      // Check if it's a URL or needs to be loaded
      let imageUrl = null;
      if (typeof image === "string") {
        imageUrl = image;
      } else if (image.src) {
        // HTMLImageElement
        imageUrl = image.src;
      } else if (image.url) {
        imageUrl = image.url;
      } else if (image.filename) {
        // Build URL from ComfyUI output path
        imageUrl = `/view?filename=${encodeURIComponent(image.filename)}&type=${image.type || "output"}&subfolder=${encodeURIComponent(image.subfolder || "")}`;
      }
      
      // Update main preview if URL changed OR if array changed
      if (imageUrl && (arrayChanged || this.previewImg.src !== imageUrl)) {
        this.previewImg.src = imageUrl;
        this.previewImg.style.display = "block";
        
        // Hide placeholder
        const placeholder = this.imagePreview.querySelector("span");
        if (placeholder) placeholder.style.display = "none";
        
        // Stop loading animation only when a NEW image (different from before) appears
        if (this._isGenerating && imageUrl !== this._imageUrlBeforeGenerate) {
          this.setGeneratingState(false);
        }
      }
      
      // Update thumbnail gallery if multiple images
      this.updateThumbnailGallery(cachedImages, selectedIdx);
    }
    
    // Also check for last_image_url from node outputs
    if (this.node._lastImageUrl) {
      if (this.previewImg.src !== this.node._lastImageUrl) {
        this.previewImg.src = this.node._lastImageUrl;
        this.previewImg.style.display = "block";
        
        const placeholder = this.imagePreview.querySelector("span");
        if (placeholder) placeholder.style.display = "none";
      }
    }
  }
  
  updateThumbnailGallery(images, selectedIdx) {
    if (!images || images.length <= 1) {
      this.thumbnailGallery.style.display = "none";
      return;
    }
    
    // Show gallery
    this.thumbnailGallery.style.display = "flex";
    
    // Only rebuild if image count changed
    if (this._lastThumbnailCount === images.length) return;
    this._lastThumbnailCount = images.length;
    
    // Clear existing thumbnails
    this.thumbnailGallery.innerHTML = "";
    
    images.forEach((image, idx) => {
      let imageUrl = null;
      if (typeof image === "string") {
        imageUrl = image;
      } else if (image.src) {
        imageUrl = image.src;
      } else if (image.url) {
        imageUrl = image.url;
      } else if (image.filename) {
        imageUrl = `/view?filename=${encodeURIComponent(image.filename)}&type=temp&subfolder=${encodeURIComponent(image.subfolder || "")}`;
      }
      
      if (!imageUrl) return;
      
      const thumb = document.createElement("img");
      thumb.src = imageUrl;
      thumb.style.cssText = `
        height: 50px;
        width: 50px;
        object-fit: cover;
        border-radius: 4px;
        cursor: pointer;
        border: 2px solid ${idx === selectedIdx ? THEME.accent : "transparent"};
        transition: border-color 0.2s;
        flex-shrink: 0;
      `;
      
      thumb.addEventListener("click", () => {
        this.node._selectedImageIndex = idx;
        this.previewImg.src = imageUrl;
        
        // Update border on all thumbnails
        this.thumbnailGallery.querySelectorAll("img").forEach((t, i) => {
          t.style.borderColor = i === idx ? THEME.accent : "transparent";
        });
      });
      
      thumb.addEventListener("mouseenter", () => {
        if (idx !== selectedIdx) thumb.style.borderColor = THEME.border;
      });
      
      thumb.addEventListener("mouseleave", () => {
        thumb.style.borderColor = idx === (this.node._selectedImageIndex || 0) ? THEME.accent : "transparent";
      });
      
      this.thumbnailGallery.appendChild(thumb);
    });
  }
  
  destroy() {
    if (this._imageWatchInterval) {
      clearInterval(this._imageWatchInterval);
    }
    if (this.container && this.container.parentNode) {
      this.container.parentNode.removeChild(this.container);
    }
  }
}

// ================================================================
// SECTION 4: NODE SETUP
// ================================================================

const nodeOverlays = new Map();

export function setupCustomPanel(node) {
  // Hide ALL original widgets
  setTimeout(() => {
    if (node.widgets) {
      node.widgets.forEach(w => {
        w.hidden = true;
      });
      
      // Minimize node size since widgets are hidden
      node.size = [400, 80]; // Just title and I/O ports
      node.setDirtyCanvas(true, true);
    }
  }, 300);
  
  // Create overlay after widgets are hidden
  setTimeout(() => {
    const overlay = new NodeOverlay(node);
    nodeOverlays.set(node.id, overlay);
    
    // Update labels from widgets
    overlay.updateButtonLabels();
    overlay.syncFromWidget();
    
    console.log("[ImagePanel] DOM overlay created for node:", node.id);
  }, 500);
  
  // Clean up on node removal
  const origOnRemoved = node.onRemoved;
  node.onRemoved = function() {
    const overlay = nodeOverlays.get(this.id);
    if (overlay) {
      overlay.destroy();
      nodeOverlays.delete(this.id);
    }
    if (origOnRemoved) origOnRemoved.call(this);
  };
  
  node._customPanelInitialized = true;
}

// Update all overlays on canvas transform
if (typeof app !== "undefined" && app.canvas) {
  const origOnPan = app.canvas.onPan;
  app.canvas.onPan = function() {
    if (origOnPan) origOnPan.apply(this, arguments);
    nodeOverlays.forEach(overlay => overlay.updatePosition());
  };
  
  const origOnZoom = app.canvas.onZoom;
  app.canvas.onZoom = function() {
    if (origOnZoom) origOnZoom.apply(this, arguments);
    nodeOverlays.forEach(overlay => overlay.updatePosition());
  };
}
