# 供应链安全检查清单

## Python 依赖
- [ ] `requirements.txt` 存在且版本锁定
- [ ] 无已知高危 CVE（运行 `pip-audit` 或 `safety check`）
- [ ] 第三方 SDK 仍在维护（`requests`, `aiohttp`, `Pillow` 等）
- [ ] 无从未知来源复制的代码片段

## JavaScript 依赖
- [ ] 前端 JS 无 CDN 外部引用（全部本地）
- [ ] 无 npm/node_modules 依赖（纯 vanilla JS）

## ComfyUI 兼容性
- [ ] 不覆盖 ComfyUI 核心函数
- [ ] 不修改全局 Python 路径
- [ ] 不注入未经声明的全局变量
