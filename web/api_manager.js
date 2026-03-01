/**
 * @fileoverview Batchbox API Manager
 * 
 * UI for managing API providers and model configurations.
 * 
 * TABLE OF CONTENTS:
 * ------------------
 * 1. UTILITIES (Line ~25)
 *    - injectCSS()
 * 
 * 2. BATCHBOX MANAGER CLASS (Line ~40)
 *    - Core: open(), loadConfig(), saveConfig(), showToast()
 *    - Modal: renderModal(), closeModal(), switchTab()
 *    - Providers: renderProviders(), showProviderForm()
 *    - Models: renderModels(), showModelForm()
 *    - Raw JSON: renderRaw()
 *    - Dialogs: confirmDelete(), showConfirmModal(), showFormModal()
 * 
 * 3. COMFYUI EXTENSION REGISTRATION (Line ~1400)
 * 
 * @author ComfyUI-Custom-Batchbox
 * @version 1.0.0
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ================================================================
// SECTION 1: UTILITIES
// ================================================================

/**
 * Inject the API Manager CSS stylesheet into the document head.
 * Uses import.meta.url to compute the correct absolute path,
 * ensuring it works regardless of how ComfyUI is accessed (reverse proxy, subpath, etc.).
 * Prevents duplicate injection by checking for a unique element ID.
 */
function injectCSS() {
    if (document.getElementById("batchbox-api-manager-css")) return;
    const link = document.createElement("link");
    link.id = "batchbox-api-manager-css";
    link.rel = "stylesheet";
    link.type = "text/css";
    link.href = new URL("api_manager.css", import.meta.url).href;
    document.head.appendChild(link);
}

// ================================================================
// SECTION 2: BATCHBOX MANAGER CLASS
// ================================================================

class BatchboxManager {
    constructor() {
        this.config = null;
        injectCSS();
    }

    async open() {
        await this.loadConfig();
        this.renderModal();
    }

    async loadConfig() {
        try {
            const resp = await api.fetchApi("/api/batchbox/config");
            if (resp.status !== 200) throw new Error("Failed to load config");
            this.config = await resp.json();
        } catch (e) {
            this.showToast("加载配置失败: " + e.message, "error");
            this.config = { providers: {}, presets: {} };
        }
    }

    async saveConfig() {
        try {
            const resp = await api.fetchApi("/api/batchbox/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(this.config)
            });
            if (resp.status !== 200) throw new Error("Save failed");

            // Trigger backend reload to update mtime
            await api.fetchApi("/api/batchbox/reload", { method: "POST" });

            // Dispatch event to notify canvas nodes to refresh
            window.dispatchEvent(new CustomEvent("batchbox:config-changed"));

            this.showToast("配置已保存！画布节点将自动刷新。", "success");
        } catch (e) {
            this.showToast("保存失败: " + e.message, "error");
        }
    }

    showToast(message, type = "info") {
        const existing = document.querySelector(".batchbox-toast");
        if (existing) existing.remove();

        const toast = document.createElement("div");
        toast.className = `batchbox-toast toast-${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => toast.classList.add("show"), 10);
        setTimeout(() => {
            toast.classList.remove("show");
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    renderModal() {
        this.closeModal();

        this.modalOverlay = document.createElement("div");
        this.modalOverlay.className = "batchbox-modal-overlay";

        const modal = document.createElement("div");
        modal.className = "batchbox-modal";
        this.modalOverlay.appendChild(modal);

        // Header
        const header = document.createElement("div");
        header.className = "batchbox-header";
        header.innerHTML = `<h2>🍌 Batchbox API Manager</h2>`;
        const closeBtn = document.createElement("button");
        closeBtn.className = "batchbox-close-btn";
        closeBtn.innerHTML = "&times;";
        closeBtn.onclick = () => this.closeModal();
        header.appendChild(closeBtn);
        modal.appendChild(header);

        // Content
        const content = document.createElement("div");
        content.className = "batchbox-content";
        modal.appendChild(content);

        // Sidebar
        const sidebar = document.createElement("div");
        sidebar.className = "batchbox-sidebar";
        content.appendChild(sidebar);

        ["供应商 Providers", "模型 Models", "保存设置 Save", "原始 JSON", "Account 服务"].forEach((label, i) => {
            const btn = document.createElement("button");
            btn.className = `batchbox-tab-btn ${i === 0 ? "active" : ""}`;
            btn.innerText = label;
            btn.onclick = () => this.switchTab(["providers", "models", "save", "raw", "account"][i]);
            sidebar.appendChild(btn);
        });

        // Panels
        this.panels = {};
        ["providers", "models", "save", "raw", "account"].forEach((name, i) => {
            const panel = document.createElement("div");
            panel.className = `batchbox-panel ${i === 0 ? "active" : ""}`;
            this.panels[name] = panel;
            content.appendChild(panel);
        });

        this.renderProviders(this.panels["providers"]);
        this.renderModels(this.panels["models"]);
        this.renderSaveSettings(this.panels["save"]);
        this.renderRaw(this.panels["raw"]);
        this.renderAccountTab(this.panels["account"]);

        // Footer
        const footer = document.createElement("div");
        footer.className = "batchbox-footer";

        // Refresh button
        const refreshBtn = document.createElement("button");
        refreshBtn.className = "batchbox-btn btn-secondary";
        refreshBtn.innerText = "🔄 刷新配置";
        refreshBtn.onclick = async () => {
            refreshBtn.disabled = true;
            refreshBtn.innerText = "⏳ 重新加载...";
            try {
                await api.fetchApi("/api/batchbox/reload", { method: "POST" });
                await this.loadConfig();
                this.renderProviders(this.panels["providers"]);
                this.renderModels(this.panels["models"]);
                this.renderRaw(this.panels["raw"]);
                this.showToast("配置已刷新！", "success");
            } catch (e) {
                this.showToast("刷新失败: " + e.message, "error");
            }
            refreshBtn.disabled = false;
            refreshBtn.innerText = "🔄 刷新配置";
        };
        footer.appendChild(refreshBtn);

        const saveBtn = document.createElement("button");
        saveBtn.className = "batchbox-btn btn-primary";
        saveBtn.innerText = "💾 保存所有更改";
        saveBtn.onclick = () => this.saveConfig();
        footer.appendChild(saveBtn);
        modal.appendChild(footer);

        document.body.appendChild(this.modalOverlay);
    }

    closeModal() {
        if (this.modalOverlay) {
            this.modalOverlay.remove();
            this.modalOverlay = null;
        }
    }

    switchTab(tabName) {
        const tabs = this.modalOverlay.querySelectorAll(".batchbox-tab-btn");
        tabs.forEach((t, i) => {
            t.classList.toggle("active", ["providers", "models", "save", "raw", "account"][i] === tabName);
        });
        Object.entries(this.panels).forEach(([name, panel]) => {
            panel.classList.toggle("active", name === tabName);
        });
        if (tabName === "raw") this.renderRaw(this.panels["raw"]);
        if (tabName === "models") this.renderModels(this.panels["models"]);
        if (tabName === "save") this.renderSaveSettings(this.panels["save"]);
        if (tabName === "account") this.renderAccountTab(this.panels["account"]);
    }

    // ================================================================
    // 2.0 ACCOUNT SERVICE
    // ================================================================

    /**
     * Render the Account service management tab.
     * Login/logout, credits display, redeem codes.
     */
    async renderAccountTab(container) {
        container.innerHTML = "";

        // Header
        const header = document.createElement("div");
        header.className = "batchbox-panel-header";
        header.innerHTML = `<h3>🔑 Account 服务</h3>`;
        container.appendChild(header);

        // Status card
        const statusCard = document.createElement("div");
        statusCard.className = "batchbox-account-card";
        statusCard.style.cssText = `
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
        `;
        statusCard.innerHTML = `
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px;">
                <div class="account-avatar" style="width: 48px; height: 48px; border-radius: 50%; background: #333; display: flex; align-items: center; justify-content: center; font-size: 24px;">👤</div>
                <div>
                    <div class="account-nickname" style="font-size: 16px; font-weight: 600; color: #e0e0e0;">加载中...</div>
                    <div class="account-status-text" style="font-size: 12px; color: #888; margin-top: 2px;">正在获取状态</div>
                </div>
            </div>
            <div class="account-credits-row" style="display: none; background: #0d1117; border-radius: 8px; padding: 14px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div style="font-size: 11px; color: #888; margin-bottom: 4px;">可用积分</div>
                        <div class="account-credits-value" style="font-size: 28px; font-weight: 700; color: #58a6ff;">--</div>
                    </div>
                    <button class="batchbox-btn btn-secondary btn-refresh-credits" style="padding: 6px 12px; font-size: 12px;">🔄 刷新</button>
                </div>
            </div>
            <div class="account-actions" style="display: flex; gap: 10px;"></div>
        `;
        container.appendChild(statusCard);

        // Redeem code section
        const redeemSection = document.createElement("div");
        redeemSection.className = "batchbox-account-redeem";
        redeemSection.style.cssText = `
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 20px;
            display: none;
        `;
        redeemSection.innerHTML = `
            <h4 style="margin: 0 0 12px; color: #e0e0e0; font-size: 14px;">🎁 兑换冰糕</h4>
            <div style="display: flex; gap: 10px;">
                <input type="text" class="redeem-code-input batchbox-form-input" placeholder="输入兑换密钥" style="flex: 1; padding: 10px;">
                <button class="batchbox-btn btn-primary btn-redeem" style="padding: 10px 20px; white-space: nowrap;">兑换</button>
            </div>
            <div class="redeem-result" style="margin-top: 8px; font-size: 12px; display: none;"></div>
        `;
        container.appendChild(redeemSection);

        // Purchase section (获取冰糕)
        const purchaseSection = document.createElement("div");
        purchaseSection.className = "batchbox-account-purchase";
        purchaseSection.style.cssText = `
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 20px;
            margin-top: 12px;
            display: none;
        `;
        purchaseSection.innerHTML = `
            <h4 style="margin: 0 0 12px; color: #e0e0e0; font-size: 14px;">🛒 获取冰糕</h4>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                <div class="purchase-tier" data-url="https://item.taobao.com/item.htm?ft=t&id=1007803936312&skuId=6168304691735" style="background: #0d1117; border: 1px solid #2a2a4a; border-radius: 8px; padding: 12px; text-align: center; cursor: pointer; transition: border-color 0.2s;">
                    <div style="font-size: 14px; font-weight: 600; color: #e0e0e0;">小型尝鲜礼包</div>
                    <div style="font-size: 18px; font-weight: 700; color: #58a6ff; margin: 6px 0;">冰糕 ×600</div>
                    <div style="font-size: 14px; color: #43cf7c;">¥6</div>
                </div>
                <div class="purchase-tier" data-url="https://item.taobao.com/item.htm?ft=t&id=1007803936312&skuId=6168304691736" style="background: #0d1117; border: 1px solid #2a2a4a; border-radius: 8px; padding: 12px; text-align: center; cursor: pointer; transition: border-color 0.2s;">
                    <div style="font-size: 14px; font-weight: 600; color: #e0e0e0;">中型品鉴礼包</div>
                    <div style="font-size: 18px; font-weight: 700; color: #58a6ff; margin: 6px 0;">冰糕 ×3300</div>
                    <div style="font-size: 14px; color: #2a82e4;">¥30</div>
                </div>
                <div class="purchase-tier" data-url="https://item.taobao.com/item.htm?ft=t&id=1007803936312&skuId=6168304691737" style="background: #0d1117; border: 1px solid #2a2a4a; border-radius: 8px; padding: 12px; text-align: center; cursor: pointer; transition: border-color 0.2s;">
                    <div style="font-size: 14px; font-weight: 600; color: #e0e0e0;">大型畅享礼包</div>
                    <div style="font-size: 18px; font-weight: 700; color: #58a6ff; margin: 6px 0;">冰糕 ×7200</div>
                    <div style="font-size: 14px; color: #7948ea;">¥60</div>
                </div>
                <div class="purchase-tier" data-url="https://item.taobao.com/item.htm?ft=t&id=1007803936312&skuId=6168304691738" style="background: #0d1117; border: 1px solid #2a2a4a; border-radius: 8px; padding: 12px; text-align: center; cursor: pointer; transition: border-color 0.2s;">
                    <div style="font-size: 14px; font-weight: 600; color: #e0e0e0;">巨型满足礼包</div>
                    <div style="font-size: 18px; font-weight: 700; color: #58a6ff; margin: 6px 0;">冰糕 ×13000</div>
                    <div style="font-size: 14px; color: #ffc300;">¥100</div>
                </div>
            </div>
            <p style="font-size: 11px; color: #666; margin: 12px 0 0; text-align: center;">⚠️ 越多人消耗冰糕，未来单次运行消耗的冰糕数越会降低 ↓</p>
        `;
        container.appendChild(purchaseSection);

        // Pricing section (模型消耗表)
        const pricingSection = document.createElement("div");
        pricingSection.className = "batchbox-account-pricing";
        pricingSection.style.cssText = `
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 20px;
            margin-top: 12px;
            display: none;
        `;
        pricingSection.innerHTML = `
            <h4 style="margin: 0 0 12px; color: #e0e0e0; font-size: 14px;">📊 模型冰糕消耗</h4>
            <div class="pricing-table-container" style="font-size: 12px;">
                <p style="color: #888;">加载中...</p>
            </div>
        `;
        container.appendChild(pricingSection);

        // Pricing strategy section (通道策略)
        const strategySection = document.createElement("div");
        strategySection.className = "batchbox-account-strategy";
        strategySection.style.cssText = `
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 20px;
            margin-top: 12px;
        `;

        // Load current pricing strategy from node settings
        let currentStrategy = "bestPrice";
        try {
            const nsResp = await api.fetchApi("/api/batchbox/node-settings");
            const nsData = await nsResp.json();
            currentStrategy = nsData.node_settings?.pricing_strategy || "bestPrice";
        } catch (e) {
            console.error("Failed to load pricing strategy:", e);
        }

        strategySection.innerHTML = `
            <h4 style="margin: 0 0 8px; color: #e0e0e0; font-size: 14px;">⚡ 通道策略</h4>
            <p style="font-size: 11px; color: #888; margin: 0 0 12px;">选择 Account 服务的供应商分配策略（同 Blender 插件的低价优先/稳定优先）</p>
            <div style="display: flex; gap: 10px;">
                <button class="strategy-btn" data-value="bestPrice" style="flex: 1; padding: 12px; border-radius: 8px; border: 2px solid ${currentStrategy === 'bestPrice' ? '#58a6ff' : '#2a2a4a'}; background: ${currentStrategy === 'bestPrice' ? '#0d2137' : '#0d1117'}; color: #e0e0e0; cursor: pointer; transition: all 0.2s; text-align: center;">
                    <div style="font-size: 20px; margin-bottom: 4px;">💰</div>
                    <div style="font-size: 13px; font-weight: 600;">低价优先</div>
                    <div style="font-size: 10px; color: #888; margin-top: 2px;">选择最优惠的供应商</div>
                </button>
                <button class="strategy-btn" data-value="bestBalance" style="flex: 1; padding: 12px; border-radius: 8px; border: 2px solid ${currentStrategy === 'bestBalance' ? '#58a6ff' : '#2a2a4a'}; background: ${currentStrategy === 'bestBalance' ? '#0d2137' : '#0d1117'}; color: #e0e0e0; cursor: pointer; transition: all 0.2s; text-align: center;">
                    <div style="font-size: 20px; margin-bottom: 4px;">⚡</div>
                    <div style="font-size: 13px; font-weight: 600;">稳定优先</div>
                    <div style="font-size: 10px; color: #888; margin-top: 2px;">选择最稳定的供应商</div>
                </button>
            </div>
        `;
        container.appendChild(strategySection);

        // Wire strategy buttons
        strategySection.querySelectorAll(".strategy-btn").forEach(btn => {
            btn.onmouseenter = () => { if (btn.style.borderColor !== "rgb(88, 166, 255)") btn.style.borderColor = "#444"; };
            btn.onmouseleave = () => { if (btn.style.borderColor !== "rgb(88, 166, 255)") btn.style.borderColor = "#2a2a4a"; };
            btn.onclick = async () => {
                const value = btn.dataset.value;
                // Update visual state
                strategySection.querySelectorAll(".strategy-btn").forEach(b => {
                    b.style.borderColor = "#2a2a4a";
                    b.style.background = "#0d1117";
                });
                btn.style.borderColor = "#58a6ff";
                btn.style.background = "#0d2137";
                // Save to node settings
                try {
                    const resp = await api.fetchApi("/api/batchbox/node-settings", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ pricing_strategy: value }),
                    });
                    if (resp.ok) {
                        // Sync to this.config so "保存所有更改" doesn't overwrite
                        if (!this.config.node_settings) this.config.node_settings = {};
                        this.config.node_settings.pricing_strategy = value;
                        this.showToast(`通道策略已切换为: ${value === 'bestPrice' ? '低价优先 💰' : '稳定优先 ⚡'}`, "success");
                    } else {
                        throw new Error("保存失败");
                    }
                } catch (e) {
                    this.showToast("保存失败: " + e.message, "error");
                }
            };
        });

        // Info section
        const infoSection = document.createElement("div");
        infoSection.style.cssText = `
            margin-top: 20px;
            padding: 16px;
            background: #0d1117;
            border-radius: 8px;
            border: 1px solid #1a1a2a;
        `;
        infoSection.innerHTML = `
            <p style="font-size: 12px; color: #888; margin: 0 0 8px;">
                <strong style="color: #aaa;">ℹ️ 关于 Account 服务</strong>
            </p>
            <p style="font-size: 11px; color: #666; margin: 0; line-height: 1.6;">
                Account 服务由 AIGODLIKE 提供稳定的 API 代理通道，通过冰糕(积分)计费。<br>
                登录后即可使用 Account 通道的模型进行图片生成。
            </p>
        `;
        container.appendChild(infoSection);

        // Server status indicator
        const serverStatusEl = document.createElement("div");
        serverStatusEl.style.cssText = `
            margin-top: 12px;
            padding: 10px 16px;
            background: #0d1117;
            border-radius: 8px;
            border: 1px solid #1a1a2a;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
        `;
        serverStatusEl.innerHTML = `
            <span class="server-status-dot" style="width: 8px; height: 8px; border-radius: 50%; background: #888;"></span>
            <span class="server-status-text" style="color: #888;">服务器状态: 检测中...</span>
        `;
        container.appendChild(serverStatusEl);

        // --- Wire up logic ---
        const nicknameEl = statusCard.querySelector(".account-nickname");
        const statusTextEl = statusCard.querySelector(".account-status-text");
        const avatarEl = statusCard.querySelector(".account-avatar");
        const creditsRow = statusCard.querySelector(".account-credits-row");
        const creditsValueEl = statusCard.querySelector(".account-credits-value");
        const actionsEl = statusCard.querySelector(".account-actions");
        const refreshCreditsBtn = statusCard.querySelector(".btn-refresh-credits");
        const redeemBtn = redeemSection.querySelector(".btn-redeem");
        const redeemInput = redeemSection.querySelector(".redeem-code-input");
        const redeemResult = redeemSection.querySelector(".redeem-result");

        const updateUI = (status) => {
            // Update server status indicator
            const dot = serverStatusEl.querySelector(".server-status-dot");
            const statusLabel = serverStatusEl.querySelector(".server-status-text");
            if (status.services_connected) {
                dot.style.background = "#4ade80";
                statusLabel.style.color = "#4ade80";
                statusLabel.textContent = "服务器状态: 已连接";
            } else {
                dot.style.background = "#f87171";
                statusLabel.style.color = "#f87171";
                statusLabel.textContent = "服务器状态: 未连接";
            }

            // Token expiry warning
            if (status.token_expired) {
                avatarEl.textContent = "⚠️";
                avatarEl.style.background = "#2a2a1a";
                nicknameEl.textContent = status.nickname || "用户";
                statusTextEl.textContent = "Token 已过期，请重新登录";
                statusTextEl.style.color = "#f0c060";
                creditsRow.style.display = "none";
                redeemSection.style.display = "none";
                purchaseSection.style.display = "none";
                pricingSection.style.display = "none";

                actionsEl.innerHTML = "";
                const reLoginBtn = document.createElement("button");
                reLoginBtn.className = "batchbox-btn btn-primary";
                reLoginBtn.innerText = "🔑 重新登录";
                reLoginBtn.style.cssText = "padding: 12px 28px; font-size: 14px; font-weight: 600;";
                reLoginBtn.onclick = async () => {
                    reLoginBtn.disabled = true;
                    reLoginBtn.innerText = "⏳ 正在打开浏览器...";
                    try {
                        await api.fetchApi("/api/batchbox/account/logout", { method: "POST" });
                        const resp = await api.fetchApi("/api/batchbox/account/login", { method: "POST" });
                        const result = await resp.json();
                        if (result.success) {
                            this.showToast("登录成功！", "success");
                            this.renderAccountTab(container);
                        } else {
                            this.showToast(result.error || "登录失败", "error");
                            reLoginBtn.disabled = false;
                            reLoginBtn.innerText = "🔑 重新登录";
                        }
                    } catch (e) {
                        this.showToast("登录失败: " + e.message, "error");
                        reLoginBtn.disabled = false;
                        reLoginBtn.innerText = "🔑 重新登录";
                    }
                };
                actionsEl.appendChild(reLoginBtn);
                return;
            }

            if (status.logged_in) {
                avatarEl.textContent = "✅";
                avatarEl.style.background = "#1a3a2a";
                nicknameEl.textContent = status.nickname || "用户";
                statusTextEl.textContent = "已登录";
                statusTextEl.style.color = "#4ade80";
                creditsRow.style.display = "block";
                creditsValueEl.textContent = status.credits !== undefined ? status.credits : "--";
                redeemSection.style.display = "none";
                purchaseSection.style.display = "none";

                actionsEl.innerHTML = "";

                const hideAllPanels = () => {
                    purchaseSection.style.display = "none";
                    redeemSection.style.display = "none";
                    pricingSection.style.display = "none";
                };

                // 获取冰糕 button
                const purchaseBtn = document.createElement("button");
                purchaseBtn.className = "batchbox-btn btn-primary";
                purchaseBtn.innerText = "🛒 获取冰糕";
                purchaseBtn.style.padding = "10px 20px";
                purchaseBtn.onclick = () => {
                    const show = purchaseSection.style.display === "none";
                    hideAllPanels();
                    if (show) purchaseSection.style.display = "block";
                };
                actionsEl.appendChild(purchaseBtn);

                // 兑换冰糕 button
                const redeemToggleBtn = document.createElement("button");
                redeemToggleBtn.className = "batchbox-btn btn-primary";
                redeemToggleBtn.innerText = "🎁 兑换冰糕";
                redeemToggleBtn.style.padding = "10px 20px";
                redeemToggleBtn.onclick = () => {
                    const show = redeemSection.style.display === "none";
                    hideAllPanels();
                    if (show) redeemSection.style.display = "block";
                };
                actionsEl.appendChild(redeemToggleBtn);

                // 消耗查询 button
                const pricingBtn = document.createElement("button");
                pricingBtn.className = "batchbox-btn btn-primary";
                pricingBtn.innerText = "📊 消耗查询";
                pricingBtn.style.padding = "10px 20px";
                pricingBtn.onclick = async () => {
                    const show = pricingSection.style.display === "none";
                    hideAllPanels();
                    if (show) {
                        pricingSection.style.display = "block";
                        const tableContainer = pricingSection.querySelector(".pricing-table-container");
                        tableContainer.innerHTML = '<p style="color: #888;">⏳ 加载中...</p>';
                        try {
                            const resp = await api.fetchApi("/api/batchbox/account/pricing");
                            const data = await resp.json();
                            if (data.price_table && data.price_table.length > 0) {
                                let html = `<table style="width: 100%; border-collapse: collapse;">`;
                                html += `<tr style="border-bottom: 1px solid #2a2a4a;">
                                    <th style="text-align: left; padding: 8px 6px; color: #aaa;">模型</th>
                                    <th style="text-align: right; padding: 8px 6px; color: #aaa;">文生图</th>
                                    <th style="text-align: right; padding: 8px 6px; color: #aaa;">图生图</th>
                                </tr>`;
                                for (const item of data.price_table) {
                                    const name = item.modelName || "未知";
                                    const t2i = item.text2img || item.txt2img;
                                    const i2i = item.img2img;
                                    const t2iPrice = t2i ? (t2i.price || t2i.coin || "-") : "-";
                                    const i2iPrice = i2i ? (i2i.price || i2i.coin || "-") : "-";
                                    html += `<tr style="border-bottom: 1px solid #1a1a2a;">
                                        <td style="padding: 8px 6px; color: #e0e0e0;">${name}</td>
                                        <td style="text-align: right; padding: 8px 6px; color: #58a6ff;">${t2iPrice} 🍦</td>
                                        <td style="text-align: right; padding: 8px 6px; color: #58a6ff;">${i2iPrice} 🍦</td>
                                    </tr>`;
                                }
                                html += `</table>`;
                                tableContainer.innerHTML = html;
                            } else {
                                tableContainer.innerHTML = '<p style="color: #888;">暂无定价信息</p>';
                            }
                        } catch (e) {
                            tableContainer.innerHTML = `<p style="color: #f87171;">获取失败: ${e.message}</p>`;
                        }
                    }
                };
                actionsEl.appendChild(pricingBtn);

                // 退出登录 button
                const logoutBtn = document.createElement("button");
                logoutBtn.className = "batchbox-btn btn-danger";
                logoutBtn.innerText = "退出登录";
                logoutBtn.style.padding = "10px 24px";
                logoutBtn.onclick = async () => {
                    logoutBtn.disabled = true;
                    logoutBtn.innerText = "⏳ 退出中...";
                    try {
                        await api.fetchApi("/api/batchbox/account/logout", { method: "POST" });
                        this.showToast("已退出登录", "success");
                        this.renderAccountTab(container);
                    } catch (e) {
                        this.showToast("退出失败: " + e.message, "error");
                        logoutBtn.disabled = false;
                        logoutBtn.innerText = "退出登录";
                    }
                };
                actionsEl.appendChild(logoutBtn);
            } else {
                avatarEl.textContent = "🔒";
                avatarEl.style.background = "#2a1a1a";
                nicknameEl.textContent = "未登录";
                statusTextEl.textContent = "点击登录以使用 Account 服务";
                statusTextEl.style.color = "#888";
                creditsRow.style.display = "none";
                redeemSection.style.display = "none";
                purchaseSection.style.display = "none";
                pricingSection.style.display = "none";

                actionsEl.innerHTML = "";
                const loginBtn = document.createElement("button");
                loginBtn.className = "batchbox-btn btn-primary";
                loginBtn.innerText = "🔑 登录 Account";
                loginBtn.style.cssText = "padding: 12px 28px; font-size: 14px; font-weight: 600;";
                loginBtn.onclick = async () => {
                    loginBtn.disabled = true;
                    loginBtn.innerText = "⏳ 正在打开浏览器...";
                    statusTextEl.textContent = "请在浏览器中完成登录";
                    statusTextEl.style.color = "#f0c060";
                    try {
                        const resp = await api.fetchApi("/api/batchbox/account/login", { method: "POST" });
                        const result = await resp.json();
                        if (result.success) {
                            this.showToast("登录成功！", "success");
                            this.renderAccountTab(container);
                        } else {
                            this.showToast(result.error || "登录失败", "error");
                            loginBtn.disabled = false;
                            loginBtn.innerText = "🔑 登录 Account";
                            statusTextEl.textContent = "登录失败，请重试";
                            statusTextEl.style.color = "#f87171";
                        }
                    } catch (e) {
                        this.showToast("登录请求失败: " + e.message, "error");
                        loginBtn.disabled = false;
                        loginBtn.innerText = "🔑 登录 Account";
                        statusTextEl.textContent = "连接失败，请检查网络";
                        statusTextEl.style.color = "#f87171";
                    }
                };
                actionsEl.appendChild(loginBtn);
            }
        };

        // Refresh credits
        refreshCreditsBtn.onclick = async () => {
            refreshCreditsBtn.disabled = true;
            refreshCreditsBtn.innerText = "⏳ 刷新中...";
            try {
                const resp = await api.fetchApi("/api/batchbox/account/credits", { method: "POST" });
                const data = await resp.json();
                if (data.credits !== undefined) {
                    creditsValueEl.textContent = data.credits;
                }
                this.showToast("积分已刷新", "success");
            } catch (e) {
                this.showToast("刷新失败: " + e.message, "error");
            }
            refreshCreditsBtn.disabled = false;
            refreshCreditsBtn.innerText = "🔄 刷新";
        };

        // Redeem code
        redeemBtn.onclick = async () => {
            const code = redeemInput.value.trim();
            if (!code) {
                this.showToast("请输入兑换码", "error");
                return;
            }
            redeemBtn.disabled = true;
            redeemBtn.innerText = "⏳ 兑换中...";
            redeemResult.style.display = "none";
            try {
                const resp = await api.fetchApi("/api/batchbox/account/redeem", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ code })
                });
                const data = await resp.json();
                redeemResult.style.display = "block";
                if (data.success) {
                    redeemResult.style.color = "#4ade80";
                    redeemResult.textContent = `✅ 兑换成功！获得 ${data.credits_added || ""} 积分`;
                    redeemInput.value = "";
                    // Refresh credits
                    refreshCreditsBtn.click();
                } else {
                    redeemResult.style.color = "#f87171";
                    redeemResult.textContent = `❌ ${data.error || "兑换失败"}`;
                }
            } catch (e) {
                redeemResult.style.display = "block";
                redeemResult.style.color = "#f87171";
                redeemResult.textContent = `❌ 兑换请求失败: ${e.message}`;
            }
            redeemBtn.disabled = false;
            redeemBtn.innerText = "兑换";
        };

        // Purchase tier hover effects & click to open Taobao
        purchaseSection.querySelectorAll(".purchase-tier").forEach(tier => {
            tier.onmouseenter = () => { tier.style.borderColor = "#58a6ff"; };
            tier.onmouseleave = () => { tier.style.borderColor = "#2a2a4a"; };
            tier.onclick = () => {
                const url = tier.dataset.url;
                if (url) window.open(url, "_blank");
            };
        });

        // Enter key for redeem
        redeemInput.onkeydown = (e) => {
            if (e.key === "Enter") redeemBtn.click();
        };

        // Fetch initial status
        try {
            const resp = await api.fetchApi("/api/batchbox/account/status");
            const status = await resp.json();
            updateUI(status);
        } catch (e) {
            nicknameEl.textContent = "连接失败";
            statusTextEl.textContent = "无法获取 Account 状态";
            statusTextEl.style.color = "#f87171";
            avatarEl.textContent = "⚠️";
        }
    }

    // ================================================================
    // 2.1 PROVIDERS
    // ================================================================

    /**
     * Render the providers management panel.
     * @param {HTMLElement} container - Target container element
     */
    renderProviders(container) {
        container.innerHTML = "";

        const header = document.createElement("div");
        header.className = "batchbox-panel-header";
        header.innerHTML = `<h3>供应商管理</h3>`;

        const addBtn = document.createElement("button");
        addBtn.className = "batchbox-btn btn-success";
        addBtn.innerText = "+ 添加供应商";
        addBtn.onclick = () => this.showProviderForm();
        header.appendChild(addBtn);
        container.appendChild(header);

        const table = document.createElement("table");
        table.className = "batchbox-table";
        table.innerHTML = `<thead><tr><th>名称</th><th>Base URL</th><th>API Key</th><th>操作</th></tr></thead>`;
        const tbody = document.createElement("tbody");

        const providers = this.config.providers || {};
        for (const [name, data] of Object.entries(providers)) {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${name}</strong></td>
                <td>${data.base_url || ""}</td>
                <td>${data.api_key ? "••••••" + data.api_key.slice(-4) : ""}</td>
                <td></td>
            `;
            const actionCell = tr.querySelector("td:last-child");

            const editBtn = document.createElement("button");
            editBtn.className = "batchbox-btn btn-edit";
            editBtn.innerText = "编辑";
            editBtn.onclick = () => this.showProviderForm(name);
            actionCell.appendChild(editBtn);

            const delBtn = document.createElement("button");
            delBtn.className = "batchbox-btn btn-danger";
            delBtn.innerText = "删除";
            delBtn.onclick = () => this.confirmDelete("provider", name);
            actionCell.appendChild(delBtn);

            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        container.appendChild(table);

        if (Object.keys(providers).length === 0) {
            container.innerHTML += `<p class="batchbox-empty">暂无供应商，点击上方按钮添加。</p>`;
        }
    }

    showProviderForm(editName = null) {
        const isEdit = editName !== null;
        const existing = isEdit ? this.config.providers[editName] : {};

        this.showFormModal({
            title: isEdit ? `编辑供应商: ${editName}` : "添加新供应商",
            fields: [
                { name: "name", label: "名称", value: editName || "", required: true },
                { name: "base_url", label: "Base URL", value: existing.base_url || "", placeholder: "https://api.example.com", required: true },
                { name: "api_key", label: "API Key", value: existing.api_key || "", placeholder: "sk-xxxxxx", type: "password" },
                { name: "divider1", type: "divider", label: "高级设置 (可选)" },
                {
                    name: "file_format",
                    label: "文件格式",
                    type: "select",
                    value: existing.file_format || "",
                    options: [
                        { value: "", label: "默认 (同名多个)" },
                        { value: "same_name", label: "同名多个: image, image" },
                        { value: "indexed", label: "索引式: image[0], image[1]" },
                        { value: "array", label: "数组式: images[], images[]" },
                        { value: "numbered", label: "编号式: image1, image2" }
                    ]
                },
                { name: "file_field", label: "文件字段名", value: existing.file_field || "", placeholder: "默认: image" }
            ],
            onSubmit: (data) => {
                if (!data.name || !data.base_url) {
                    this.showToast("名称和 Base URL 为必填项", "error");
                    return false;
                }
                if (!isEdit && this.config.providers[data.name]) {
                    this.showToast("该名称已存在", "error");
                    return false;
                }
                const providerConfig = {
                    base_url: data.base_url,
                    api_key: data.api_key
                };
                // Only add file settings if specified
                if (data.file_format) providerConfig.file_format = data.file_format;
                if (data.file_field) providerConfig.file_field = data.file_field;

                this.config.providers[data.name] = providerConfig;
                if (isEdit && data.name !== editName) {
                    delete this.config.providers[editName];
                }
                this.renderProviders(this.panels["providers"]);
                this.showToast(isEdit ? "供应商已更新" : "供应商已添加", "success");
                return true;
            }
        });
    }

    // ================================================================
    // 2.2 MODELS
    // ================================================================

    /**
     * Render the models management panel.
     * @param {HTMLElement} container - Target container element
     */
    renderModels(container) {
        container.innerHTML = "";

        const header = document.createElement("div");
        header.className = "batchbox-panel-header";
        header.innerHTML = `<h3>模型管理</h3>`;

        const addBtn = document.createElement("button");
        addBtn.className = "batchbox-btn btn-success";
        addBtn.innerText = "+ 添加模型";
        addBtn.onclick = () => this.showModelForm();
        header.appendChild(addBtn);
        container.appendChild(header);

        // Category tabs
        const categories = this.config.node_categories || {
            image: { display_name: "🖼️ 图片生成" },
            text: { display_name: "📝 文本生成" },
            video: { display_name: "🎬 视频生成" },
            audio: { display_name: "🎵 音频生成" },
            image_editor: { display_name: "🔧 图片编辑" }
        };

        const catTabs = document.createElement("div");
        catTabs.className = "batchbox-category-tabs";
        let firstCat = null;
        Object.entries(categories).forEach(([catKey, catData], idx) => {
            if (!firstCat) firstCat = catKey;
            const tab = document.createElement("button");
            tab.className = `batchbox-cat-tab ${idx === 0 ? "active" : ""}`;
            tab.innerText = catData.display_name || catKey;
            tab.dataset.category = catKey;
            tab.onclick = () => {
                catTabs.querySelectorAll(".batchbox-cat-tab").forEach(t => t.classList.remove("active"));
                tab.classList.add("active");
                this.renderModelList(modelListContainer, catKey);
            };
            catTabs.appendChild(tab);
        });
        container.appendChild(catTabs);

        const modelListContainer = document.createElement("div");
        modelListContainer.className = "batchbox-model-list-container";
        container.appendChild(modelListContainer);

        this.renderModelList(modelListContainer, firstCat);
    }

    renderModelList(container, category) {
        container.innerHTML = "";
        this.currentCategory = category;
        this.dragContainer = container;

        const models = this.config.models || {};
        let filteredModels = Object.entries(models).filter(([name, data]) =>
            data.category === category
        );

        if (filteredModels.length === 0) {
            container.innerHTML = `<p class="batchbox-empty">该分类下暂无模型</p>`;
            return;
        }

        // Sort by configured order
        const modelOrder = this.config.model_order?.[category] || [];
        if (modelOrder.length > 0) {
            const orderMap = {};
            modelOrder.forEach((name, i) => orderMap[name] = i);
            const maxIndex = modelOrder.length;
            filteredModels.sort((a, b) => {
                const ai = orderMap[a[0]] ?? maxIndex;
                const bi = orderMap[b[0]] ?? maxIndex;
                return ai - bi || a[0].localeCompare(b[0]);
            });
        }

        const table = document.createElement("table");
        table.className = "batchbox-table batchbox-sortable";
        table.innerHTML = `<thead><tr><th style="width:40px;"></th><th>模型名称</th><th>描述</th><th>API站点数</th><th>参数数</th><th>操作</th></tr></thead>`;
        const tbody = document.createElement("tbody");
        tbody.className = "batchbox-sortable-body";

        filteredModels.forEach(([name, data], index) => {
            const endpointCount = (data.api_endpoints || []).length;
            const paramCount = this.countModelParams(data.parameter_schema || {});

            const tr = document.createElement("tr");
            tr.className = "batchbox-sortable-row";
            tr.dataset.modelName = name;
            tr.draggable = true;
            tr.innerHTML = `
                <td class="batchbox-drag-handle" title="拖拽排序">⋮⋮</td>
                <td><strong>${data.display_name || name}</strong><br><small style="color:#888">${name}</small></td>
                <td>${data.description || ""}</td>
                <td><span class="batchbox-badge">${endpointCount}</span></td>
                <td><span class="batchbox-badge">${paramCount}</span></td>
                <td class="batchbox-action-cell"></td>
            `;

            // Drag events
            tr.ondragstart = (e) => this.handleDragStart(e, name);
            tr.ondragover = (e) => this.handleDragOver(e);
            tr.ondragenter = (e) => this.handleDragEnter(e);
            tr.ondragleave = (e) => this.handleDragLeave(e);
            tr.ondrop = (e) => this.handleDrop(e, category, container);
            tr.ondragend = (e) => this.handleDragEnd(e);

            // Action buttons cell
            const actionCell = tr.querySelector(".batchbox-action-cell");

            const editBtn = document.createElement("button");
            editBtn.className = "batchbox-btn btn-edit";
            editBtn.innerText = "编辑";
            editBtn.onclick = () => this.showModelForm(name);
            actionCell.appendChild(editBtn);

            const copyBtn = document.createElement("button");
            copyBtn.className = "batchbox-btn btn-secondary";
            copyBtn.innerText = "复制";
            copyBtn.onclick = () => this.duplicateModel(name);
            actionCell.appendChild(copyBtn);

            const delBtn = document.createElement("button");
            delBtn.className = "batchbox-btn btn-danger";
            delBtn.innerText = "删除";
            delBtn.onclick = () => this.confirmDelete("model", name);
            actionCell.appendChild(delBtn);

            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        container.appendChild(table);
    }

    // Drag and Drop handlers
    handleDragStart(e, modelName) {
        this.draggedModel = modelName;
        e.target.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", modelName);
    }

    handleDragOver(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
    }

    handleDragEnter(e) {
        const row = e.target.closest(".batchbox-sortable-row");
        if (row && row.dataset.modelName !== this.draggedModel) {
            row.classList.add("drag-over");
        }
    }

    handleDragLeave(e) {
        const row = e.target.closest(".batchbox-sortable-row");
        if (row) {
            row.classList.remove("drag-over");
        }
    }

    async handleDrop(e, category, container) {
        e.preventDefault();
        const targetRow = e.target.closest(".batchbox-sortable-row");
        if (!targetRow) return;

        const targetModel = targetRow.dataset.modelName;
        if (targetModel === this.draggedModel) return;

        targetRow.classList.remove("drag-over");

        // Reorder
        const models = this.config.models || {};
        let categoryModels = Object.keys(models).filter(name =>
            models[name].category === category
        );

        let order = this.config.model_order?.[category] || [...categoryModels];
        categoryModels.forEach(name => {
            if (!order.includes(name)) order.push(name);
        });
        order = order.filter(name => categoryModels.includes(name));

        const dragIndex = order.indexOf(this.draggedModel);
        const dropIndex = order.indexOf(targetModel);

        if (dragIndex === -1 || dropIndex === -1) return;

        // Remove dragged item and insert at new position
        order.splice(dragIndex, 1);
        order.splice(dropIndex, 0, this.draggedModel);

        // Save
        if (!this.config.model_order) this.config.model_order = {};
        this.config.model_order[category] = order;

        try {
            await fetch(`/api/batchbox/model-order/${encodeURIComponent(category)}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ order })
            });
            this.toast("顺序已更新", "success");
        } catch (e) {
            console.error("Failed to save model order:", e);
        }

        this.renderModelList(container, category);
    }

    handleDragEnd(e) {
        e.target.classList.remove("dragging");
        document.querySelectorAll(".drag-over").forEach(el => el.classList.remove("drag-over"));
        this.draggedModel = null;
    }

    countModelParams(schema) {
        let count = 0;
        for (const group of Object.values(schema)) {
            count += Object.keys(group || {}).length;
        }
        return count;
    }

    duplicateModel(name) {
        const original = this.config.models[name];
        if (!original) return;

        const newName = name + "_copy";
        this.config.models[newName] = JSON.parse(JSON.stringify(original));
        this.config.models[newName].display_name = (original.display_name || name) + " (副本)";
        this.renderModels(this.panels["models"]);
        this.showToast(`已复制模型为 ${newName}`, "success");
    }

    showModelForm(editName = null) {
        const isEdit = editName !== null;
        const existing = isEdit ? (this.config.models[editName] || {}) : {};
        const providerOptions = Object.keys(this.config.providers || {});

        const categories = this.config.node_categories || {
            image: { display_name: "🖼️ 图片生成" },
            text: { display_name: "📝 文本生成" },
            video: { display_name: "🎬 视频生成" },
            audio: { display_name: "🎵 音频生成" },
            image_editor: { display_name: "🔧 图片编辑" }
        };

        const paramSchema = existing.parameter_schema || { basic: {}, advanced: {} };
        const apiEndpoints = existing.api_endpoints || [];

        const overlay = document.createElement("div");
        overlay.className = "batchbox-submodal-overlay";

        const modal = document.createElement("div");
        modal.className = "batchbox-submodal batchbox-model-modal";
        modal.style.maxWidth = "850px";
        modal.style.maxHeight = "85vh";

        modal.innerHTML = `
            <div class="batchbox-submodal-header"><h4>${isEdit ? `编辑模型: ${editName}` : "添加新模型"}</h4></div>
            <div class="batchbox-submodal-body batchbox-tabs-container" style="max-height: 60vh; overflow-y: auto;">
                <div class="batchbox-form-tabs">
                    <button class="batchbox-form-tab active" data-tab="basic">基础信息</button>
                    <button class="batchbox-form-tab" data-tab="params">参数配置</button>
                    <button class="batchbox-form-tab" data-tab="api">API端点</button>
                </div>
                
                <div class="batchbox-form-tab-content active" data-tab="basic">
                    <div class="batchbox-form-group">
                        <label>模型ID (唯一标识) *</label>
                        <input type="text" name="model_id" value="${editName || ""}" class="batchbox-form-input" placeholder="banana_pro">
                    </div>
                    <div class="batchbox-form-row">
                        <div class="batchbox-form-group">
                            <label>显示名称 *</label>
                            <input type="text" name="display_name" value="${existing.display_name || ""}" class="batchbox-form-input" placeholder="🍌 Banana Pro">
                        </div>
                        <div class="batchbox-form-group">
                            <label>分类 *</label>
                            <select name="category" class="batchbox-form-input">
                                ${Object.entries(categories).map(([k, v]) =>
            `<option value="${k}" ${k === existing.category ? "selected" : ""}>${v.display_name || k}</option>`
        ).join("")}
                            </select>
                        </div>
                    </div>
                    <div class="batchbox-form-group">
                        <label>描述</label>
                        <input type="text" name="description" value="${existing.description || ""}" class="batchbox-form-input" placeholder="高质量图片生成模型">
                    </div>
                    <div class="batchbox-form-group" style="margin-top: 16px; padding: 12px; background: #1a1a2a; border-radius: 8px;">
                        <label style="display: flex; align-items: center; cursor: pointer; gap: 10px;">
                            <input type="checkbox" name="show_seed_widget" ${existing.show_seed_widget !== false ? "checked" : ""} style="width: 18px; height: 18px;">
                            <span>显示 Seed 控制组件</span>
                        </label>
                        <p style="font-size: 11px; color: #888; margin: 6px 0 0 28px;">启用后，节点将显示 "seed" 和 "生成后控制" 参数</p>
                    </div>
                </div>
                
                <div class="batchbox-form-tab-content" data-tab="params">
                    <p class="batchbox-hint">配置该模型支持的参数，选择模型后会在节点上动态显示这些参数</p>
                    
                    <div class="batchbox-param-section">
                        <div class="batchbox-param-section-header">
                            <span>基础参数 (basic)</span>
                            <button class="batchbox-btn btn-success btn-sm btn-add-model-param" data-group="basic">+ 添加</button>
                        </div>
                        <div class="batchbox-param-list" data-group="basic"></div>
                    </div>
                    
                    <div class="batchbox-param-section">
                        <div class="batchbox-param-section-header">
                            <span>高级参数 (advanced)</span>
                            <button class="batchbox-btn btn-success btn-sm btn-add-model-param" data-group="advanced">+ 添加</button>
                        </div>
                        <div class="batchbox-param-list" data-group="advanced"></div>
                    </div>
                </div>
                
                <div class="batchbox-form-tab-content" data-tab="api">
                    <p class="batchbox-hint">配置该模型在不同API站点的调用方式</p>
                    <div class="batchbox-api-endpoints-list"></div>
                    <button class="batchbox-btn btn-success btn-add-endpoint">+ 添加API端点</button>
                </div>
            </div>
            <div class="batchbox-submodal-footer">
                <button class="batchbox-btn btn-cancel">取消</button>
                <button class="batchbox-btn btn-primary">保存</button>
            </div>
        `;

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Tab switching
        modal.querySelectorAll(".batchbox-form-tab").forEach(tab => {
            tab.onclick = () => {
                modal.querySelectorAll(".batchbox-form-tab").forEach(t => t.classList.remove("active"));
                modal.querySelectorAll(".batchbox-form-tab-content").forEach(c => c.classList.remove("active"));
                tab.classList.add("active");
                modal.querySelector(`.batchbox-form-tab-content[data-tab="${tab.dataset.tab}"]`).classList.add("active");
            };
        });

        // Parameter editor state
        let currentParams = JSON.parse(JSON.stringify(paramSchema));
        let currentEndpoints = JSON.parse(JSON.stringify(apiEndpoints));

        const renderParams = () => {
            ["basic", "advanced"].forEach(group => {
                const list = modal.querySelector(`.batchbox-param-list[data-group="${group}"]`);
                list.innerHTML = "";
                const params = currentParams[group] || {};

                Object.entries(params).forEach(([name, config]) => {
                    const item = document.createElement("div");
                    item.className = "batchbox-param-item";
                    item.style.cssText = "margin: 8px 0; padding: 10px; background: #252525; border-radius: 6px;";

                    const typeVal = config.type || "string";
                    // Show options in value=label format, or just value if same
                    const optionsStr = Array.isArray(config.options)
                        ? config.options.map(o => {
                            if (typeof o === 'object') {
                                return o.value === o.label ? o.value : `${o.value}==${o.label}`;
                            }
                            return o;
                        }).join(", ")
                        : "";

                    // Build display name: show name==api_name if api_name is set
                    const displayName = config.api_name ? `${name}==${config.api_name}` : name;

                    item.innerHTML = `
                        <div style="display: grid; grid-template-columns: 1fr 120px 1fr 30px; gap: 8px; align-items: center;">
                            <input type="text" class="param-name batchbox-form-input" value="${displayName}" placeholder="参数名 或 参数名==API名" style="padding: 6px;" title="可使用 ui_name==api_name 格式映射API参数名">
                            <select class="param-type batchbox-form-input" style="padding: 6px;">
                                <option value="string" ${typeVal === "string" ? "selected" : ""}>字符串</option>
                                <option value="select" ${typeVal === "select" ? "selected" : ""}>下拉选择</option>
                                <option value="number" ${typeVal === "number" ? "selected" : ""}>数字</option>
                                <option value="boolean" ${typeVal === "boolean" ? "selected" : ""}>开关</option>
                            </select>
                            <input type="text" class="param-default batchbox-form-input" value="${config.default !== undefined ? config.default : ""}" placeholder="默认值" style="padding: 6px;">
                            <button class="batchbox-btn btn-danger btn-sm btn-del" style="padding: 4px 8px;">×</button>
                        </div>
                        <div class="param-options-row" style="margin-top: 6px; display: ${typeVal === 'select' ? 'block' : 'none'};">
                            <input type="text" class="param-options batchbox-form-input" value="${optionsStr}" placeholder="选项 (格式: auto==自适应, 16:9, 4:3)" style="padding: 6px; width: 100%;">
                            <p style="font-size: 10px; color: #888; margin: 2px 0 0 0;">value和label相同时只写value，不同时用双等号分隔 value==label</p>
                        </div>
                        <p style="font-size: 10px; color: #666; margin: 4px 0 0 0;">参数名可用 resolution==image_size 格式，表示UI显示resolution，API发送image_size</p>
                    `;

                    // Show/hide options row when type changes
                    item.querySelector(".param-type").onchange = (e) => {
                        const optionsRow = item.querySelector(".param-options-row");
                        optionsRow.style.display = e.target.value === "select" ? "block" : "none";
                    };

                    item.querySelector(".btn-del").onclick = () => {
                        delete currentParams[group][name];
                        renderParams();
                    };

                    list.appendChild(item);
                });
            });
        };

        modal.querySelectorAll(".btn-add-model-param").forEach(btn => {
            btn.onclick = () => {
                const group = btn.dataset.group;
                if (!currentParams[group]) currentParams[group] = {};
                const newName = `param_${Date.now() % 10000}`;
                currentParams[group][newName] = { type: "string", default: "" };
                renderParams();
            };
        });

        const renderEndpoints = () => {
            const container = modal.querySelector(".batchbox-api-endpoints-list");
            container.innerHTML = "";

            currentEndpoints.forEach((ep, idx) => {
                const card = document.createElement("div");
                card.className = "batchbox-endpoint-card";
                card.style.cssText = "border: 1px solid #444; border-radius: 8px; padding: 12px; margin-bottom: 12px; background: #1a1a2a;";

                card.innerHTML = `
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <strong>端点 #${idx + 1}</strong>
                        <button class="batchbox-btn btn-danger btn-sm btn-del-endpoint">删除</button>
                    </div>
                    <div class="batchbox-form-group" style="margin-bottom: 8px;">
                        <label style="font-size: 11px;">端点名称 (用于手动选择)</label>
                        <input type="text" class="ep-display-name batchbox-form-input" value="${ep.display_name || ""}" style="padding: 6px;" placeholder="例如: 主线路, 备用线路, 高速通道">
                    </div>
                    <div class="batchbox-form-row" style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                        <div class="batchbox-form-group">
                            <label style="font-size: 11px;">供应商</label>
                            <select class="ep-provider batchbox-form-input" style="padding: 6px;">
                                ${providerOptions.map(p => `<option value="${p}" ${p === ep.provider ? "selected" : ""}>${p}</option>`).join("")}
                            </select>
                        </div>
                        <div class="batchbox-form-group">
                            <label style="font-size: 11px;">优先级</label>
                            <input type="number" class="ep-priority batchbox-form-input" value="${ep.priority || 1}" min="1" style="padding: 6px;">
                        </div>
                    </div>
                    <div class="batchbox-form-group" style="margin-top: 8px;">
                        <label style="font-size: 11px;">API 模型名称 (传给API的model参数)</label>
                        <input type="text" class="ep-model-name batchbox-form-input" value="${ep.model_name || ""}" style="padding: 6px;" placeholder="例如: nano-banana-2-4k, gpt-4o, dall-e-3">
                    </div>
                    <div class="batchbox-form-row" style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px;">
                        <div class="batchbox-form-group">
                            <label style="font-size: 11px;">text2img 端点 (文生图)</label>
                            <input type="text" class="ep-text2img batchbox-form-input" value="${ep.modes?.text2img?.endpoint || ""}" style="padding: 6px;" placeholder="留空则使用img2img端点">
                        </div>
                        <div class="batchbox-form-group">
                            <label style="font-size: 11px;">img2img 端点 (图生图)</label>
                            <input type="text" class="ep-img2img batchbox-form-input" value="${ep.modes?.img2img?.endpoint || ""}" style="padding: 6px;" placeholder="留空则使用text2img端点">
                        </div>
                    </div>
                    <p style="font-size: 10px; color: #888; margin: 4px 0 0 0;">至少配置一个端点，另一个留空则自动使用相同端点</p>
                    
                    <!-- Advanced Settings Collapsible -->
                    <div class="ep-advanced-toggle" style="margin-top: 12px; cursor: pointer; color: #6c9cff; font-size: 12px; user-select: none;">
                        ▶ 高级设置
                    </div>
                    <div class="ep-advanced-content" style="display: none; margin-top: 8px; padding: 10px; background: #0d0d15; border-radius: 6px;">
                        <div class="batchbox-form-row" style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                            <div class="batchbox-form-group">
                                <label style="font-size: 11px;">文件格式 (img2img)</label>
                                <select class="ep-file-format batchbox-form-input" style="padding: 6px;">
                                    <option value="" ${!ep.modes?.img2img?.file_format ? "selected" : ""}>继承供应商设置</option>
                                    <option value="same_name" ${ep.modes?.img2img?.file_format === "same_name" ? "selected" : ""}>同名多个</option>
                                    <option value="indexed" ${ep.modes?.img2img?.file_format === "indexed" ? "selected" : ""}>索引式 [0],[1]</option>
                                    <option value="array" ${ep.modes?.img2img?.file_format === "array" ? "selected" : ""}>数组式 []</option>
                                    <option value="numbered" ${ep.modes?.img2img?.file_format === "numbered" ? "selected" : ""}>编号式 1,2</option>
                                </select>
                            </div>
                            <div class="batchbox-form-group">
                                <label style="font-size: 11px;">文件字段名 (img2img)</label>
                                <input type="text" class="ep-file-field batchbox-form-input" value="${ep.modes?.img2img?.file_field || ""}" style="padding: 6px;" placeholder="默认: image">
                            </div>
                        </div>
                        <p style="font-size: 10px; color: #666; margin: 4px 0 0 0;">留空则继承供应商设置，供应商未设置则使用系统默认</p>
                        
                        <div class="batchbox-form-group" style="margin-top: 12px;">
                            <label style="font-size: 11px; display: flex; align-items: center; gap: 8px; cursor: pointer;">
                                <input type="checkbox" class="ep-use-oss-cache" ${ep.modes?.img2img?.use_oss_cache ? "checked" : ""}>
                                <span>OSS 图片缓存 (img2img)</span>
                            </label>
                            <p style="font-size: 10px; color: #666; margin: 4px 0 0 0;">开启后图转图时先上传到阿里 OSS，适用于 Gemini 等不支持 base64 直传的 API</p>
                        </div>
                        
                        <div class="batchbox-form-row" style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px;">
                            <div class="batchbox-form-group">
                                <label style="font-size: 11px;">API 格式</label>
                                <select class="ep-api-format batchbox-form-input" style="padding: 6px;">
                                    <option value="openai" ${!ep.api_format || ep.api_format === "openai" ? "selected" : ""}>OpenAI 兼容</option>
                                    <option value="gemini" ${ep.api_format === "gemini" ? "selected" : ""}>Gemini 原生</option>
                                </select>
                                <p style="font-size: 10px; color: #666; margin: 4px 0 0 0;">Gemini 原生支持 responseModalities</p>
                            </div>
                            <div class="batchbox-form-group">
                                <label style="font-size: 11px;">Prompt 前缀</label>
                                <input type="text" class="ep-prompt-prefix batchbox-form-input" value="${ep.prompt_prefix || ""}" style="padding: 6px;" placeholder="例如: 生成一张图片：">
                                <p style="font-size: 10px; color: #666; margin: 4px 0 0 0;">自动添加到用户 prompt 前</p>
                            </div>
                        </div>
                        
                        <div class="batchbox-form-group" style="margin-top: 12px;">
                            <label style="font-size: 11px;">额外请求参数 (JSON)</label>
                            <textarea class="ep-extra-params batchbox-form-input" style="padding: 6px; height: 60px; font-family: monospace; font-size: 11px;" placeholder='例如: {"response_modalities": ["Image"]}'>${ep.extra_params ? JSON.stringify(ep.extra_params, null, 2) : ""}</textarea>
                            <p style="font-size: 10px; color: #666; margin: 4px 0 0 0;">添加到请求体的额外参数，如 response_modalities 强制只返回图片</p>
                        </div>
                    </div>
                `;

                card.querySelector(".btn-del-endpoint").onclick = () => {
                    currentEndpoints.splice(idx, 1);
                    renderEndpoints();
                };

                // Toggle advanced settings
                const advToggle = card.querySelector(".ep-advanced-toggle");
                const advContent = card.querySelector(".ep-advanced-content");
                advToggle.onclick = () => {
                    const isOpen = advContent.style.display !== "none";
                    advContent.style.display = isOpen ? "none" : "block";
                    advToggle.textContent = isOpen ? "▶ 高级设置" : "▼ 高级设置";
                };

                container.appendChild(card);
            });
        };

        modal.querySelector(".btn-add-endpoint").onclick = () => {
            currentEndpoints.push({
                provider: providerOptions[0] || "",
                priority: currentEndpoints.length + 1,
                modes: {
                    text2img: { endpoint: "/v1/images/generations", method: "POST", content_type: "application/json", response_type: "sync" },
                    img2img: { endpoint: "", method: "POST", content_type: "multipart/form-data", response_type: "sync" }
                }
            });
            renderEndpoints();
        };

        renderParams();
        renderEndpoints();

        modal.querySelector(".btn-cancel").onclick = () => overlay.remove();
        modal.querySelector(".btn-primary").onclick = () => {
            const modelId = modal.querySelector('[name="model_id"]').value.trim();
            const displayName = modal.querySelector('[name="display_name"]').value.trim();
            const category = modal.querySelector('[name="category"]').value;

            if (!modelId || !displayName) {
                this.showToast("模型ID和显示名称为必填项", "error");
                return;
            }

            if (!isEdit && this.config.models && this.config.models[modelId]) {
                this.showToast("该模型ID已存在", "error");
                return;
            }

            // Collect params from UI
            const collectedParams = { basic: {}, advanced: {} };
            ["basic", "advanced"].forEach(group => {
                const list = modal.querySelector(`.batchbox-param-list[data-group="${group}"]`);
                list.querySelectorAll(".batchbox-param-item").forEach(item => {
                    let name = item.querySelector(".param-name").value.trim();
                    if (!name) return;

                    // Parse name==api_name format
                    let apiName = null;
                    if (name.includes("==")) {
                        const [uiName, apn] = name.split("==").map(s => s.trim());
                        name = uiName;
                        apiName = apn;
                    }

                    const paramType = item.querySelector(".param-type").value;
                    const paramData = {
                        type: paramType,
                        default: item.querySelector(".param-default").value
                    };

                    // Store api_name if different from name
                    if (apiName && apiName !== name) {
                        paramData.api_name = apiName;
                    }

                    // Collect options for select type (support value=label format)
                    if (paramType === "select") {
                        const optionsInput = item.querySelector(".param-options");
                        if (optionsInput && optionsInput.value.trim()) {
                            paramData.options = optionsInput.value.split(",").map(o => {
                                const trimmed = o.trim();
                                if (trimmed.includes("==")) {
                                    const [value, label] = trimmed.split("==").map(s => s.trim());
                                    return { value, label };
                                }
                                return { value: trimmed, label: trimmed };
                            }).filter(o => o.value);
                        }
                    }

                    collectedParams[group][name] = paramData;
                });
            });

            // Collect endpoints from UI
            const collectedEndpoints = [];
            let endpointError = false;

            modal.querySelectorAll(".batchbox-endpoint-card").forEach((card, idx) => {
                const text2imgEndpoint = card.querySelector(".ep-text2img").value.trim();
                const img2imgEndpoint = card.querySelector(".ep-img2img").value.trim();

                // Validate: at least one endpoint must be configured
                if (!text2imgEndpoint && !img2imgEndpoint) {
                    endpointError = true;
                    return;
                }

                // Get original endpoint config to preserve payload_template, response_path, etc.
                const originalEndpoint = currentEndpoints[idx] || {};
                const originalModes = originalEndpoint.modes || {};

                const modes = {};

                // Add text2img mode - preserve original mode config, only update endpoint
                if (text2imgEndpoint) {
                    const originalText2img = originalModes.text2img || {};
                    modes.text2img = {
                        ...originalText2img,  // Preserve payload_template, response_path, etc.
                        endpoint: text2imgEndpoint,
                        method: originalText2img.method || "POST",
                        content_type: originalText2img.content_type || "application/json",
                        response_type: originalText2img.response_type || "sync"
                    };
                }

                // Add img2img mode - preserve original mode config, only update endpoint
                if (img2imgEndpoint) {
                    const originalImg2img = originalModes.img2img || {};
                    const img2imgConfig = {
                        ...originalImg2img,  // Preserve payload_template, response_path, etc.
                        endpoint: img2imgEndpoint,
                        method: originalImg2img.method || "POST",
                        content_type: originalImg2img.content_type || "multipart/form-data",
                        response_type: originalImg2img.response_type || "sync"
                    };
                    // Add file format settings if specified
                    const fileFormat = card.querySelector(".ep-file-format")?.value;
                    const fileField = card.querySelector(".ep-file-field")?.value.trim();
                    if (fileFormat) img2imgConfig.file_format = fileFormat;
                    if (fileField) img2imgConfig.file_field = fileField;
                    const useOssCache = card.querySelector(".ep-use-oss-cache")?.checked;
                    img2imgConfig.use_oss_cache = !!useOssCache;

                    modes.img2img = img2imgConfig;
                }

                // Parse extra_params JSON if provided
                let extraParams = null;
                const extraParamsText = card.querySelector(".ep-extra-params")?.value.trim();
                if (extraParamsText) {
                    try {
                        extraParams = JSON.parse(extraParamsText);
                    } catch (e) {
                        console.warn("[API Manager] Invalid extra_params JSON:", e);
                        this.showToast("额外请求参数 JSON 格式无效", "error");
                        endpointError = true;
                        return;
                    }
                }

                const endpointData = {
                    display_name: card.querySelector(".ep-display-name").value.trim(),
                    provider: card.querySelector(".ep-provider").value,
                    priority: parseInt(card.querySelector(".ep-priority").value) || 1,
                    model_name: card.querySelector(".ep-model-name").value.trim(),
                    modes: modes
                };

                // Add api_format if not default (openai)
                const apiFormat = card.querySelector(".ep-api-format")?.value;
                if (apiFormat && apiFormat !== "openai") {
                    endpointData.api_format = apiFormat;
                }

                // Add prompt_prefix if provided
                const promptPrefix = card.querySelector(".ep-prompt-prefix")?.value.trim();
                if (promptPrefix) {
                    endpointData.prompt_prefix = promptPrefix;
                }

                if (extraParams) {
                    endpointData.extra_params = extraParams;
                }
                collectedEndpoints.push(endpointData);
            });

            if (endpointError) {
                this.showToast("每个端点配置至少需要填写一个端点路径", "error");
                return;
            }

            if (!this.config.models) this.config.models = {};
            this.config.models[modelId] = {
                display_name: displayName,
                category: category,
                description: modal.querySelector('[name="description"]').value,
                show_seed_widget: modal.querySelector('[name="show_seed_widget"]').checked,
                parameter_schema: collectedParams,
                api_endpoints: collectedEndpoints
            };

            if (isEdit && modelId !== editName) {
                delete this.config.models[editName];
            }

            this.renderModels(this.panels["models"]);
            this.showToast(isEdit ? "模型已更新" : "模型已添加", "success");
            overlay.remove();
        };
    }

    // ==================== PRESETS ====================
    renderPresets(container) {
        container.innerHTML = "";

        const header = document.createElement("div");
        header.className = "batchbox-panel-header";
        header.innerHTML = `<h3>预设管理</h3>`;

        const addBtn = document.createElement("button");
        addBtn.className = "batchbox-btn btn-success";
        addBtn.innerText = "+ 添加预设";
        addBtn.onclick = () => this.showPresetForm();
        header.appendChild(addBtn);
        container.appendChild(header);

        const table = document.createElement("table");
        table.className = "batchbox-table";
        table.innerHTML = `<thead><tr><th>名称</th><th>供应商</th><th>模型</th><th>动态节点</th><th>操作</th></tr></thead>`;
        const tbody = document.createElement("tbody");

        const presets = this.config.presets || {};
        for (const [name, data] of Object.entries(presets)) {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${name}</strong></td>
                <td>${data.provider || ""}</td>
                <td>${data.model_name || ""}</td>
                <td>${data.dynamic_node ? "✅" : "❌"}</td>
                <td></td>
            `;
            const actionCell = tr.querySelector("td:last-child");

            const editBtn = document.createElement("button");
            editBtn.className = "batchbox-btn btn-edit";
            editBtn.innerText = "编辑";
            editBtn.onclick = () => this.showPresetForm(name);
            actionCell.appendChild(editBtn);

            const delBtn = document.createElement("button");
            delBtn.className = "batchbox-btn btn-danger";
            delBtn.innerText = "删除";
            delBtn.onclick = () => this.confirmDelete("preset", name);
            actionCell.appendChild(delBtn);

            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        container.appendChild(table);

        if (Object.keys(presets).length === 0) {
            container.innerHTML += `<p class="batchbox-empty">暂无预设，点击上方按钮添加。</p>`;
        }
    }

    showPresetForm(editName = null) {
        const isEdit = editName !== null;
        const existing = isEdit ? this.config.presets[editName] : {};
        const providerOptions = Object.keys(this.config.providers || {});
        const hasDynamicNode = !!existing.dynamic_node;

        this.showAdvancedPresetModal({
            title: isEdit ? `编辑预设: ${editName}` : "添加新预设",
            existing,
            editName,
            isEdit,
            providerOptions,
            hasDynamicNode,
            onSubmit: (data) => {
                if (!data.name || !data.provider || !data.model_name) {
                    this.showToast("名称、供应商和模型名称为必填项", "error");
                    return false;
                }
                if (!isEdit && this.config.presets[data.name]) {
                    this.showToast("该名称已存在", "error");
                    return false;
                }

                const presetData = {
                    description: data.description || undefined,
                    provider: data.provider,
                    model_name: data.model_name,
                    modes: {
                        text2img: {
                            endpoint: data.endpoint || "/v1/images/generations",
                            response_type: data.response_type || "sync"
                        }
                    }
                };

                // Handle dynamic node
                if (data.enable_dynamic_node) {
                    presetData.dynamic_node = {
                        class_name: data.dynamic_class_name || `DynamicNode_${data.name}`,
                        display_name: data.dynamic_display_name || `🍌 ${data.name}`,
                        parameters: data.dynamic_parameters || { required: {}, optional: {} }
                    };
                }

                this.config.presets[data.name] = presetData;
                if (isEdit && data.name !== editName) {
                    delete this.config.presets[editName];
                }
                this.renderPresets(this.panels["presets"]);
                this.showToast(isEdit ? "预设已更新" : "预设已添加", "success");
                return true;
            }
        });
    }

    showAdvancedPresetModal({ title, existing, editName, isEdit, providerOptions, hasDynamicNode, onSubmit }) {
        const overlay = document.createElement("div");
        overlay.className = "batchbox-submodal-overlay";

        const modal = document.createElement("div");
        modal.className = "batchbox-submodal batchbox-advanced-modal";

        const dynNode = existing.dynamic_node || {};
        const dynParams = dynNode.parameters || { required: {}, optional: {} };

        modal.innerHTML = `
            <div class="batchbox-submodal-header"><h4>${title}</h4></div>
            <div class="batchbox-submodal-body batchbox-tabs-container">
                <div class="batchbox-form-tabs">
                    <button class="batchbox-form-tab active" data-tab="basic">基础设置</button>
                    <button class="batchbox-form-tab" data-tab="dynamic">动态节点</button>
                </div>
                
                <div class="batchbox-form-tab-content active" data-tab="basic">
                    <div class="batchbox-form-group">
                        <label>预设名称 *</label>
                        <input type="text" name="name" value="${editName || ""}" class="batchbox-form-input" ${isEdit ? "disabled" : ""}>
                    </div>
                    <div class="batchbox-form-row">
                        <div class="batchbox-form-group">
                            <label>供应商 *</label>
                            <select name="provider" class="batchbox-form-input">
                                ${providerOptions.length === 0 ? '<option value="">请先添加供应商</option>' : providerOptions.map(p => `<option value="${p}" ${p === existing.provider ? "selected" : ""}>${p}</option>`).join("")}
                            </select>
                        </div>
                        <div class="batchbox-form-group">
                            <label>模型名称 *</label>
                            <input type="text" name="model_name" value="${existing.model_name || ""}" class="batchbox-form-input" placeholder="nano-banana-2">
                        </div>
                    </div>
                    <div class="batchbox-form-group">
                        <label>描述</label>
                        <input type="text" name="description" value="${existing.description || ""}" class="batchbox-form-input" placeholder="可选描述">
                    </div>
                    <div class="batchbox-form-row">
                        <div class="batchbox-form-group">
                            <label>Endpoint</label>
                            <input type="text" name="endpoint" value="${existing.modes?.text2img?.endpoint || "/v1/images/generations"}" class="batchbox-form-input">
                        </div>
                        <div class="batchbox-form-group">
                            <label>响应类型</label>
                            <select name="response_type" class="batchbox-form-input">
                                <option value="sync" ${existing.modes?.text2img?.response_type === "sync" ? "selected" : ""}>sync</option>
                                <option value="async" ${existing.modes?.text2img?.response_type === "async" ? "selected" : ""}>async</option>
                            </select>
                        </div>
                    </div>
                </div>
                
                <div class="batchbox-form-tab-content" data-tab="dynamic">
                    <div class="batchbox-form-group">
                        <label class="batchbox-checkbox-label">
                            <input type="checkbox" name="enable_dynamic_node" ${hasDynamicNode ? "checked" : ""}>
                            <span>启用动态节点</span>
                        </label>
                        <p class="batchbox-hint">启用后将在 ComfyUI 中生成独立的节点</p>
                    </div>
                    
                    <div class="batchbox-dynamic-fields" style="display: ${hasDynamicNode ? "block" : "none"}">
                        <div class="batchbox-form-row">
                            <div class="batchbox-form-group">
                                <label>类名 (Class Name)</label>
                                <input type="text" name="dynamic_class_name" value="${dynNode.class_name || ""}" class="batchbox-form-input" placeholder="MyDynamicNode">
                            </div>
                            <div class="batchbox-form-group">
                                <label>显示名称</label>
                                <input type="text" name="dynamic_display_name" value="${dynNode.display_name || ""}" class="batchbox-form-input" placeholder="🍌 My Node">
                            </div>
                        </div>
                        
                        <!-- Parameter Editor Mode Toggle -->
                        <div class="batchbox-param-mode-toggle">
                            <button class="batchbox-btn btn-mode active" data-mode="visual">📋 可视化编辑</button>
                            <button class="batchbox-btn btn-mode" data-mode="json">📝 JSON 编辑</button>
                        </div>
                        
                        <!-- Visual Parameter Editor -->
                        <div class="batchbox-param-editor" data-mode="visual">
                            <div class="batchbox-param-section">
                                <div class="batchbox-param-section-header">
                                    <span>必填参数 (Required)</span>
                                    <button class="batchbox-btn btn-success btn-sm btn-add-param" data-category="required">+ 添加</button>
                                </div>
                                <div class="batchbox-param-list" data-category="required"></div>
                            </div>
                            <div class="batchbox-param-section">
                                <div class="batchbox-param-section-header">
                                    <span>可选参数 (Optional)</span>
                                    <button class="batchbox-btn btn-success btn-sm btn-add-param" data-category="optional">+ 添加</button>
                                </div>
                                <div class="batchbox-param-list" data-category="optional"></div>
                            </div>
                        </div>
                        
                        <!-- JSON Editor (Hidden by default) -->
                        <div class="batchbox-param-editor" data-mode="json" style="display: none;">
                            <div class="batchbox-form-group">
                                <label>参数配置 (JSON)</label>
                                <textarea name="dynamic_parameters" class="batchbox-form-input batchbox-params-textarea">${JSON.stringify(dynParams, null, 2)}</textarea>
                                <p class="batchbox-hint">格式: { "required": {...}, "optional": {...} }</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="batchbox-submodal-footer">
                <button class="batchbox-btn btn-cancel">取消</button>
                <button class="batchbox-btn btn-primary">保存</button>
            </div>
        `;

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Tab switching
        modal.querySelectorAll(".batchbox-form-tab").forEach(tab => {
            tab.onclick = () => {
                modal.querySelectorAll(".batchbox-form-tab").forEach(t => t.classList.remove("active"));
                modal.querySelectorAll(".batchbox-form-tab-content").forEach(c => c.classList.remove("active"));
                tab.classList.add("active");
                modal.querySelector(`.batchbox-form-tab-content[data-tab="${tab.dataset.tab}"]`).classList.add("active");
            };
        });

        // Dynamic node toggle
        const dynamicCheckbox = modal.querySelector('[name="enable_dynamic_node"]');
        const dynamicFields = modal.querySelector('.batchbox-dynamic-fields');
        dynamicCheckbox.onchange = () => {
            dynamicFields.style.display = dynamicCheckbox.checked ? "block" : "none";
        };

        // ===== Visual Parameter Editor Logic =====
        let currentParams = JSON.parse(JSON.stringify(dynParams)); // Deep copy
        let isVisualMode = true;

        // Mode toggle
        modal.querySelectorAll(".btn-mode").forEach(btn => {
            btn.onclick = () => {
                const mode = btn.dataset.mode;
                modal.querySelectorAll(".btn-mode").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");

                modal.querySelectorAll(".batchbox-param-editor").forEach(ed => {
                    ed.style.display = ed.dataset.mode === mode ? "block" : "none";
                });

                isVisualMode = mode === "visual";

                if (mode === "json") {
                    // Sync visual -> JSON
                    modal.querySelector('[name="dynamic_parameters"]').value = JSON.stringify(currentParams, null, 2);
                } else {
                    // Sync JSON -> visual
                    try {
                        currentParams = JSON.parse(modal.querySelector('[name="dynamic_parameters"]').value);
                        renderParamLists();
                    } catch (e) { }
                }
            };
        });

        const renderParamLists = () => {
            ["required", "optional"].forEach(cat => {
                const list = modal.querySelector(`.batchbox-param-list[data-category="${cat}"]`);
                list.innerHTML = "";
                const params = currentParams[cat] || {};

                Object.entries(params).forEach(([name, config]) => {
                    const item = document.createElement("div");
                    item.className = "batchbox-param-item";

                    const typeValue = Array.isArray(config.type) ? "select" : (config.type || "STRING");
                    const optionsValue = Array.isArray(config.type) ? config.type.join(", ") : "";

                    item.innerHTML = `
                        <div class="param-row">
                            <input type="text" class="param-name" value="${name}" placeholder="参数名">
                            <select class="param-type">
                                <option value="STRING" ${typeValue === "STRING" ? "selected" : ""}>字符串</option>
                                <option value="INT" ${typeValue === "INT" ? "selected" : ""}>整数</option>
                                <option value="FLOAT" ${typeValue === "FLOAT" ? "selected" : ""}>浮点</option>
                                <option value="BOOLEAN" ${typeValue === "BOOLEAN" ? "selected" : ""}>布尔</option>
                                <option value="select" ${typeValue === "select" ? "selected" : ""}>下拉</option>
                            </select>
                            <input type="text" class="param-default" value="${config.default !== undefined ? config.default : ""}" placeholder="默认值">
                        </div>
                        <button class="batchbox-btn btn-danger btn-sm btn-del-param">×</button>
                        <input type="text" class="param-options" value="${optionsValue}" placeholder="下拉选项 (逗号分隔)" style="display: ${typeValue === "select" ? "block" : "none"}; grid-column: 1;">
                    `;

                    // Type change handler
                    item.querySelector(".param-type").onchange = (e) => {
                        const optInput = item.querySelector(".param-options");
                        optInput.style.display = e.target.value === "select" ? "block" : "none";
                        syncFromVisual();
                    };

                    // Other input handlers
                    item.querySelectorAll("input").forEach(inp => inp.oninput = syncFromVisual);

                    // Delete handler
                    item.querySelector(".btn-del-param").onclick = () => {
                        item.remove();
                        syncFromVisual();
                    };

                    list.appendChild(item);
                });
            });
        };

        const syncFromVisual = () => {
            currentParams = { required: {}, optional: {} };
            ["required", "optional"].forEach(cat => {
                const list = modal.querySelector(`.batchbox-param-list[data-category="${cat}"]`);
                list.querySelectorAll(".batchbox-param-item").forEach(item => {
                    const name = item.querySelector(".param-name").value.trim();
                    if (!name) return;

                    const typeSelect = item.querySelector(".param-type").value;
                    const defaultVal = item.querySelector(".param-default").value;
                    const optionsStr = item.querySelector(".param-options").value;

                    let config = {};
                    if (typeSelect === "select") {
                        config.type = optionsStr.split(",").map(s => s.trim()).filter(s => s);
                    } else {
                        config.type = typeSelect;
                    }

                    if (defaultVal !== "") {
                        if (typeSelect === "INT") config.default = parseInt(defaultVal) || 0;
                        else if (typeSelect === "FLOAT") config.default = parseFloat(defaultVal) || 0;
                        else if (typeSelect === "BOOLEAN") config.default = defaultVal.toLowerCase() === "true";
                        else config.default = defaultVal;
                    }

                    // Special handling for STRING multiline
                    if (typeSelect === "STRING" && name.toLowerCase().includes("prompt")) {
                        config.multiline = true;
                    }

                    currentParams[cat][name] = config;
                });
            });
        };

        // Add param buttons
        modal.querySelectorAll(".btn-add-param").forEach(btn => {
            btn.onclick = () => {
                const cat = btn.dataset.category;
                const newName = `param_${Date.now() % 1000}`;
                currentParams[cat][newName] = { type: "STRING", default: "" };
                renderParamLists();
            };
        });

        // Initial render
        renderParamLists();

        modal.querySelector(".btn-cancel").onclick = () => overlay.remove();
        modal.querySelector(".btn-primary").onclick = () => {
            let dynamicParams = { required: {}, optional: {} };

            if (isVisualMode) {
                syncFromVisual();
                dynamicParams = currentParams;
            } else {
                try {
                    const paramsText = modal.querySelector('[name="dynamic_parameters"]').value;
                    if (paramsText.trim()) {
                        dynamicParams = JSON.parse(paramsText);
                    }
                } catch (e) {
                    this.showToast("动态节点参数 JSON 格式错误", "error");
                    return;
                }
            }

            const formData = {
                name: modal.querySelector('[name="name"]').value,
                provider: modal.querySelector('[name="provider"]').value,
                model_name: modal.querySelector('[name="model_name"]').value,
                description: modal.querySelector('[name="description"]').value,
                endpoint: modal.querySelector('[name="endpoint"]').value,
                response_type: modal.querySelector('[name="response_type"]').value,
                enable_dynamic_node: dynamicCheckbox.checked,
                dynamic_class_name: modal.querySelector('[name="dynamic_class_name"]').value,
                dynamic_display_name: modal.querySelector('[name="dynamic_display_name"]').value,
                dynamic_parameters: dynamicParams
            };

            if (onSubmit(formData)) {
                overlay.remove();
            }
        };
    }

    // ==================== SAVE SETTINGS ====================
    async renderSaveSettings(container) {
        container.innerHTML = "";

        // ========== Node Display Settings Section ==========
        const nodeSection = document.createElement("div");
        nodeSection.className = "batchbox-settings-section";
        nodeSection.innerHTML = `<h3>📐 节点显示设置</h3><p style="color: #aaa;">配置节点的默认显示样式。</p>`;

        // Load node settings
        let nodeSettings = { default_width: 500 };
        try {
            const resp = await api.fetchApi("/api/batchbox/node-settings");
            const data = await resp.json();
            nodeSettings = data.node_settings || nodeSettings;
        } catch (e) {
            console.error("Failed to load node settings:", e);
        }

        const nodeForm = document.createElement("div");
        nodeForm.className = "batchbox-node-settings-form";
        nodeForm.innerHTML = `
            <div class="batchbox-form-group">
                <label>节点默认宽度 (px)</label>
                <div class="batchbox-input-hint">新建节点时使用的初始宽度</div>
                <div class="batchbox-slider-row">
                    <input type="range" id="node-width-slider" class="batchbox-slider" min="300" max="1200" step="10" value="${nodeSettings.default_width}">
                    <input type="number" id="node-width-input" class="batchbox-input-sm" min="300" max="1200" value="${nodeSettings.default_width}" style="width: 80px;">
                </div>
            </div>
            
            <div class="batchbox-form-group">
                <label class="batchbox-checkbox-label">
                    <input type="checkbox" id="node-bypass-queue" ${nodeSettings.bypass_queue_prompt !== false ? 'checked' : ''}>
                    <span>拦截全局 Queue Prompt</span>
                </label>
                <div class="batchbox-input-hint">开启后，BatchBox 节点仅通过节点上的"开始生成"按钮执行，不参与全局 Queue Prompt</div>
            </div>
            
            <div class="batchbox-form-group">
                <label class="batchbox-checkbox-label">
                    <input type="checkbox" id="node-canvas-menu" ${nodeSettings.show_in_canvas_menu !== false ? 'checked' : ''}>
                    <span>右键菜单快捷添加</span>
                </label>
                <div class="batchbox-input-hint">开启后，在画布空白处右键可直接添加 BatchBox 节点</div>
            </div>
            
            <div class="batchbox-form-group">
                <label class="batchbox-checkbox-label">
                    <input type="checkbox" id="node-hash-check" ${nodeSettings.smart_cache_hash_check !== false ? 'checked' : ''}>
                    <span>参数变化检测</span>
                </label>
                <div class="batchbox-input-hint">开启后，修改节点参数会触发重新生成；关闭后仅按钮触发生成</div>
            </div>
            
            <div class="batchbox-form-group">
                <label>自动端点模式</label>
                <div class="batchbox-input-hint">未手动选择端点时，自动模式的端点分配策略</div>
                <select id="node-endpoint-mode" class="batchbox-select" style="width: 100%; padding: 8px; background: #333; color: #eee; border: 1px solid #555; border-radius: 6px;">
                    <option value="priority" ${nodeSettings.auto_endpoint_mode === 'priority' ? 'selected' : ''}>🎯 优先级（始终使用排名第一的端点）</option>
                    <option value="round_robin" ${nodeSettings.auto_endpoint_mode !== 'priority' ? 'selected' : ''}>🔄 轮询（批量时轮流使用所有端点）</option>
                </select>
            </div>
            
            <div class="batchbox-form-group">
                <label>预览模式</label>
                <div class="batchbox-input-hint">生成多张图片时，节点预览的加载方式</div>
                <select id="node-preview-mode" class="batchbox-select" style="width: 100%; padding: 8px; background: #333; color: #eee; border: 1px solid #555; border-radius: 6px;">
                    <option value="progressive" ${nodeSettings.preview_mode !== 'wait_all' ? 'selected' : ''}>🖼️ 逐张载入（完成一张显示一张）</option>
                    <option value="wait_all" ${nodeSettings.preview_mode === 'wait_all' ? 'selected' : ''}>📷 全部完成后载入</option>
                </select>
            </div>
            
            <div class="batchbox-form-actions">
                <button class="batchbox-btn btn-primary" id="save-node-settings-btn">💾 保存节点设置</button>
            </div>
        `;
        nodeSection.appendChild(nodeForm);
        container.appendChild(nodeSection);

        // Sync slider and input
        const widthSlider = container.querySelector("#node-width-slider");
        const widthInput = container.querySelector("#node-width-input");
        widthSlider.oninput = () => { widthInput.value = widthSlider.value; };
        widthInput.oninput = () => {
            const val = Math.min(1200, Math.max(300, parseInt(widthInput.value) || 500));
            widthSlider.value = val;
        };

        // Save node settings button
        container.querySelector("#save-node-settings-btn").onclick = async () => {
            const newWidth = parseInt(widthInput.value) || 500;
            const bypassQueuePrompt = container.querySelector("#node-bypass-queue").checked;
            const showInCanvasMenu = container.querySelector("#node-canvas-menu").checked;
            const smartCacheHashCheck = container.querySelector("#node-hash-check").checked;
            const autoEndpointMode = container.querySelector("#node-endpoint-mode").value;
            const previewMode = container.querySelector("#node-preview-mode").value;
            const newNodeSettings = {
                default_width: newWidth,
                bypass_queue_prompt: bypassQueuePrompt,
                show_in_canvas_menu: showInCanvasMenu,
                smart_cache_hash_check: smartCacheHashCheck,
                auto_endpoint_mode: autoEndpointMode,
                preview_mode: previewMode
            };
            try {
                const resp = await api.fetchApi("/api/batchbox/node-settings", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(newNodeSettings),
                });
                if (resp.ok) {
                    // IMPORTANT: Sync to this.config so main Save button doesn't overwrite
                    this.config.node_settings = { ...this.config.node_settings, ...newNodeSettings };
                    this.showToast("节点设置已保存！", "success");
                    // Notify dynamic_params.js to reload settings
                    window.dispatchEvent(new CustomEvent("batchbox:node-settings-changed"));
                } else {
                    throw new Error("保存失败");
                }
            } catch (e) {
                this.showToast("保存失败: " + e.message, "error");
            }
        };

        // ========== Upscale Model Settings Section ==========
        const upscaleDivider = document.createElement("hr");
        upscaleDivider.style.cssText = "margin: 30px 0; border: none; border-top: 1px solid #444;";
        container.appendChild(upscaleDivider);

        const upscaleSection = document.createElement("div");
        upscaleSection.className = "batchbox-settings-section";
        upscaleSection.innerHTML = `<h3>🔍 高清放大模型设置</h3><p style="color: #aaa;">配置高斯模糊放大节点使用的 AI 模型。</p>`;

        const upscaleForm = document.createElement("div");
        upscaleForm.className = "batchbox-upscale-settings-form";

        // Load presets and upscale settings
        let upscaleModel = "";
        let upscaleEndpoint = "";
        let savedDefaultParams = {};
        try {
            const upscaleResp = await api.fetchApi("/api/batchbox/upscale-settings");
            if (upscaleResp.ok) {
                const upscaleData = await upscaleResp.json();
                upscaleModel = upscaleData.upscale_settings?.model || "";
                upscaleEndpoint = upscaleData.upscale_settings?.endpoint || "";
                savedDefaultParams = upscaleData.upscale_settings?.default_params || {};
            }
        } catch (e) {
            console.error("Failed to load upscale settings:", e);
        }

        // Build model options from the config
        const models = this.config.models || {};
        let presetOptions = '<option value="">-- 选择预设模型 --</option>';
        for (const [name, model] of Object.entries(models)) {
            const selected = name === upscaleModel ? "selected" : "";
            const displayName = model.display_name || name;
            presetOptions += `<option value="${name}" ${selected}>${displayName}</option>`;
        }

        upscaleForm.innerHTML = `
            <div class="batchbox-form-group">
                <label>放大模型</label>
                <div class="batchbox-input-hint">选择用于高斯模糊放大的预设模型（与图片生成节点使用相同的预设列表）</div>
                <select id="upscale-model-select" class="batchbox-select">${presetOptions}</select>
            </div>
            <div class="batchbox-form-group" id="upscale-endpoint-group" style="display:none;">
                <label>端点</label>
                <div class="batchbox-input-hint">选择该模型使用的 API 端点</div>
                <select id="upscale-endpoint-select" class="batchbox-select"></select>
            </div>
            <div id="upscale-params-container"></div>
            <div class="batchbox-form-actions">
                <button class="batchbox-btn btn-primary" id="save-upscale-settings-btn">💾 保存放大模型设置</button>
            </div>
        `;
        upscaleSection.appendChild(upscaleForm);
        container.appendChild(upscaleSection);

        // Render endpoint options for a given model
        const renderUpscaleEndpoints = (modelName) => {
            const endpointGroup = container.querySelector("#upscale-endpoint-group");
            const endpointSelect = container.querySelector("#upscale-endpoint-select");
            if (!modelName) {
                endpointGroup.style.display = "none";
                return;
            }

            const modelData = models[modelName];
            const endpoints = modelData?.api_endpoints || [];
            if (endpoints.length <= 1) {
                // Single or no endpoint — no need to show selector
                endpointGroup.style.display = "none";
                endpointSelect.innerHTML = "";
                return;
            }

            endpointGroup.style.display = "";
            const autoLabel = nodeSettings.auto_endpoint_mode === 'round_robin' ? '自动（轮询）' : '自动（优先级）';
            let options = `<option value="">${autoLabel}</option>`;
            for (const ep of endpoints) {
                const name = ep.display_name || ep.provider || "";
                const sel = name === upscaleEndpoint ? "selected" : "";
                options += `<option value="${name}" ${sel}>${name}</option>`;
            }
            endpointSelect.innerHTML = options;
        };

        // Render model parameters into the params container
        const renderUpscaleParams = (modelName) => {
            const paramsContainer = container.querySelector("#upscale-params-container");
            paramsContainer.innerHTML = "";
            if (!modelName) return;

            const modelData = models[modelName];
            if (!modelData?.parameter_schema) return;

            const schema = modelData.parameter_schema;
            const allParams = [];
            for (const [group, params] of Object.entries(schema)) {
                for (const [name, config] of Object.entries(params || {})) {
                    if (name === "prompt") continue;
                    allParams.push({ name, config, group });
                }
            }
            if (allParams.length === 0) return;

            const heading = document.createElement("div");
            heading.style.cssText = "margin: 16px 0 8px; color: #ccc; font-size: 13px; font-weight: 600;";
            heading.textContent = "默认发送参数";
            paramsContainer.appendChild(heading);

            const hint = document.createElement("div");
            hint.style.cssText = "margin-bottom: 10px; color: #888; font-size: 12px;";
            hint.textContent = "设置放大时默认附加的参数值，留空则不发送该参数";
            paramsContainer.appendChild(hint);

            for (const { name, config } of allParams) {
                const apiName = config.api_name || name;
                const savedVal = savedDefaultParams[apiName];
                const row = document.createElement("div");
                row.className = "batchbox-upscale-param-row";
                row.style.cssText = "display: flex; align-items: center; gap: 10px; margin-bottom: 6px;";

                const label = document.createElement("label");
                label.style.cssText = "width: 100px; color: #aaa; font-size: 12px; flex-shrink: 0;";
                label.textContent = name;
                row.appendChild(label);

                let input;
                if (config.type === "select" && Array.isArray(config.options)) {
                    input = document.createElement("select");
                    input.className = "batchbox-select";
                    input.style.cssText = "flex: 1;";
                    input.innerHTML = '<option value="">-- 不设置 --</option>';
                    for (const opt of config.options) {
                        const val = typeof opt === "object" ? opt.value : opt;
                        const lbl = typeof opt === "object" ? opt.label : opt;
                        const sel = String(savedVal ?? config.default) === String(val) ? "selected" : "";
                        input.innerHTML += `<option value="${val}" ${sel}>${lbl}</option>`;
                    }
                } else if (config.type === "boolean") {
                    input = document.createElement("select");
                    input.className = "batchbox-select";
                    input.style.cssText = "flex: 1;";
                    const curVal = String(savedVal ?? config.default);
                    input.innerHTML = `
                        <option value="">-- 不设置 --</option>
                        <option value="true" ${curVal === "true" ? "selected" : ""}>是</option>
                        <option value="false" ${curVal === "false" ? "selected" : ""}>否</option>
                    `;
                } else if (config.type === "number") {
                    input = document.createElement("input");
                    input.type = "number";
                    input.className = "batchbox-input";
                    input.style.cssText = "flex: 1;";
                    input.value = savedVal ?? config.default ?? "";
                    input.placeholder = "默认: " + (config.default ?? "");
                } else {
                    input = document.createElement("input");
                    input.type = "text";
                    input.className = "batchbox-input";
                    input.style.cssText = "flex: 1;";
                    input.value = savedVal ?? config.default ?? "";
                    input.placeholder = "默认: " + (config.default ?? "");
                }
                input.dataset.apiName = apiName;
                input.dataset.paramType = config.type || "string";
                row.appendChild(input);
                paramsContainer.appendChild(row);
            }
        };

        // Listen for model selection change
        container.querySelector("#upscale-model-select").addEventListener("change", (e) => {
            upscaleEndpoint = ""; // Reset endpoint when model changes
            renderUpscaleEndpoints(e.target.value);
            renderUpscaleParams(e.target.value);
        });

        // Initial render if model already selected
        if (upscaleModel) {
            renderUpscaleEndpoints(upscaleModel);
            renderUpscaleParams(upscaleModel);
        }

        // Save upscale settings button
        container.querySelector("#save-upscale-settings-btn").onclick = async () => {
            const selectedModel = container.querySelector("#upscale-model-select").value;
            const selectedEndpoint = container.querySelector("#upscale-endpoint-select")?.value || "";

            // Collect default params from the rendered param inputs
            const defaultParams = {};
            const paramInputs = container.querySelectorAll("#upscale-params-container [data-api-name]");
            for (const input of paramInputs) {
                const val = input.value;
                if (val !== "") {
                    defaultParams[input.dataset.apiName] = val;
                }
            }

            try {
                const resp = await api.fetchApi("/api/batchbox/upscale-settings", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ model: selectedModel, endpoint: selectedEndpoint, default_params: defaultParams }),
                });
                if (resp.ok) {
                    // IMPORTANT: Sync to this.config so "保存所有更改" doesn't overwrite
                    if (!this.config.upscale_settings) this.config.upscale_settings = {};
                    this.config.upscale_settings.model = selectedModel;
                    this.config.upscale_settings.endpoint = selectedEndpoint;
                    this.config.upscale_settings.default_params = defaultParams;
                    this.showToast("放大模型设置已保存！", "success");
                } else {
                    throw new Error("保存失败");
                }
            } catch (e) {
                this.showToast("保存失败: " + e.message, "error");
            }
        };

        // ========== Divider ==========
        const divider = document.createElement("hr");
        divider.style.cssText = "margin: 30px 0; border: none; border-top: 1px solid #444;";
        container.appendChild(divider);

        // ========== Auto Save Settings Section ==========
        const saveSection = document.createElement("div");
        saveSection.className = "batchbox-settings-section";
        saveSection.innerHTML = `<h3>📁 自动保存设置</h3><p style="color: #aaa;">配置生成图片的自动保存选项。</p>`;
        container.appendChild(saveSection);

        // Load current settings
        let settings = {};
        try {
            const resp = await api.fetchApi("/api/batchbox/save-settings");
            const data = await resp.json();
            settings = data.save_settings || {};
        } catch (e) {
            console.error("Failed to load save settings:", e);
        }

        const form = document.createElement("div");
        form.className = "batchbox-save-settings-form";
        form.innerHTML = `
            <div class="batchbox-form-group">
                <label class="batchbox-checkbox-label">
                    <input type="checkbox" id="save-enabled" ${settings.enabled !== false ? 'checked' : ''}>
                    <span>启用自动保存</span>
                </label>
            </div>
            
            <div class="batchbox-form-group">
                <label>保存目录</label>
                <div class="batchbox-input-hint">相对于 ComfyUI output 目录</div>
                <input type="text" id="save-output-dir" class="batchbox-input" value="${settings.output_dir || 'batchbox'}" placeholder="batchbox">
            </div>
            
            <div class="batchbox-form-row-inline">
                <div class="batchbox-form-group" style="flex:1">
                    <label>文件格式</label>
                    <select id="save-format" class="batchbox-select">
                        <option value="original" ${settings.format === 'original' ? 'selected' : ''}>保持原格式</option>
                        <option value="png" ${settings.format === 'png' || !settings.format ? 'selected' : ''}>PNG (无损)</option>
                        <option value="jpg" ${settings.format === 'jpg' ? 'selected' : ''}>JPG</option>
                        <option value="webp" ${settings.format === 'webp' ? 'selected' : ''}>WebP</option>
                    </select>
                </div>
                <div class="batchbox-form-group" id="fallback-row" style="flex:1;${settings.format !== 'original' ? 'display:none' : ''}">
                    <label>默认格式</label>
                    <select id="save-fallback" class="batchbox-select">
                        <option value="png" ${settings.fallback_format === 'png' || !settings.fallback_format ? 'selected' : ''}>PNG</option>
                        <option value="jpg" ${settings.fallback_format === 'jpg' ? 'selected' : ''}>JPG</option>
                        <option value="webp" ${settings.fallback_format === 'webp' ? 'selected' : ''}>WebP</option>
                    </select>
                </div>
                <div class="batchbox-form-group" id="quality-row" style="flex:1;${settings.format === 'png' || settings.format === 'original' ? 'display:none' : ''}">
                    <label>质量</label>
                    <input type="number" id="save-quality" class="batchbox-input" min="1" max="100" value="${settings.quality || 95}">
                </div>
            </div>
            
            <div class="batchbox-form-group">
                <label>命名格式</label>
                <input type="text" id="save-pattern" class="batchbox-input" value="${settings.naming_pattern || '{model}_{timestamp}_{seed}'}" placeholder="{model}_{timestamp}_{seed}">
                <div class="batchbox-input-hint">可用变量: {model} {timestamp} {date} {time} {seed} {batch} {uuid} {prompt}</div>
            </div>
            
            <div class="batchbox-form-group">
                <label>文件名预览</label>
                <span id="filename-preview" class="batchbox-preview-text">loading...</span>
            </div>
            
            <div class="batchbox-form-group">
                <label class="batchbox-checkbox-label">
                    <input type="checkbox" id="save-date-subfolder" ${settings.create_date_subfolder !== false ? 'checked' : ''}>
                    <span>按日期创建子文件夹</span>
                </label>
            </div>
            
            <div class="batchbox-form-group">
                <label class="batchbox-checkbox-label">
                    <input type="checkbox" id="save-include-prompt" ${settings.include_prompt ? 'checked' : ''}>
                    <span>在文件名中包含 Prompt</span>
                </label>
                <div id="prompt-length-row" class="batchbox-sub-option" style="${settings.include_prompt ? '' : 'display:none'}">
                    <label>最大长度:</label>
                    <input type="number" id="save-prompt-length" class="batchbox-input-sm" min="10" max="200" value="${settings.prompt_max_length || 50}">
                </div>
            </div>
            
            <div class="batchbox-form-actions">
                <button class="batchbox-btn btn-primary" id="save-settings-btn">💾 保存设置</button>
                <button class="batchbox-btn btn-secondary" id="reset-settings-btn">🔄 重置默认</button>
            </div>
        `;
        container.appendChild(form);

        // Event handlers
        const formatSelect = container.querySelector("#save-format");
        const qualityRow = container.querySelector("#quality-row");
        const fallbackRow = container.querySelector("#fallback-row");
        formatSelect.onchange = () => {
            const isOriginal = formatSelect.value === "original";
            const hideQuality = formatSelect.value === "png" || isOriginal;
            qualityRow.style.display = hideQuality ? "none" : "";
            fallbackRow.style.display = isOriginal ? "" : "none";
            this.updateFilenamePreview(container);
        };

        const patternInput = container.querySelector("#save-pattern");
        patternInput.oninput = () => this.updateFilenamePreview(container);

        const includePromptCheck = container.querySelector("#save-include-prompt");
        const promptLengthRow = container.querySelector("#prompt-length-row");
        includePromptCheck.onchange = () => {
            promptLengthRow.style.display = includePromptCheck.checked ? "" : "none";
            this.updateFilenamePreview(container);
        };

        // Save button
        container.querySelector("#save-settings-btn").onclick = async () => {
            const newSettings = {
                enabled: container.querySelector("#save-enabled").checked,
                output_dir: container.querySelector("#save-output-dir").value,
                format: container.querySelector("#save-format").value,
                fallback_format: container.querySelector("#save-fallback").value,
                quality: parseInt(container.querySelector("#save-quality").value) || 95,
                naming_pattern: container.querySelector("#save-pattern").value,
                create_date_subfolder: container.querySelector("#save-date-subfolder").checked,
                include_prompt: container.querySelector("#save-include-prompt").checked,
                prompt_max_length: parseInt(container.querySelector("#save-prompt-length").value) || 50,
            };

            try {
                const resp = await api.fetchApi("/api/batchbox/save-settings", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(newSettings),
                });
                if (resp.ok) {
                    this.showToast("保存设置已更新！", "success");
                } else {
                    throw new Error("保存失败");
                }
            } catch (e) {
                this.showToast("保存失败: " + e.message, "error");
            }
        };

        // Reset button
        container.querySelector("#reset-settings-btn").onclick = () => {
            container.querySelector("#save-enabled").checked = true;
            container.querySelector("#save-output-dir").value = "batchbox";
            container.querySelector("#save-format").value = "original";
            container.querySelector("#save-fallback").value = "png";
            container.querySelector("#save-quality").value = "95";
            qualityRow.style.display = "none";
            fallbackRow.style.display = "";
            container.querySelector("#save-pattern").value = "{model}_{timestamp}_{seed}";
            container.querySelector("#save-date-subfolder").checked = true;
            container.querySelector("#save-include-prompt").checked = false;
            container.querySelector("#save-prompt-length").value = "50";
            promptLengthRow.style.display = "none";
            this.updateFilenamePreview(container);
        };

        // Initial preview
        this.updateFilenamePreview(container);
    }

    async updateFilenamePreview(container) {
        const previewSpan = container.querySelector("#filename-preview");
        if (!previewSpan) return;

        const settings = {
            naming_pattern: container.querySelector("#save-pattern")?.value || "{model}_{timestamp}_{seed}",
            format: container.querySelector("#save-format")?.value || "png",
            include_prompt: container.querySelector("#save-include-prompt")?.checked || false,
            prompt_max_length: parseInt(container.querySelector("#save-prompt-length")?.value) || 50,
        };

        try {
            const resp = await api.fetchApi("/api/batchbox/save-settings/preview", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ settings }),
            });
            const data = await resp.json();
            previewSpan.textContent = data.preview || "preview_error";
        } catch (e) {
            previewSpan.textContent = "preview_error";
        }
    }

    // ==================== RAW JSON ====================
    renderRaw(container) {
        container.innerHTML = `<h3>原始 JSON 配置</h3><p style="color: #aaa;">直接编辑配置，注意 JSON 格式正确性。</p>`;

        const textarea = document.createElement("textarea");
        textarea.className = "batchbox-raw-textarea";
        textarea.value = JSON.stringify(this.config, null, 2);
        textarea.oninput = () => {
            try {
                this.config = JSON.parse(textarea.value);
                textarea.classList.remove("error");
            } catch (e) {
                textarea.classList.add("error");
            }
        };
        container.appendChild(textarea);
    }

    // ==================== DIALOGS ====================
    confirmDelete(type, name) {
        const typeLabels = { provider: "供应商", preset: "预设", model: "模型" };
        const typeLabel = typeLabels[type] || type;
        this.showConfirmModal({
            title: `删除 ${typeLabel}`,
            message: `确定要删除 ${typeLabel} "${name}" 吗？此操作无法撤销。`,
            onConfirm: () => {
                if (type === "provider") {
                    delete this.config.providers[name];
                    this.renderProviders(this.panels["providers"]);
                } else if (type === "model") {
                    delete this.config.models[name];
                    this.renderModels(this.panels["models"]);
                } else {
                    delete this.config.presets[name];
                    this.renderPresets(this.panels["presets"]);
                }
                this.showToast(`${typeLabel} "${name}" 已删除`, "success");
            }
        });
    }

    showConfirmModal({ title, message, onConfirm }) {
        const overlay = document.createElement("div");
        overlay.className = "batchbox-submodal-overlay";

        const modal = document.createElement("div");
        modal.className = "batchbox-submodal";
        modal.innerHTML = `
            <div class="batchbox-submodal-header"><h4>${title}</h4></div>
            <div class="batchbox-submodal-body"><p>${message}</p></div>
            <div class="batchbox-submodal-footer">
                <button class="batchbox-btn btn-cancel">取消</button>
                <button class="batchbox-btn btn-danger">确认删除</button>
            </div>
        `;
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        modal.querySelector(".btn-cancel").onclick = () => overlay.remove();
        modal.querySelector(".btn-danger").onclick = () => {
            onConfirm();
            overlay.remove();
        };
    }

    showFormModal({ title, fields, onSubmit }) {
        const overlay = document.createElement("div");
        overlay.className = "batchbox-submodal-overlay";

        const modal = document.createElement("div");
        modal.className = "batchbox-submodal batchbox-form-modal";

        let fieldsHtml = fields.map(f => {
            // Divider for visual separation
            if (f.type === "divider") {
                return `<div class="batchbox-form-divider" style="border-top: 1px solid #444; margin: 16px 0 8px 0; padding-top: 8px;">
                    <span style="font-size: 11px; color: #888;">${f.label || ""}</span>
                </div>`;
            }
            if (f.type === "select") {
                // Support both string array and {value, label} object array
                const opts = f.options.map(o => {
                    const val = typeof o === "object" ? o.value : o;
                    const label = typeof o === "object" ? o.label : o;
                    const selected = val === f.value ? "selected" : "";
                    return `<option value="${val}" ${selected}>${label}</option>`;
                }).join("");
                return `<div class="batchbox-form-group">
                    <label>${f.label}${f.required ? " *" : ""}</label>
                    <select name="${f.name}" class="batchbox-form-input" ${f.disabled ? "disabled" : ""}>${opts}</select>
                </div>`;
            }
            // Password field with toggle button
            if (f.type === "password") {
                return `<div class="batchbox-form-group">
                    <label>${f.label}${f.required ? " *" : ""}</label>
                    <div style="position: relative; display: flex; gap: 4px;">
                        <input type="password" name="${f.name}" value="${f.value || ""}" 
                            placeholder="${f.placeholder || ""}" class="batchbox-form-input" style="flex: 1;" ${f.disabled ? "disabled" : ""}>
                        <button type="button" class="batchbox-btn btn-toggle-password" style="padding: 6px 10px; background: #333; border: 1px solid #555; min-width: 36px;" title="显示/隐藏">👁</button>
                    </div>
                </div>`;
            }
            return `<div class="batchbox-form-group">
                <label>${f.label}${f.required ? " *" : ""}</label>
                <input type="${f.type || "text"}" name="${f.name}" value="${f.value || ""}" 
                    placeholder="${f.placeholder || ""}" class="batchbox-form-input" ${f.disabled ? "disabled" : ""}>
            </div>`;
        }).join("");

        modal.innerHTML = `
            <div class="batchbox-submodal-header"><h4>${title}</h4></div>
            <div class="batchbox-submodal-body">${fieldsHtml}</div>
            <div class="batchbox-submodal-footer">
                <button class="batchbox-btn btn-cancel">取消</button>
                <button class="batchbox-btn btn-primary">保存</button>
            </div>
        `;
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Password toggle buttons
        modal.querySelectorAll(".btn-toggle-password").forEach(btn => {
            btn.onclick = () => {
                const input = btn.parentElement.querySelector("input");
                if (input.type === "password") {
                    input.type = "text";
                    btn.textContent = "🔒";
                    btn.title = "隐藏";
                } else {
                    input.type = "password";
                    btn.textContent = "👁";
                    btn.title = "显示";
                }
            };
        });

        modal.querySelector(".btn-cancel").onclick = () => overlay.remove();
        modal.querySelector(".btn-primary").onclick = () => {
            const formData = {};
            fields.forEach(f => {
                const el = modal.querySelector(`[name="${f.name}"]`);
                formData[f.name] = el ? el.value : "";
            });
            if (onSubmit(formData)) {
                overlay.remove();
            }
        };
    }
}

// ================================================================
// SECTION 3: COMFYUI EXTENSION REGISTRATION
// ================================================================

app.registerExtension({
    name: "ComfyUI.CustomBatchbox.Manager",

    async setup() {
        console.log("%c[Batchbox] Extension Loading...", "color: gold; font-weight: bold; font-size: 14px");

        try {
            const STORAGE_KEY = "batchbox_btn_pos";

            const createFloatingButton = () => {
                const floatBtn = document.createElement("button");
                floatBtn.id = "batchbox-float-btn";
                floatBtn.innerText = "🍌";
                floatBtn.title = "Batchbox Manager (可拖拽)";

                // Load saved position or use default
                let savedPos = { right: 20, bottom: 20 };
                try {
                    const stored = localStorage.getItem(STORAGE_KEY);
                    if (stored) savedPos = JSON.parse(stored);
                } catch (e) { }

                Object.assign(floatBtn.style, {
                    position: "fixed",
                    right: savedPos.right + "px",
                    bottom: savedPos.bottom + "px",
                    zIndex: "99999",
                    width: "44px",
                    height: "44px",
                    borderRadius: "50%",
                    background: "linear-gradient(135deg, #3a3a3a, #222)",
                    color: "gold",
                    border: "2px solid #555",
                    cursor: "grab",
                    fontSize: "22px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    boxShadow: "0 4px 8px rgba(0,0,0,0.4)",
                    transition: "transform 0.1s, box-shadow 0.1s",
                    userSelect: "none"
                });

                // Drag state
                let isDragging = false;
                let hasMoved = false;
                let startX, startY, startRight, startBottom;

                floatBtn.onmousedown = (e) => {
                    if (e.button !== 0) return;
                    isDragging = true;
                    hasMoved = false;
                    startX = e.clientX;
                    startY = e.clientY;
                    startRight = parseInt(floatBtn.style.right);
                    startBottom = parseInt(floatBtn.style.bottom);
                    floatBtn.style.cursor = "grabbing";
                    floatBtn.style.transition = "none";
                    e.preventDefault();
                };

                document.addEventListener("mousemove", (e) => {
                    if (!isDragging) return;
                    const dx = startX - e.clientX;
                    const dy = startY - e.clientY;
                    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) hasMoved = true;

                    let newRight = Math.max(5, Math.min(window.innerWidth - 50, startRight + dx));
                    let newBottom = Math.max(5, Math.min(window.innerHeight - 50, startBottom + dy));

                    floatBtn.style.right = newRight + "px";
                    floatBtn.style.bottom = newBottom + "px";
                });

                document.addEventListener("mouseup", () => {
                    if (!isDragging) return;
                    isDragging = false;
                    floatBtn.style.cursor = "grab";
                    floatBtn.style.transition = "transform 0.1s, box-shadow 0.1s";

                    // Save position
                    const pos = {
                        right: parseInt(floatBtn.style.right),
                        bottom: parseInt(floatBtn.style.bottom)
                    };
                    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(pos)); } catch (e) { }
                });

                floatBtn.onclick = (e) => {
                    if (hasMoved) {
                        e.preventDefault();
                        return;
                    }
                    const manager = new BatchboxManager();
                    manager.open();
                };

                floatBtn.onmouseenter = () => {
                    if (!isDragging) {
                        floatBtn.style.transform = "scale(1.1)";
                        floatBtn.style.boxShadow = "0 6px 12px rgba(0,0,0,0.5)";
                    }
                };
                floatBtn.onmouseleave = () => {
                    floatBtn.style.transform = "scale(1.0)";
                    floatBtn.style.boxShadow = "0 4px 8px rgba(0,0,0,0.4)";
                };

                return floatBtn;
            };

            const floatBtn = createFloatingButton();
            document.body.appendChild(floatBtn);
            console.log("[Batchbox] Draggable floating button injected.");

        } catch (e) {
            console.error("[Batchbox] Fatal error in setup:", e);
        }
    }
});
