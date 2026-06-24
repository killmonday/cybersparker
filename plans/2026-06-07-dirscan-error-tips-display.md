# 目录扫描编辑保存错误 tips 不显示

## 问题

编辑目录扫描任务（ID=1），保存时后端返回 `{"status": false, "tips": "输入源未匹配到任何根资产"}`，前端不显示这个 tips。

## 根因

`frontend/src/api/client.ts` 第 87 行，`request()` 检测到 `status === false` 后抛异常，但错误消息只取 `data.message || data.error`，完全忽略了 `data.tips`。后端所有用户提示都放在 `tips` 字段。

## 修复

`data.tips` 放在 ApiError 消息取值链最前面：`data.tips || data.message || data.error || ...`

## 验证

- tsc --noEmit：0 errors
- vite build：✓ 3.50s

## 风险

无。改动一行，全局生效 — 所有后端返回 `tips` 的错误都能正确显示。
