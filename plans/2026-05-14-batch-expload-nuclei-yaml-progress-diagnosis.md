# batch_expload nuclei yaml 协程进度卡顿排查

## 做什么

排查 `batch_expload_Task` 在“协程运行 + nuclei yaml 脚本”场景下后端终端长时间无输出、前端进度条长时间停留后跳变的问题。

## 为什么

用户观察到任务进度不是平滑推进，而是从 0% 突然跳到约 40%，需要判断这是实现 bug、进度采样粒度问题，还是 nuclei yaml 执行性能瓶颈。

## 怎么做

1. 读取项目控制台，确认当前阶段与相关 backlog 基线。
2. 定位批量任务启动、执行器、nuclei yaml 运行时加载、任务进度查询、前端轮询链路。
3. 对比协程模式与线程模式的进度更新位置、DB 写入时机、yaml 运行时执行方式。
4. 给出根因判断、风险和最小修复建议；本轮先不改代码。

## 风险

- 当前工作区已有大量未提交改动，本次排查不能把既有改动误认为本轮修改。
- 如果需要复现实测，可能依赖本地服务、数据库和具体 nuclei yaml 样本；本轮先基于代码静态分析，必要时再请求运行时授权。

## 状态

- 2026-05-14：已创建计划，开始静态排查。
- 2026-05-14：完成静态定位，结论是“实现缺陷为主，nuclei yaml 请求耗时会放大现象”。

## 证据

- `app_cybersparker/views/expload/task_manage/batch_exp_task.py:617`：协程运行模式会使用 `multiprocessing.get_context("spawn")` 启动独立进程执行 `run_task_in_subprocess`。
- `app_cybersparker/views/expload/task_manage/batch_task_executor.py:443`：子进程内强制 `Task_handler.run_mode = 2`，进入协程执行路径。
- `app_cybersparker/views/expload/task_manage/batch_task_executor.py:224`、`237`、`247`：协程模式只在生产者未结束、消费者数量未清零、输出队列清空后几个固定点调用 `get_progress()`。
- `app_cybersparker/views/expload/task_manage/batch_task_executor.py:340`：进度用 `max(self.consumer_number, self.current_index) / self.total_line_count` 计算，而 `consumer_number` 在取到输入任务后立即加一，不等 nuclei yaml 请求完成。
- `app_cybersparker/views/expload/task_manage/batch_task_executor.py:370`：每个目标执行 `call_runtime_method(..., "verify", line)`；nuclei yaml 会进入模板运行时。
- `app_cybersparker/views/expload/task_manage/nuclei_runtime_engine.py:697`：模板 HTTP 请求通过 `requests.Session().request(...)` 串行执行；默认 timeout 在 `:606`、`:615` 为 10 秒，raw 模板可覆盖更长 timeout。
- `app_cybersparker/views/expload/task_manage/batch_exp_task.py:451`：前端轮询读取的是 DB 中 `batch_EXPTask.process` 字段。
- `app_cybersparker/templates/project/expload/task_manage/bath_exp_task_list.html:883`、`:889`、`:895`：页面每 3 秒请求详情接口并直接把返回的 `process` 写入进度条。

## 结论

这是后端进度模型的实现问题，不是单纯前端刷新问题。nuclei yaml 的 HTTP 请求耗时、模板多请求/多 payload 串行执行，会让协程消费者长时间卡在单个 `verify` 调用里；同时当前进度按“已取出/已入队目标数”而不是“已完成目标数”计算，并且协程模式只有少数固定循环点写库，所以页面看到的就是长时间不变后一次性跳到较大百分比。

## 最小修复建议

1. 把进度计算从 `max(consumer_number, current_index)` 改为以“完成的目标数”为主，避免目标刚被消费就提前计入完成。
2. 在 `consumer_exp` 每个目标处理完成后触发轻量进度更新，或维护完成计数并由单独定时器写库，避免只在外层等待循环写库。
3. 对 nuclei yaml 运行时增加更细的执行日志或每目标开始/结束日志，便于区分网络慢、模板慢和执行器卡住。
4. 如需性能优化，再评估模板请求并发、timeout 上限、payload 数量控制；但这应在进度语义修正之后做。

## 实施结果

- `app_cybersparker/views/expload/task_manage/batch_task_executor.py` 新增 `completed_count`，进度计算改为 `completed_count / total_line_count`。
- `consumer_exp()` 在单个目标完成 `verify` 调用并处理输出队列后递增完成数，并触发一次进度写库。
- 恢复执行时根据历史百分比计算已完成行数，钳制边界后从下一行继续读取，避免把未完成目标提前计入 100%。
- 完成数更新与写库去重标记放在同一把锁内，避免并发消费者重复触发同一完成数写库。
- 未修改前端轮询、接口契约、数据库模型或 nuclei yaml runtime。

## 验证

- `python -m py_compile app_cybersparker/views/expload/task_manage/batch_task_executor.py`：通过。
- 静态语义检查：`completed_count` 已初始化；进度公式使用完成数；旧 `max(self.consumer_number, self.current_index)` 公式已移除；消费者完成后递增完成数；恢复执行钳制已完成行并跳到下一行；写库去重标记在锁内更新。
- Reviewer 审查：指出恢复进度边界与写库去重竞态风险，已修复并重跑验证通过。
- 仓库未发现现成 pytest/Django 测试配置，未新增测试文件；建议后续用本地服务按下方场景做 UI/端到端复验。

## 验证建议

- 准备 5 个目标、1 个 nuclei yaml 模板、协程数 2，观察 `process` 是否按完成目标推进，而不是按读取/入队目标推进。
- 使用一个故意慢响应或超时目标，确认其他已完成目标仍能让进度逐步更新。
- 前端无需额外验证轮询机制，只需确认详情接口返回的 `process` 平滑变化即可。
