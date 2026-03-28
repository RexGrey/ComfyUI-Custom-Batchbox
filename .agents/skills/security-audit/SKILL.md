---
name: security-audit
description: "BatchBox 插件安全审查。触发词: 安全审查, security audit, 代码审查, 密钥泄露, SSRF, 路径穿越, XSS, 供应链安全, gitleaks, bandit。执行三层审计：自动化扫描 → 检查清单 → LLM 深度审计。"
compatibility: "Python 3.9+, Windows PowerShell. 需要 bandit (pip install bandit)。"
allowed-tools: "Read Write Bash"
depends-on: []
related-skills: [python-pytest-ops]
---

# BatchBox 安全审查 SKILL

针对 `ComfyUI-Custom-Batchbox` 仓库的专用安全审查框架。

## 审查触发条件

当用户请求以下操作时激活此 SKILL：
- "安全审查" / "代码审查" / "security audit"
- 发版前检查
- 新增敏感功能（密钥、上传、缓存、API 路由）后

## 三层审计流程

### Layer 1: 自动化扫描（必须先执行）

运行自动化扫描脚本，获取机器可检测的安全问题：

```powershell
# 在项目根目录执行
powershell -ExecutionPolicy Bypass -File .agents/skills/security-audit/scripts/run_security_scan.ps1
```

脚本会自动执行：
1. **bandit 扫描**：检测 Python 代码中的 `eval/exec/os.system/subprocess/yaml.load` 等危险模式
2. **密钥泄露 grep**：扫描硬编码的 API Key 模式 (`AIzaSy`, `sk-`, `AKIA`, `-----BEGIN`)
3. **路径安全 grep**：检测未保护的 `open()` + 外部输入拼接
4. **前端安全 grep**：检测 `innerHTML`/`outerHTML`/`document.write` 等 XSS 风险
5. **日志泄露 grep**：检测 `print/logger` 中可能包含密钥的输出
6. **gitignore 完整性**：验证敏感文件是否在 `.gitignore` 中
7. **SQLite 参数化**：检测直接字符串拼接的 SQL 语句

扫描结果输出到控制台。审查者需要阅读结果，对每个 finding 判断是误报还是真实问题。

### Layer 2: 检查清单（逐项核查）

读取 `checklists/` 目录中的 13 个检查清单，按维度逐项核查。每个清单包含：
- 具体检查项
- 对应的文件/代码位置
- 通过标准

13 个维度：

| # | 维度 | 清单文件 | 自动化 |
|:--|:-----|:---------|:------:|
| 1 | 密钥管理 | `secrets_management.md` | 🟢 高 |
| 2 | API 安全 | `api_security.md` | 🟡 中 |
| 3 | 路径安全 | `file_path_security.md` | 🟢 高 |
| 4 | 上传下载 | `upload_download_security.md` | 🟡 中 |
| 5 | 前端安全 | `frontend_security.md` | 🟢 高 |
| 6 | 并发稳定 | `concurrency_stability.md` | 🔴 低 |
| 7 | 崩溃恢复 | `crash_recovery.md` | 🔴 低 |
| 8 | 配置序列化 | `config_serialization.md` | 🟢 高 |
| 9 | 日志隐私 | `logging_privacy.md` | 🟢 高 |
| 10 | 供应链 | `supply_chain.md` | 🟢 高 |
| 11 | GitHub 发布 | `github_publish.md` | 🟢 高 |
| 12 | 共享缓存 | `shared_cache_security.md` | 🟡 中 |
| 13 | 机房部署 | `fleet_deployment.md` | 🔴 低 |

### Layer 3: LLM 深度审计（语义级）

自动化和清单无法覆盖的深层问题，需要由你（Agent）通过代码阅读和语义理解来审查：

1. **数据流追踪**：从用户输入 → API 请求 → 日志输出，追踪敏感字段是否在任何环节被全文暴露
2. **Fallback 语义**：确认所有失败路径返回真实错误状态，不伪装成功
3. **竞态分析**：检查 `threading.local()` 使用是否正确覆盖所有共享状态
4. **超时链完整性**：确认从 JS fetch → aiohttp → requests 的每一层都有 timeout
5. **错误信息脱敏**：确认前端收到的错误信息不包含内部路径、依赖版本、真实 URL

## 审查报告格式

审查完成后，输出报告应包含：

```markdown
# BatchBox 安全审查报告 (第 N 次)

## 执行摘要
- 整体风险等级: [低/中/高/严重]
- 自动化扫描发现: X 项 (Y 项误报)
- 检查清单通过率: XX/YY
- 深度审计发现: Z 项

## 发现清单
### P0 (立即处理)
### P1 (尽快处理)
### P2 (计划处理)

## 与上次审查对比
- 新增风险: ...
- 已修复: ...
- 持续存在: ...
```

## 关键文件清单

审查时重点关注以下文件：

### 核心安全文件
- `config_manager.py` — 加密配置管理，密钥加解密
- `crypto_utils.py` — AES-256-GCM 加密工具
- `adapters/generic.py` — API 请求构建，密钥注入
- `__init__.py` — HTTP 路由注册，请求处理
- `account/` — 账号认证系统

### 缓存与存储
- `gcs_cache.py` — GCS 上传缓存 + NAS 共享
- `oss_cache.py` — OSS 上传缓存 + NAS 共享
- `gemini_files_cache.py` — Gemini Files API 缓存 + NAS 共享

### 前端
- `web/dynamic_params.js` — 核心交互逻辑
- `web/blur_upscale.js` — 模糊放大交互
- `web/settings_panel.js` — 设置面板

### 配置
- `api_config.yaml` — API 端点配置
- `secrets.yaml` — 加密密钥存储
- `.gitignore` — 发布安全

## 参考文档

- `./references/threat_model.md` — BatchBox 威胁模型
- `./references/asset_inventory.md` — 资产清单
- `./references/past_findings.md` — 历次审查发现汇总
