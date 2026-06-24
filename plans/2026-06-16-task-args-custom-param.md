# task_args 任务自定义参数 — 实现方案

- 状态：待审查
- 日期：2026-06-16

## 做什么

给三种任务类型（自动扫描、批量、目录扫描）新增 `task_args` 自定义参数字段。用户创建/编辑任务时输入 JSON 字符串，后端执行时将其注入 `target["task_args"]`，Python 插件内可读取此参数做任务级别的定制。

Nuclei (YAML) 插件不注入 task_args。

## 为什么

用户在跑同一个插件（如某个 RCE PoC）时，不同目标可能需要不同的额外参数（如回连地址、自定义 payload 前缀等）。之前只能每次写死到插件代码里，现在可以在任务配置时动态传入。

## 数据流

```
用户在前端任务表单输入 task_args (JSON字符串)
  ↓ 保存到 DB (TextField)
任务启动 → celery task / thread
  ↓ tasks.py: .values() 读 DB → 放入 row_dict
  ↓ startTask(): 解析 JSON → 放入 data dict
  ↓ data dict 传递给 Executor（不额外查 DB）
执行器 consumer 循环
  ↓ 对 Python 插件: {"target": url, "task_args": parsed_json}
  ↓ 对 YAML 插件: {"target": url} （不注入 task_args）
插件内: target["task_args"]["mykey"]
```

## 改动范围

### 1. 数据模型 (models.py + migration)

```python
# batch_EXPTask, auto_scan_tasks, DirScanTask 各加一行:
task_args = models.TextField(verbose_name="自定义参数(JSON)", null=True, blank=True)
```

### 2. tasks.py — .values() 列表补充

`_run_auto_scan_task` 和 `_run_batch_scan_task` 的 `.values()` 列表中各加 `"task_args"`。

### 3. 任务启动层 — 解析 JSON，放入 data dict

解析时机统一在 `startTask` / phase1 入口，不在 executor 里解析。解析失败时打 warning 日志并回退为 `{}`。

```python
# 解析模式（三处统一）
try:
    parsed = json.loads(raw_task_args or "{}")
except json.JSONDecodeError:
    logging.warning("task_args JSON parse failed for task %s", uid)
    parsed = {}
```

| 文件 | 位置 | 改动 |
|------|------|------|
| `auto_scan_task.py:717` | `startTask()` | `row_dict["task_args"] = json.loads(row_dict.get("task_args") or "{}")` |
| `batch_exp_task.py:878` | `startTask()` data dict 构建 | `data["task_args"] = json.loads(row_dict.get("task_args") or "{}")` |
| `dirscan_worker.py:232` | `_run_dir_scan_phase1()` 读 task 之后 | `task.task_args` → 解析 JSON → 传 `task_args` 给 `_run_dir_scan_phase2(task_id, dispatch_token, owner, task_args=task_args)` |
| `dirscan_worker.py:445` | `_run_dir_scan_phase2()` 签名 | 新增 `task_args=None` 参数 |
| `dirscan_worker.py:552` | `consumer(worker_id)` 闭包 | 闭包捕获 `task_args`，第 572 行 `{"target": target, "task_args": task_args}` |

### 4. 执行器 — 注入 target dict（仅 Python 插件）

执行器构造函数从 `data` dict 读取 task_args 并存为实例属性，consumer 中读取。传递模式与现有 `cmd_input` 一致。

| 文件 | 位置 | 改动 |
|------|------|------|
| `batch_task_executor.py:156` | `Task_handler.__init__` | `self.task_args = data.get("task_args", {})`（参考旁边 `self.cmd_input`） |
| `auto_exp_task.py:114` | `Auto_exploit_Task_handler.__init__` | `self.task_args = data.get("task_args", {})` |
| `batch_task_executor.py:217-251` | `_build_exp_cache()` | `.values()` 加 `"plugin_language"`；cache item 加 `"plugin_language"` 字段 |

consumer 中注入 target dict：

| 文件 | 位置 | 当前 | 改为 |
|------|------|------|------|
| `batch_task_executor.py:759-762` | `consumer_exp()` | `{"target": line}` | `{"target": line, "task_args": self.task_args}` |
| `auto_exp_task.py:1329` | `consumer_EXP()` | `{"target": url}` | `{"target": url, "task_args": self.task_args}` |

注入条件：`plugin_language != 2`（即仅 Python 插件，YAML 不注入 task_args）。参考现有 `auto_exp_task.py:1332` 的 `if plugin_language == 2:` 分支模式。

### 5. 表单/API — 前后端都加 task_args 字段

后端 Form 文件及字段：
- `auto_scan_task.py:37-46` — `AutoScanModelForm.Meta.fields` 加 `"task_args"`
- `batch_exp_task.py:70-79` — `batch_ExpTask_ModelForm.Meta.fields` 加 `"task_args"`
- `dirscan_task_manage.py:30-41` — `DirScanTaskForm.Meta.fields` 加 `"task_args"`

入库前处理：表单提交后，先 `json.loads()` 校验 JSON 合法性，再 `json.dumps()` 格式化为标准 JSON 字符串存入 DB。空白输入存为 `""`（空字符串），读取时 `json.loads(task_args or "{}")` 统一处理。

前端 React：三种任务的新建/编辑表单页各加一个 TextArea（placeholder 提示 JSON 格式），提交前做 JSON 格式校验。

### 6. 调试页 — 可输入 task_args

后端 `app_cybersparker/views/expload/exp_debug.py`：
- `api_exp_execute`（JSON API，第 73 行）和 `debug_execute`（Form API，第 311 行）：接收请求中的 `task_args` 参数，解析 JSON，注入 target dict。解析失败或未填时用 `{}`。
- `runtime_target = {"target": target, "task_args": parsed_task_args}`（仅 Python；YAML 保持不注入）

前端 `frontend/src/pages/ExpDebugPage.tsx`：
- 新增 TextArea 输入框，placeholder 提示 JSON 格式（与任务表单一致）
- 执行时一并通过 FormData / JSON body 传给后端

## 风险

| 风险 | 等级 | 处理 |
|------|------|------|
| JSON 解析失败 | 中 | 表单提交时校验 JSON 格式；启动时解析失败打 warning 日志并回退 `{}` |
| `_build_exp_cache` 缺 plugin_language 导致无法区分 Python/YAML | 高 | 已补充 `.values()` + cache item 字段 |
| 三种任务模型 schema 不一致 | 低 | 字段名和逻辑统一 |
| task_args 含超长内容 | 低 | TextField 无长度限制，按需截断 |
| 前端 forms 遗漏 | 中 | 已列出具体 Form 文件位置 |

## 不做

- 不在 Nuclei YAML 插件执行时注入 task_args
- 不限制 task_args 的 JSON 结构（由插件和用户约定）
- 不修改 exp_debug.py 外的调试相关功能

## 验证

- [ ] `python manage.py makemigrations` 生成迁移文件
- [ ] `python manage.py check` 0 issues
- [ ] `python manage.py test app_cybersparker.tests --parallel` 通过
- [ ] 三种任务创建/编辑表单可输入 task_args，提交后 DB 有对应值
- [ ] 批量任务 Python 插件执行，`target["task_args"]` 为已配置的 dict
- [ ] 批量任务 YAML 插件执行，target 中无 task_args
- [ ] 目录扫描任务 Python 插件执行，`target["task_args"]` 正确传递
- [ ] 不填 task_args 时 `target["task_args"] == {}`
