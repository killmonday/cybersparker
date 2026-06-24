# HTML 内容精准检索 — pg_trgm + GIN 索引

## 问题
`to_query_structure()` 对 `html` 字段走默认精确匹配 `Q(html=value)`，无法做内容搜索。

## 方案
PostgreSQL `pg_trgm` 扩展 + GIN 索引，使 `html ILIKE '%keyword%'` 走索引。

## 变更

| 文件 | 操作 |
|------|------|
| `app_cybersparker/migrations/0010_pg_trgm_html_index.py` | 新增：启用 pg_trgm 扩展 + 创建 GIN 索引 |
| `app_cybersparker/views/expload/task_manage/auto_scan_result.py` | `to_query_structure()` 新增 `html` → `html__icontains` |

## 不做
- 不将 `html` 加入 facet 侧边栏（HTML 内容无聚类意义）
- 不改前端 UI

## 风险
- 低：GIN 索引构建时间取决于现有数据量（~817 行，秒级完成）
- 低：pg_trgm 扩展需在 PostgreSQL 中可用（PostgreSQL 15 默认包含）

## 验证
- [ ] `python manage.py migrate` — 迁移成功
- [ ] `python manage.py check` — 0 issues
- [ ] PostgreSQL 中确认索引存在
- [ ] 搜索 `html:"keyword"` 返回匹配结果
