# 自动扫描暂停收尾诊断日志

- 日期：2026-05-18
- 状态：进行中

## 做什么

仅为自动扫描任务暂停收尾链路增加诊断日志，持续打印各队列的 `unfinished_tasks`，帮助定位为什么任务长期停在“暂停中...”。

## 为什么

- 当前“暂停中...”的含义是 `status=2 && pause_requested=true`。
- 只有执行器真正等到各队列排空后，才会落成最终 `status=4`。
- 需要先知道具体卡在哪个队列，再决定是否改行为。

## 范围

- `app_cybersparker/views/expload/task_manage/auto_exp_task.py`

## 不做

- 不改变暂停语义
- 不改变队列 put/get 逻辑
- 不改变前端展示逻辑

## 验证

1. `python manage.py check`
2. 下次复现“暂停中...”时，从 Celery 日志里直接看到卡住的队列计数
