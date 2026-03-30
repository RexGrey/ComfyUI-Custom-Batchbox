# 配置序列化检查清单

## YAML 安全
- [ ] 所有 `yaml.load()` 使用 `yaml.safe_load()` 或指定 `Loader=SafeLoader`
- [ ] 无 `yaml.load()` 接受不可信输入

## JSON 安全
- [ ] 所有 API 请求体 `json.loads()` 有 try/except
- [ ] 反序列化后的数据做类型检查（`.get()` + 默认值）

## 模板引擎
- [ ] `adapters/template_engine.py` 使用纯正则替换，不使用 eval/exec
- [ ] 无 `{{__import__}}` 类注入可能

## 配置热加载
- [ ] `config_manager.py` 的 mtime 检查只重新读取同一文件
- [ ] 热加载不会意外覆盖加密文件
- [ ] 配置更新后旧配置引用被正确清理
