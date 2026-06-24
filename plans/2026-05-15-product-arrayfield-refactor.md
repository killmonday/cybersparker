# 产品识别存储重构：CharField → ArrayField

## 问题

| 维度 | 现状 | 缺陷 |
|------|------|------|
| 存储 | 多个产品 `\n` 拼接为单个 `CharField(128)` | 128 字符限制会截断；无法精确检索 |
| 唯一约束 | `unique_together = (task_id, product, target)` | ArrayField 不能入 unique；同 target 不同产品会生成多行 |
| 搜索 | `product__icontains` | `nginx` 误匹配 `openresty-nginx`；无法用索引 |
| 前端 | `item.product.split('\n')` | 依赖换行分隔约定，脆弱 |
| EXP 查找 | `get_exp_ids_for_products` 接收列表，在换行分隔的缓存中逐行比对 | 正确但绕了弯路 |

## 方案

将 `product CharField` 替换为 PostgreSQL `ArrayField(CharField)` + GIN 索引。

```
product: "nginx\nphp\njQuery"          (旧)
    ↓
products: ["nginx", "php", "jQuery"]   (新)
```

搜索：`product:"nginx"` → `products__contains=['nginx']` → `WHERE products @> ARRAY['nginx']` → GIN 索引命中

## 变更范围

| 文件 | 操作 |
|------|------|
| `app_cybersparker/models.py` | `product CharField` → `products ArrayField`；`unique_together` 移除 `product` |
| `app_cybersparker/migrations/0011_product_to_arrayfield.py` | 新增：数据迁移（`\n` split → array） + GIN 索引 |
| `app_cybersparker/views/expload/task_manage/auto_exp_task.py` | `save_indentify_to_db()` 直接存 list；`update_or_create` 替代 `get_or_create` |
| `app_cybersparker/views/expload/task_manage/auto_scan_result.py` | `to_query_structure()` `product` 改用 `products__contains`；统计逻辑改迭代数组 |
| `app_cybersparker/templates/.../auto_scan_identify_result_standalone.html` | `item.product` → `item.products`（已是数组） |
| `app_cybersparker/templates/.../_result_items.html` | `item.product` → `item.products`；`split_newlines` 不再需要 |

## 不做

- 不改变 `exp_relate_fingerprint` 模型（它有自己的 `product` 字段）
- 不改变 `auto_scan_exp_result.product` 字段（EXP 结果单产品，CharField 够用）
- 不修改批量任务/单任务的 EXP 结果表

## 搜索语义变化

| 场景 | 旧 | 新 |
|------|-----|-----|
| `product:"nginx"` | `product ILIKE '%nginx%'` 模糊 | `products @> ARRAY['nginx']` 精确，GIN 索引 |
| `product:"ngin"` | 能匹配到 nginx | 匹配不到（需完整产品名） |
| `!product:"nginx"` | `NOT (product ILIKE '%nginx%')` | `NOT (products @> ARRAY['nginx'])` |

## 风险

- 中：数据迁移将现有 `\n` 分隔字符串转为数组，需确认所有数据格式一致
- 低：前端 JS 代码中 `item.product` → `item.products`，需全局搜索替换
- 低：搜索语义从模糊变为精确，用户可能需适应

## 验证

- [x] `python manage.py check` — 0 issues
- [x] `python manage.py migrate` — 迁移成功
- [x] PostgreSQL 确认 `products` 列类型为 `ARRAY`，GIN 索引存在
- [x] 数据迁移：抽查旧数据 — 多产品已转为数组 `['Microsoft(ISA Server)', 'Zyxel NAS', 'jquery']`；0 个重复 (task_id, target)
- [x] `python manage.py test` — 15/15 通过
- [x] 搜索 `product:"qnap"` — `to_query_structure` 使用 `products__contains=['qnap']`，GIN 索引加速
