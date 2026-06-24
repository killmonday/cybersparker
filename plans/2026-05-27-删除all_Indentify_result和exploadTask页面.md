# 删除 all_Indentify_result 和 exploadTask 页面

- 日期：2026-05-27
- 状态：已完成

## 做什么

删除两个已废弃/不需要的页面：
1. `all_Indentify_result` — 全局识别结果页，已被 auto_scan_result 全局搜索页替代
2. `exploadTask/list` — 单插件执行任务页，已在侧边栏标注"已弃用"，BL-TASK-002 审计建议删除

## 风险

- 低：两个页面都是独立视图，不影响其他模块
- `EXPTask` 模型和 `auto_scan_indentify_result` 模型均保留（被其他模块使用）

## 删除清单

### all_Indentify_result
- [x] 删除视图文件 `all_Indentify_result.py`
- [x] 删除模板 `all_indentify_result.html`
- [x] 移除 URL 路由和 import
- [x] 移除侧边栏链接
- [x] 移除相关测试（2 个）

### exploadTask
- [x] 删除视图文件 `exp_task.py`
- [x] 删除模板 `exp_task_list.html`、`exp_task_result.html`
- [x] 删除 JS 文件 `Expload_Task.js`（两处）
- [x] 移除 URL 路由和 import
- [x] 移除侧边栏链接
- [x] 清理 `batch_Expload_Task.js` 死代码
- [x] 清理 `apps.py` 单任务僵尸检测
- [x] 清理 `recover_zombie_tasks.py` 单任务引用
- [x] 清理 `scheduler_runtime_service.py` 单任务映射
- [x] 清理测试中直接测试已删除视图的用例

## 验证

- [x] python manage.py check（0 issues）
- [x] URL 路由解析无报错（104 patterns，无已删除路由）
- [x] 全模块导入通过
- [x] 测试文件导入通过
- [x] 文档同步（更新模块文档、实现总览）
- [x] CHANGELOG 已更新

## 未完成/风险

- 测试运行因 `dj_db_conn_pool` 基础设施问题无法完整通过（已知预存问题，非本次变更引入）
- `EXPTask` 模型和 `single_task_executor.py` 执行引擎保留（模型被调度器/诊断页/测试引用，暂时保留）
- `静态目录下` 的 `Expload_Task.js` 副本也已删除
