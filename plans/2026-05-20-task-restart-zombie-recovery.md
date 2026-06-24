# 服务重启后的任务状态回收修复

- 状态：已完成
- 创建时间：2026-05-20

## 做什么

修复服务重启后，部分自动扫描/批量任务仍停留在运行中或暂停中，前端只剩“暂停”按钮，点击后长期卡在“暂停中...”的问题。

## 为什么

当前启动恢复逻辑只回收“已 claim 且心跳过期”的任务，漏掉了 queued、pause_requested、owner 为空但明显已失活的中间态任务。进程重启后执行器句柄已经不存在，这些任务不可能再继续运行，却还在页面上表现成 running 或 pausing。

## 怎么做

1. 扩大 `_recover_zombie_tasks()` 的回收范围，把 `startTime` 为空但仍是 `status=2` 的脏运行态也直接收敛成 `stop`。
2. 保持现有 `Task_all_info` 的 `waiting` 映射不变，仅补充回归测试，防止 queued/running 展示再次回退。
3. 增加定向测试覆盖：重启回收 `startTime/heartbeat_at` 为空的 running 任务，以及 waiting 状态映射。

## 风险

- 回收条件放宽后，如果阈值过激，可能把真实还在排队的任务提前打回 stop。
- 当前目标是“无法证明还活着就收敛成 stop”，偏保守，但更符合频繁重载开发环境。

## 验证

- [x] 启动回收能把 `queued=False` 且 `startTime/heartbeat_at` 为空的 running 脏任务改成 stop。
- [x] 现有 queued → waiting 状态映射不回退，也不会被这次兜底条件误伤。
- [x] 定向测试通过。

## 结果

- 已在 `app_cybersparker/apps.py` 为 auto/batch 启动回收补上 `queued=False + startTime__isnull=True` 兜底条件。
- 已新增回归测试，覆盖“运行中但无 startTime/heartbeat 的脏记录会在服务启动时被回收到 stop”。
- 已确认数据库中的自动扫描任务 `id=200`、`id=201` 现已从 `status=2` 收敛到 `status=3`，`last_error` 为 `server restarted`。

## 风险结论

- 本次改动只影响 `AppcybersparkerConfig.ready()` 启动时的一次性回收，不影响正常运行中的任务执行链路。
- 兜底条件保持保守：只回收 `queued=False` 且连 `startTime` 都没有的 running 脏记录，避免把仍在等待 worker 认领的 queued 任务一起打回 stop。

## 下一步

- 若还有其他历史任务残留 running，可按同样方式检查 `status/owner/startTime/heartbeat_at` 四个字段是否自洽。
