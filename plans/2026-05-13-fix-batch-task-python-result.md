# batch_exp_task Python POC 结果无法入库

- 状态：已完成
- 模式：Mode D-lite

## 问题
`batch_expload_Task` 执行 Python3 POC 时，成功返回 `{"target": url, "result": "ok"}` 但结果未入库，前端看到空列表。

## 根因
POC 文件 `[QVE-2026-1111]test11_a21ff8e5.py` 第3-4行用 tab 缩进、第5行用 4 空格缩进，混用导致 Python 3 `TabError`。
`_build_exp_cache` 的 `except Exception: continue` 静默吞掉此异常，POC 未被加载到缓存中，所有目标都无结果产出。

## 方案
1. 修复 POC 文件缩进：统一为 spaces
2. 在 `_build_exp_cache` 异常处理中加入 `traceback.print_exc()`，使加载失败可见

## 修改文件
- `EXP_plugin/[QVE-2026-1111]test11_a21ff8e5.py`
- `app_cybersparker/views/expload/task_manage/batch_task_executor.py`

## 验证
- POC 文件可正常 import（无 TabError）
- Django 系统检查 0 issues
