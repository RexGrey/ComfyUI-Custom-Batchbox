# 更新日志

所有版本的功能变更记录。技术实现细节请参阅 [ARCHITECTURE.md](ARCHITECTURE.md)。

---

## v2.24 (2026-03-01)

**逐张预览 + 生成进度计数器**

- 生成按钮实时显示批次进度：`⏳ 生成中 0/4` → `1/4` → …→ `4/4` → `▶ 开始生成`
- 节点预览支持逐张载入模式（progressive）：完成一张显示一张
- 管理面板「保存设置」新增预览模式下拉：🖼️ 逐张载入 / 📷 全部完成后载入
- 设置项 `node_settings.preview_mode`：`progressive`（默认）| `wait_all`
- 后端 WebSocket 事件 `batchbox:progress` 推送进度
- 两阶段分离设计：逐张显示仅操作 `node.imgs`；持久化仅在全部完成后执行

## v2.23 (2026-03-01)

**Account 系统移植 + Google 官方 API 直连 + 多端点统一架构**

- Account 登录计费系统移植（从 BlenderAIStudio v0.1.4）
- WebSocket 登录回调 + Token 管理 + 自动初始化
- 冰糕积分：余额查询、定价查询、兑换码兑换
- Token 过期检测（code=-4001）+ 前端重新登录提示
- 生图后自动刷新积分
- 前端 Account Tab：服务器状态、积分、购买入口、兑换
- 6 个新 API 端点：login/logout/status/credits/redeem/pricing
- Pricing Table 解析 + `Account.resolve_model_id()` 数字 ID 解析
- 通道策略 UI：💰 低价优先 / ⚡ 稳定优先
- `generationConfig` 对齐上游：`maxOutputTokens=32768`, `temperature=0.8`
- `responseModalities` 大小写修正：`Image` → `IMAGE`
- Google 官方 API 直连：`auth_header_format: none` + URL `?key={api_key}`
- 三通道认证架构：Account (X-Auth-T) / Google (URL Key) / 代理 (Bearer)
- 模型合并：8 个独立模型合为 5 个统一模型（多端点架构）
- 参数校正：严格对齐上游 BlenderAIStudio
- img2img 模式新增 `use_oss_cache: true`

## v2.22 (2026-02-09)

**GaussianBlurUpscale 节点**

- 新增 GaussianBlurUpscale 节点：高斯模糊 + AI 放大工作流
- Canvas 绘制自定义按钮组（模糊程度、修复模式）
- 三种修复模式：直出 / 降噪 / 风格
- 近全屏自定义面板：σ 滑块 + 实时 CSS 模糊预览 + 风格提示词
- 风格预设管理器：CRUD + 拖拽排序
- 作用域执行：点击"开始生成"仅执行当前节点及上游依赖

## 修复记录 (2026-02-05 ~ 2026-02-08)

- **img2img 分辨率失效 (02-08)**：multipart 过滤器误删 `image_size`，修复过滤条件
- **工作流加载排版错位 (02-07)**：`_isRestoring` 时序竞争，添加延迟补做机制
- **API 密钥分离 (02-05)**：密钥分离至 `secrets.yaml`

## v2.21 (2026-01-29)

- 动态缓存加载：根据 `all_images` 输出端口连接状态决定加载策略
- 未连接时只加载选中的 1 张图片（~195MB），连接时加载全部

## v2.20 (2026-01-29)

- 共享图片数据优化：Img2img 批量生成共享同一份 base64 数据
- 内存占用从 N×ImageSize 降到 ~1×ImageSize

## v2.19 (2026-01-29)

- 修复 `HTTPRequestEntityTooLarge`：使用分块迭代读取 `iter_any()`

## v2.18 (2026-01-29)

- 批量图片尺寸归一化：API 返回不同尺寸图片时自动缩放
- 使用 LANCZOS 高质量缩放算法

## v2.17 (2026-01-28)

- 选中图片放大显示：生成多张图后默认第一张放大呈现
- 缩略图切换 + 执行后保持放大 + 重启恢复

## v2.16 (2026-01-28)

- 智能缓存：已生成图片后 Queue Prompt 不再调用 API
- 统一后端哈希 + "参数变化检测"开关

## v2.15 (2026-01-27)

- 即时保存：每张图片收到后立即写入磁盘
- Gemini API 格式修复：`imageConfig` 嵌套对象

## v2.14 (2026-01-27)

- 动态输入槽紧凑：断开中间槽位后连接自动前移
- 并行批处理：效率提升 4x+
- 新增 DALL-E-3、GPT-4o-Image、Sora-Image、Flux 系列等模型

## v2.13 (2026-01-27)

- 画布右键菜单快捷添加功能
- 使用 `getCanvasMenuItems()` 官方 hook + 热重载

## v2.12 (2026-01-27)

- 动态参数持久化修复：风格、分辨率、比例等参数正确恢复
- Endpoint 选择器 + 高级设置折叠状态持久化
- "Pending State" 模式消除 UI 闪烁

## v2.11 (2026-01-27)

- 配置热重载：保存设置后画布节点立即刷新
- `batchbox:config-changed` 事件通知 + `forceRefresh` 参数

## v2.10 (2026-01-27)

- "开始生成"按钮扩展至所有 BatchBox 节点类型

## v2.9 (2026-01-27)

- 独立并发生成优化：asyncio.to_thread 避免阻塞
- 图片实时显示 + 重启后恢复

## v2.8 (2026-01-26)

- Queue Prompt 拦截开关：全局执行时自动排除 BatchBox 节点

## v2.7 (2026-01-26)

- "开始生成"按钮部分执行：只执行目标节点及其上游依赖

## v2.6 (2026-01-26)

- Gemini 原生 API 格式支持
- Prompt 前缀功能

## v2.5.1 (2026-01-25)

- 节点默认宽度可配置（300-1200px）

## v2.5 (2026-01-25)

- 节点宽度保持机制（防止 252px 重置）

## v2.4 (2026-01-25)

- 节点预览持久化（重启后不丢失）

## v2.3 (2026-01-25)

- 模型排序功能 + 拖拽排序 UI

## v2.2 (2026-01-25)

- 自动保存功能：可配置目录、格式、命名模式

## v2.1 (2026-01-25)

- 请求日志系统 + 重试机制（指数退避）
- 结构化异常类 + 配置验证
- TTL 缓存 + RGBA 透明度保持 + WebP 支持
- 单元测试覆盖

## v2.0 (2026-01-24)

- 手动端点选择 + 轮询模式
- 层级文件格式配置
- LLM 配置参考文档

## v1.0 (初版)

- 动态参数系统
- 多供应商支持
- 基础 API 适配器
