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
