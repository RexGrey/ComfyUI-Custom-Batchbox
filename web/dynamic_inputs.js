import { app } from "../../scripts/app.js";

/**
 * 动态图像输入扩展 - ComfyUI Custom Batchbox
 * 
 * 功能：当图像连接到节点时，自动添加新的图像输入接口
 * - 默认只显示 1 个图像输入 (image1)
 * - 连接图像后自动添加下一个输入 (image2, image3, ...)
 * - 最多支持 20 个图像输入
 * - 断开连接后，如果后面没有连接的输入，会自动移除多余的空输入
 */

const DYNAMIC_INPUT_CONFIG = {
    prefix: "image",
    type: "IMAGE",
    maxInputs: 20,
    minInputs: 1
};

app.registerExtension({
    name: "ComfyUI.CustomBatchbox.DynamicInputs",

    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        // 只处理 NanoBananaPro 节点
        if (nodeData.name !== "NanoBananaPro") {
            return;
        }

        // 保存原始的 onNodeCreated
        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;

        nodeType.prototype.onNodeCreated = function () {
            if (originalOnNodeCreated) {
                originalOnNodeCreated.apply(this, arguments);
            }

            // 存储动态输入的状态
            this._dynamicInputCount = 1;

            // 确保节点有正确的初始状态
            this.updateDynamicInputs();
        };

        /**
         * 获取所有图像输入的信息
         */
        nodeType.prototype.getImageInputs = function () {
            const imageInputs = [];
            for (let i = 0; i < this.inputs.length; i++) {
                const input = this.inputs[i];
                if (input.name.startsWith(DYNAMIC_INPUT_CONFIG.prefix)) {
                    const num = parseInt(input.name.replace(DYNAMIC_INPUT_CONFIG.prefix, ""));
                    if (!isNaN(num)) {
                        imageInputs.push({
                            index: i,
                            name: input.name,
                            num: num,
                            connected: input.link !== null
                        });
                    }
                }
            }
            // 按编号排序
            imageInputs.sort((a, b) => a.num - b.num);
            return imageInputs;
        };

        /**
         * 更新动态输入
         * 确保：
         * 1. 至少有 minInputs 个输入
         * 2. 最后一个连接的输入后面有一个空输入（除非已达到 maxInputs）
         * 3. 移除多余的未连接输入
         */
        nodeType.prototype.updateDynamicInputs = function () {
            const imageInputs = this.getImageInputs();

            // 找到最高的已连接编号
            let highestConnected = 0;
            for (const input of imageInputs) {
                if (input.connected && input.num > highestConnected) {
                    highestConnected = input.num;
                }
            }

            // 计算需要的输入数量：最高连接编号 + 1（提供一个空槽位）
            let targetCount = Math.max(DYNAMIC_INPUT_CONFIG.minInputs, highestConnected + 1);
            targetCount = Math.min(targetCount, DYNAMIC_INPUT_CONFIG.maxInputs);

            // 当前存在的最大编号
            let currentMaxNum = 0;
            for (const input of imageInputs) {
                if (input.num > currentMaxNum) {
                    currentMaxNum = input.num;
                }
            }

            // 添加缺少的输入
            for (let i = currentMaxNum + 1; i <= targetCount; i++) {
                const inputName = `${DYNAMIC_INPUT_CONFIG.prefix}${i}`;
                // 检查是否已存在
                let exists = false;
                for (let j = 0; j < this.inputs.length; j++) {
                    if (this.inputs[j].name === inputName) {
                        exists = true;
                        break;
                    }
                }
                if (!exists) {
                    this.addInput(inputName, DYNAMIC_INPUT_CONFIG.type);
                }
            }

            // 移除多余的未连接输入（从后往前）
            // 保留 targetCount 个输入
            const updatedImageInputs = this.getImageInputs();
            for (let i = updatedImageInputs.length - 1; i >= 0; i--) {
                const input = updatedImageInputs[i];
                if (input.num > targetCount && !input.connected) {
                    this.removeInput(input.index);
                }
            }

            // 更新存储的数量
            this._dynamicInputCount = targetCount;

            // 重新排序输入，确保图像输入按顺序排列
            this.reorderInputs();

            // 更新节点大小
            this.setSize(this.computeSize());
            this.setDirtyCanvas(true, true);
        };

        /**
         * 重新排序输入，确保图像输入在最后且按顺序排列
         */
        nodeType.prototype.reorderInputs = function () {
            // 分离图像输入和其他输入
            const otherInputs = [];
            const imageInputs = [];

            for (let i = 0; i < this.inputs.length; i++) {
                const input = this.inputs[i];
                if (input.name.startsWith(DYNAMIC_INPUT_CONFIG.prefix)) {
                    const num = parseInt(input.name.replace(DYNAMIC_INPUT_CONFIG.prefix, ""));
                    if (!isNaN(num)) {
                        imageInputs.push({ input: input, num: num });
                        continue;
                    }
                }
                otherInputs.push(input);
            }

            // 按编号排序图像输入
            imageInputs.sort((a, b) => a.num - b.num);

            // 重新构建输入数组：其他输入在前，图像输入在后（按顺序）
            this.inputs = [...otherInputs, ...imageInputs.map(item => item.input)];
        };

        // 保存原始的 onConnectionsChange
        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;

        /**
         * 连接变化时触发
         */
        nodeType.prototype.onConnectionsChange = function (type, index, connected, link_info) {
            if (originalOnConnectionsChange) {
                originalOnConnectionsChange.apply(this, arguments);
            }

            // 只处理输入连接 (type === 1 表示输入)
            if (type !== 1) return;

            // 检查是否是图像输入
            const input = this.inputs[index];
            if (!input || !input.name.startsWith(DYNAMIC_INPUT_CONFIG.prefix)) return;

            // 延迟更新，确保连接状态已经更新
            setTimeout(() => {
                this.updateDynamicInputs();
            }, 10);
        };

        // 保存原始的 onConfigure
        const originalOnConfigure = nodeType.prototype.onConfigure;

        /**
         * 加载工作流时恢复状态
         */
        nodeType.prototype.onConfigure = function (info) {
            if (originalOnConfigure) {
                originalOnConfigure.apply(this, arguments);
            }

            // 延迟执行，确保所有连接已建立
            setTimeout(() => {
                this.updateDynamicInputs();
            }, 100);
        };

        // 保存原始的 clone
        const originalClone = nodeType.prototype.clone;

        /**
         * 克隆节点时重置动态输入
         */
        nodeType.prototype.clone = function () {
            const cloned = originalClone ? originalClone.apply(this, arguments) : LiteGraph.LGraphNode.prototype.clone.apply(this, arguments);

            // 重置克隆节点的动态输入
            if (cloned) {
                setTimeout(() => {
                    // 移除多余的图像输入，只保留 image1
                    const imageInputs = [];
                    for (let i = cloned.inputs.length - 1; i >= 0; i--) {
                        const input = cloned.inputs[i];
                        if (input.name.startsWith(DYNAMIC_INPUT_CONFIG.prefix)) {
                            const num = parseInt(input.name.replace(DYNAMIC_INPUT_CONFIG.prefix, ""));
                            if (num > 1) {
                                cloned.removeInput(i);
                            }
                        }
                    }
                    cloned._dynamicInputCount = 1;
                    cloned.setSize(cloned.computeSize());
                }, 10);
            }

            return cloned;
        };
    }
});

console.log("[ComfyUI-Custom-Batchbox] Dynamic inputs extension loaded");
