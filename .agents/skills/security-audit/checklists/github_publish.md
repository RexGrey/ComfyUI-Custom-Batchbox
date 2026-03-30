# GitHub 发布安全检查清单

## .gitignore 覆盖
- [ ] `secrets.yaml` 被忽略
- [ ] `.auth.json` 被忽略
- [ ] `*.db` (缓存数据库) 被忽略
- [ ] `__pycache__/` 被忽略
- [ ] `*.pyc` 被忽略
- [ ] `service_account*.json` 被忽略
- [ ] `gateway_client.json` 被忽略
- [ ] `*.enc` 加密文件评估是否需要忽略

## Git 历史清洁
- [ ] 历史中无明文密钥
- [ ] 历史中无 `.auth.json` 内容
- [ ] 历史中无 Service Account JSON

## 示例配置
- [ ] 保留 `secrets.yaml.example`（如有）
- [ ] 示例配置中使用占位值（`YOUR_KEY_HERE`）

## Release 检查
- [ ] Release 包不包含本地配置
- [ ] Release 包不包含缓存数据库
- [ ] Release 包不包含测试产出图片

## 文档安全
- [ ] README/文档中无真实 API Key
- [ ] 截图中无内网 IP/机器名
- [ ] 截图中无用户名/密码
