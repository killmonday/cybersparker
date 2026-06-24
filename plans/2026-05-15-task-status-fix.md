# 修复任务完成后前端仍显示 running + 添加进度条

- 日期：2026-05-15
- 类型：Bug Fix + UI Enhancement
- 风险：LOW（仅影响任务生命周期管理，不影响插件/结果/其他模块）

## 问题

1. **自动扫描任务** (`auto_exp_task.py`)：`Auto_exploit_Task_handler.run()` 启动子线程后立即返回，producer 线程在 EOF 时 `break` 跳过了 status=1 的更新代码，导致任务完成后状态永远卡在 running。
2. **批量任务** (`batch_task_executor.py`)：输入文件含空行时 `completed_count < total_line_count`，`_finalize_run` 中的 `get_progress()` 进度达不到 100%，status 无法设为 1。
3. **自动扫描任务无 process 字段**：`auto_scan_tasks` 模型缺少 `process` 字段，但代码中尝试写入该字段会静默失败。

## 修复

### 模型
- `auto_scan_tasks` 新增 `process = CharField(default='0%')` 字段 + 迁移 `0009_add_process_to_auto_scan_tasks`

### auto_exp_task.py
- `run()`：启动子线程后等待 producer 完成 → 排空输入队列 → 设置 exit_flag → 休眠 2s 等待 flush → 强制设置 `status=1, process="100%"`
- `producer()`：移除 EOF break 后的死代码，改为循环外写入 `process="100%"`；进度更新改为仅百分比桶变化时写库

### batch_task_executor.py
- `_finalize_run()`：`get_progress(force=True)` 后追加兜底更新 `status=1, process="100%"`

### 前端
- `auto_scan_task_list.html`：新增 process 列（Bootstrap progress bar）；新增 JS 轮询逻辑，每 3s 通过 `Task_all_info` 接口更新进度条和状态
- `auto_scan_task.py`：`Task_all_info` 返回字段中加入 `process`

## 验证
- Django 系统检查：0 issues
- 数据库迁移：已应用
- 测试：15/15 通过
- ruff lint：44 个 error 均为已有代码，非本次修改引入
- 模块导入：正常

### 后续追加 (2026-05-15)

修复 `Task_operate` 停止任务时 `KeyError`：
- `KILL_AUTO_TASK_DIC[uid]` → `KILL_AUTO_TASK_DIC.get(uid)` 防御式访问
- 启动线程前插入 `KILL_AUTO_TASK_DIC[uid] = None` 占位，消除时序竞争
- `startTask` 正常结束后兜底写 `status=1, endTime`

## 后续
- 需要启动服务后人工验证自动扫描和批量任务的进度条刷新和状态自动终止
