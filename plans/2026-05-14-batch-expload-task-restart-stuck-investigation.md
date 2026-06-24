# 批量任务暂停后切换运行模式重启卡住排查

## 问题

用户反馈：同一个 `batch_expload_Task` 第一次以协程模式运行，跑到一半暂停；随后改为线程模式并重启，任务进度一直为 `0`，后端终端也看不到运行信息，疑似卡住。

## 范围

- 排查根因并执行 D-lite 最小修复。
- 重点检查批量任务 `operate()`、`startTask()`、`BATH_TASK_DIC`、线程/协程停止器、进度写库链路。
- 不修改数据库 schema、不改变任务执行架构。

## 假设

- 同一任务暂停后，运行模式可能从 `run_mode=2` 改为 `run_mode=1`。
- 卡住表现可能不是执行器内部慢，而是新线程/子进程根本未被启动，或被旧停止句柄误杀/阻止。

## 风险

- 现有工作树已有多处未提交改动，排查结论需要区分本次观察与既有改动。
- SQLite 并发和多进程状态字典本身有运行时不确定性，本次先以代码链路证据为主。

## 验证计划

1. 读取批量任务控制入口与执行器关键符号。
2. 跟踪暂停、重启、run_mode 读取和 `BATH_TASK_DIC` 更新/删除逻辑。
3. 对照测试覆盖，判断是否已有该场景测试。
4. 给出根因、触发条件、建议修复方向与最小验证方式。

## 结果

### 根因判断

主因是批量任务前端操作确认按钮重复绑定：`OperateTask()` 每次打开启动/停止确认弹窗时都会追加一次 `.btn-startTask.click(...)`，没有先 `.off()` 清理旧 handler。用户第一次暂停任务时会留下一个 `status=2` 的停止 handler；之后编辑运行模式并重启时，新旧 handler 会同时发起 AJAX，请求顺序不确定。若旧的停止请求在新的启动请求之后到达，后端会立即调用 `BATH_TASK_DIC[uid].kill_task()` 并把任务状态写回停止，导致新线程/子进程刚启动就被停止，进度保持 `0%`，终端也很难看到执行器运行日志。

放大因素：后端停止分支把 `batch_EXPTask.status` 更新为 `0`，但模型合法状态只有 `1=finish`、`2=running`、`3=stop`。这会造成列表页、详情接口和操作弹窗对同一任务状态的解释不一致，并让后续 start/restart 分支更容易混乱。

次要因素：如果任务是 `input_type=4` 空间测绘输入，编辑 run_mode 时 `resolve_target_source()` 会把 `target` 清空；下一次启动会先在后台 `startTask()` 内重新执行 `fetch_and_dump_targets()`，执行器尚未创建，因此在这段时间不会出现 `Task_handler.run()` 的运行日志，进度也保持 `0%`。该路径有 15s 单请求超时，但多页查询仍可能让用户感觉“卡住”。

### 代码证据

- `app_cybersparker/static/project2/expload/js/batch_Expload_Task.js:721-745`：确认按钮使用 `.click(...)` 追加绑定，没有 `.off()`。
- `app_cybersparker/views/expload/task_manage/batch_exp_task.py:727-733`：停止分支调用 `sett.BATH_TASK_DIC[uid].kill_task()` 后写入 `status=0`。
- `app_cybersparker/models.py:156-162`：`batch_EXPTask.status_choices` 只定义 `1/2/3`，没有 `0`。
- `app_cybersparker/views/expload/task_manage/batch_exp_task.py:735-741`：停止态重启会重新创建后台 `startTask_thread`。
- `app_cybersparker/views/expload/task_manage/batch_exp_task.py:307-335`：空间测绘任务启动前会先准备 target。
- `app_cybersparker/views/expload/task_manage/batch_exp_task.py:378-381`：`input_type=4` 编辑保存会清空 `target`。
- `app_cybersparker/services/cyberspace_engine_service.py:132-139`：重新准备 target 时分页调用测绘引擎 API。

### 现场数据佐证

只读查询最近批量任务记录时发现已有非法状态记录：`id=9 status=0 run_mode=2 process=0.632%`、`id=1 status=0 run_mode=1 process=1%`。另有 `id=15 status=3 run_mode=1 process=0% input_type=4 target为空`，符合“编辑空间测绘任务后 target 被清空，启动前准备 target 未进入执行器”的表现。

### 建议修复方向

1. 前端 `OperateTask()` 中将 `$(".btn-startTask").click(...)` 改为 `$(".btn-startTask").off("click").click(...)`，避免旧 start/stop handler 残留。
2. 后端停止分支统一写 `status=3`，不要写未定义的 `0`。
3. 可选：停止/启动前清理或覆盖 `BATH_TASK_DIC[uid]`，避免旧句柄残留造成误杀。
4. 可选：`input_type=4` 仅改 run_mode 时不要清空已有 `target`，或在 UI/日志中明确提示正在重新拉取测绘目标。

### 验证建议

- 新增前端/后端最小回归：连续执行“启动协程 -> 停止 -> 编辑 run_mode=线程 -> 重启”，确认只发出一次启动请求、不会再发旧停止请求。
- 后端单测覆盖：停止运行中批量任务后 `status` 为 `3`，不是 `0`。
- 空间测绘任务回归：编辑 run_mode 后重启时要么复用已有 target，要么明确记录正在重新获取 target。

### 修复结果

已执行最小修复：

- `app_cybersparker/static/project2/expload/js/batch_Expload_Task.js`：确认启动/停止时先解绑 `.btn-startTask` 旧 click handler，再绑定当前操作，避免暂停后的旧停止请求在重启时再次发出。
- `app_cybersparker/views/expload/task_manage/batch_exp_task.py`：停止运行中任务时从 `BATH_TASK_DIC` 弹出并停止当前句柄，DB 状态写合法 `status=3`。
- `app_cybersparker/tests.py`：新增回归测试，验证停止运行中批量任务会调用 killer、清理 `BATH_TASK_DIC`，并将 `batch_EXPTask.status` 写为 `3`。

### 验证结果

- GitNexus impact：`OperateTask` LOW（0 upstream），`operate` LOW（1 direct caller）。
- `python manage.py test app_cybersparker.tests.BatchTaskGeventRunnerTests`：4 tests OK。
- `python manage.py check`：0 issues。
- `python manage.py test app_cybersparker`：15 tests OK。
- simplify 质量审查后，将前端确认按钮回归测试从完整源码字符串断言改为 `OperateTask` 内“先解绑再绑定”的结构检查；复跑以上三项验证仍通过。

### 文档与变更记录

- 已更新 `CHANGELOG.md`。
- 已更新 `docs/backlog/02-任务执行.md` 的 BL-BATCH-004 状态记录。
- 模块设计文档无需新增架构决策；现有启停控制说明仍适用。
