# BL-FE-113 漏洞结果清空 + 指纹规则长度修复

- 日期：2026-06-18

## 做什么

1. 漏洞利用结果页（`/react-shell/exp-results`）新增"清空结果"按钮
2. 自动扫描漏洞结果页（`/react-shell/auto-exp-results`）新增"清空结果"按钮
3. 修复指纹 condition 字段 max_length=128 太小导致编辑报错

## 怎么做

### 清空结果按钮

- 后端新增 `POST /api/v1/exp-results/clear` 和 `POST /api/v1/auto-exp-results/clear`
- 前端在 `task_id` 过滤时显示红色"清空结果"按钮，确认后调用 API 删除该任务全部结果

### 指纹长度修复

- `fingerPrint.condition` TextField(max_length=128) → TextField()，去掉长度限制
- 实际库中已有 1539 条超 128 字符（最长 2078），导入时绕过了校验，编辑时触发报错
- Migration: 0063

## 风险

- 无。清空操作为确认式，不可恢复但非误触。
- 指纹 TextField 无 max_length 后 PostgreSQL text 类型无上限，Django 层也不校验。

## 验证

- TypeScript ✓ / Vite build ✓ / Django check ✓ / migrate ✓
- 569 字符 condition full_clean() 通过 ✓
