import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Utility to inject CSS
function injectCSS() {
    if (document.querySelector('link[href*="api_manager.css"]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.type = "text/css";
    link.href = "extensions/ComfyUI-Custom-Batchbox/api_manager.css";
    document.head.appendChild(link);
}

// --------------------------------------------------------
// UI Builder Classes
// --------------------------------------------------------

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
            const resp = await api.fetchApi("/batchbox/config");
            if (resp.status !== 200) throw new Error("Failed to load config");
            this.config = await resp.json();
        } catch (e) {
            this.showToast("加载配置失败: " + e.message, "error");
            this.config = { providers: {}, presets: {} };
        }
    }

    async saveConfig() {
        try {
            const resp = await api.fetchApi("/batchbox/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(this.config)
            });
            if (resp.status !== 200) throw new Error("Save failed");
            this.showToast("配置已保存！后端已更新。", "success");
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

        ["供应商 Providers", "预设 Presets", "原始 JSON"].forEach((label, i) => {
            const btn = document.createElement("button");
            btn.className = `batchbox-tab-btn ${i === 0 ? "active" : ""}`;
            btn.innerText = label;
            btn.onclick = () => this.switchTab(["providers", "presets", "raw"][i]);
            sidebar.appendChild(btn);
        });

        // Panels
        this.panels = {};
        ["providers", "presets", "raw"].forEach((name, i) => {
            const panel = document.createElement("div");
            panel.className = `batchbox-panel ${i === 0 ? "active" : ""}`;
            this.panels[name] = panel;
            content.appendChild(panel);
        });

        this.renderProviders(this.panels["providers"]);
        this.renderPresets(this.panels["presets"]);
        this.renderRaw(this.panels["raw"]);

        // Footer
        const footer = document.createElement("div");
        footer.className = "batchbox-footer";
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
            t.classList.toggle("active", ["providers", "presets", "raw"][i] === tabName);
        });
        Object.entries(this.panels).forEach(([name, panel]) => {
            panel.classList.toggle("active", name === tabName);
        });
        if (tabName === "raw") this.renderRaw(this.panels["raw"]);
    }

    // ==================== PROVIDERS ====================
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
                { name: "name", label: "名称", value: editName || "", disabled: isEdit, required: true },
                { name: "base_url", label: "Base URL", value: existing.base_url || "", placeholder: "https://api.example.com", required: true },
                { name: "api_key", label: "API Key", value: existing.api_key || "", placeholder: "sk-xxxxxx", type: "password" }
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
                this.config.providers[data.name] = {
                    base_url: data.base_url,
                    api_key: data.api_key
                };
                if (isEdit && data.name !== editName) {
                    delete this.config.providers[editName];
                }
                this.renderProviders(this.panels["providers"]);
                this.showToast(isEdit ? "供应商已更新" : "供应商已添加", "success");
                return true;
            }
        });
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
                                ${providerOptions.map(p => `<option value="${p}" ${p === existing.provider ? "selected" : ""}>${p}</option>`).join("")}
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
        const typeLabel = type === "provider" ? "供应商" : "预设";
        this.showConfirmModal({
            title: `删除 ${typeLabel}`,
            message: `确定要删除 ${typeLabel} "${name}" 吗？此操作无法撤销。`,
            onConfirm: () => {
                if (type === "provider") {
                    delete this.config.providers[name];
                    this.renderProviders(this.panels["providers"]);
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
            if (f.type === "select") {
                const opts = f.options.map(o => `<option value="${o}" ${o === f.value ? "selected" : ""}>${o}</option>`).join("");
                return `<div class="batchbox-form-group">
                    <label>${f.label}${f.required ? " *" : ""}</label>
                    <select name="${f.name}" class="batchbox-form-input" ${f.disabled ? "disabled" : ""}>${opts}</select>
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

// --------------------------------------------------------
// Registration
// --------------------------------------------------------

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
