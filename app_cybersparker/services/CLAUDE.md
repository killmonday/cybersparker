# services 目录约束

- 处理空间测绘历史文件时，读取和删除都必须走 `cyberspace_engine_service.get_engine_asset_file_path()`，不能只用 `get_absolute_target_path()`；前者会同时检查 `EXP_input/engine_assets/` 前缀和真实路径，防止项目内其他文件被当成任务输入。
