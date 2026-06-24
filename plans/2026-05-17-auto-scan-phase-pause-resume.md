# 自动扫描任务阶段显示与暂停/续跑/重跑

- 日期：2026-05-17
- 状态：已完成

## 做什么

自动扫描任务增加：
1. 阶段显示（Web扫描 → 漏洞扫描 → 全部完成）
2. 优雅暂停（队列排空后自动停止）
3. 续跑（从当前进度继续）和重跑（从头开始）

## 为什么

- 进度条只反映 Web 扫描阶段，用户看到 99% 以为完成了，实际还在做指纹/POC
- 之前的停止是强制终止，队列数据丢失
- 缺少续跑和重跑能力

## 怎么做

### 模型层
- `auto_scan_tasks` 新增 `phase`（1/2/3）、`pause_requested` 字段
- `status_choices` 增加 `(4, "pause")`

### 执行器
- `check_pause_signal()` 新增方法，只在 producer 调用
- producer 检测到暂停信号后停止读新 URL，消费者继续排空
- `run()` 启动时设置 phase=1，HTTP 阶段完成后设 phase=2，暂停收尾设 status=4

### 视图层
- `Task_operate` 增加 `pause`/`resume`/`rerun` 状态分支
- `Task_all_info` 返回 phase 字段

### 前端
- 状态列改为标签显示（完成/运行中/已暂停/已停止）
- 新增阶段列，显示当前阶段文字
- 操作按钮按状态重组：running→暂停，stop→启动+续跑+重跑，pause→续跑+重跑
- 轮询增加 phase 实时更新

## 改动文件

| 文件 | 改动 |
|------|------|
| `app_cybersparker/models.py` | 2 新字段 + status_choices 扩展 |
| `app_cybersparker/migrations/0014_add_phase_pause_fields.py` | 新迁移 |
| `app_cybersparker/views/expload/task_manage/auto_exp_task.py` | check_pause_signal、producer 暂停检查、run() 阶段跟踪 |
| `app_cybersparker/views/expload/task_manage/auto_scan_task.py` | Task_operate 新分支、Task_all_info 加 phase |
| `app_cybersparker/tasks.py` | pause 跳过 CAS |
| `auto_scan_task_list.html` | 阶段列、按钮重组、轮询增强 |
| `Identify_task.js` | 新 bindOperateEvents 函数 |

## 验证

- Django 系统检查：0 issues
- 数据库迁移：已应用
- 模型字段验证：phase_choices / status_choices / pause_requested 正确
- URL 路由：90 patterns 正常
- 模块导入：全部通过
