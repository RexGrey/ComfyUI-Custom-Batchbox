# 机房部署安全检查清单 (BatchBox 特有)

## 环境变量注入
- [ ] `Start_Client.bat` 中 `BATCHBOX_KEY` 不持久化到系统环境变量
- [ ] `Start_Client.bat` 中 NAS 路径检查（`if defined NAS_DRIVE`）
- [ ] 环境变量不在 bat 文件以外的地方硬编码

## 学生机隔离
- [ ] 学生机无法读取明文 API Key（只有加密的 `secrets.yaml`）
- [ ] 学生机无法通过分析本地文件获取解密密钥
- [ ] 学生机环境变量在 ComfyUI 退出后不残留

## NAS 安全
- [ ] NAS 只读访问足够运行（模型/配置同步）
- [ ] 共享缓存目录有写权限但限定范围
- [ ] NAS 断连不影响 ComfyUI 启动

## 多机一致性
- [ ] 30+ 机器使用同一 key 时的 API 限流策略
- [ ] 端点轮转（Randomized Endpoint Selection）分散请求
- [ ] 每台机器有唯一标识用于审计追踪

## Z 盘阉割版完整性（参考 DEPLOYMENT.md）
- [ ] `Z:\ComfyUI_Master\...\web\api_manager.js` 中悬浮按钮注入已被替换为 `return;`
- [ ] `Z:\ComfyUI_Master\...\__init__.py` 中 `GET/POST /api/batchbox/config` 返回 403
- [ ] Z 盘实际运行目录中**不存在** `.git` 文件夹
- [ ] Z 盘 `secrets.yaml` 不含明文密钥（仅有 `.enc` 加密版或由环境变量注入）
- [ ] 学生端浏览器打开 ComfyUI 后**看不到**管理器浮窗
- [ ] 学生端直接访问 `/api/batchbox/config` 返回 403

## E → Z 同步安全（参考 sync-z-drive.md）
- [ ] robocopy 命令的 `/XF` 参数包含 `api_manager.js` 和 `__init__.py`
- [ ] 同步后 Z 盘阉割文件未被 E 盘完整版覆盖（抽查上述两个文件内容）
- [ ] `.git` 目录被 `/XD .git` 排除在同步之外
