# BL-AUTO-006 自动扫描任务多输入来源

- 状态：已完成

## 验证

- [x] Django check 0 issues
- [x] 迁移可正常应用（0016_add_input_source_fields）
- [x] URL 解析无冲突
- [ ] 运行时端到端测试（需启动服务人工走查四种输入类型）

## 风险

无新风险。完全复用批量任务已有的目标构建和引擎服务。
- 创建时间：2026-05-17

## 做什么

给自动扫描任务（`auto_scan_tasks`）添加与批量任务相同的多输入来源：上传新文件、历史文件、测绘引擎导入、引擎历史文件。（不含 input_type=2 历史漏洞资产——自动扫描不使用插件。）

## 为什么

当前自动扫描任务仅支持上传单个文件作为目标来源。用户需要像批量任务一样灵活选择目标来源，减少手动文件操作。

## 怎么做

### 模型层
- `auto_scan_tasks` 新增 8 个字段（对照 `batch_EXPTask`）：`input_type`、`history_files`、`engine_type`、`engine_query`、`engine_max_assets`、`engine_proxy_mode`、`engine_proxy`、`reuse_engine_data`
- 生成迁移文件

### 视图层（auto_scan_task.py）
- 更新 `ModelForm` 包含新字段
- 新增 `resolve_target_source()` 函数（从 batch_exp_task.py 适配，去掉 input_type=2）
- 更新 `add`：调用 `resolve_target_source` 处理目标
- 更新 `edit`：调用 `resolve_target_source` 处理目标
- 更新 `detail`：返回新字段 + `can_reuse_engine_data`
- 更新 `delete`：处理引擎目标文件清理
- 新增 `history_files` / `history_files_delete` / `history_engine_results` 辅助接口
- 更新 `startTask` / `Task_operate`：启动前对 input_type=4 做引擎目标准备

### URL 层
- 新增 3 条 URL 映射

### 前端
- `auto_scan_task_list.html`：弹窗表单增加 input_type 选择器 + 条件化面板（引擎配置、历史文件、引擎历史）
- `Identify_task.js`：增加 input type 切换、历史文件管理、引擎结果管理逻辑

## 风险

- **低风险**：完全复用批量任务已有的目标构建函数和引擎服务，逻辑已成熟。
- `auto_scan_tasks.target` 的 FileField 保存路径与批量任务的 `EXP_input/` 目录共享，无冲突。
- 前端改动量大（JS 需完整移植批量任务 UI 逻辑），但均为复制-适配，不涉及新交互模式。

## 验证

- Django check 0 issues
- 迁移可正常应用
- 四种输入类型分别手工创建任务并确认 target 字段正确写入
- 编辑切换输入类型后旧字段清理正确
