# 路径安全检查清单

## 输出路径
- [ ] `AutoSave` 输出目录固定在 `ComfyUI/output/batchbox/` 下
- [ ] 输出文件名由代码生成（时间戳+随机），不由用户输入决定
- [ ] 无 `../` 路径穿越可能

## 临时文件
- [ ] 临时文件使用 `tempfile.gettempdir()` + 唯一文件名
- [ ] 临时文件使用后删除

## 缓存路径
- [ ] SQLite 缓存固定在插件目录或 `BATCHBOX_SHARED_CACHE` 指定路径
- [ ] `BATCHBOX_SHARED_CACHE` 路径不接受用户输入（仅环境变量）

## 文件读取
- [ ] `config_manager.py` 只读取固定文件名 (`api_config.yaml`, `secrets.yaml`)
- [ ] 无用户可控路径直接传入 `open()` 的代码
- [ ] ComfyUI 的 `/view` 端点路径由 ComfyUI 自身校验
