# 2026-06-21 扫描区域全链路修复

## 问题链

1. **表单不传输 zone**：三个 ModelForm `Meta.fields` 缺 `"zone"`，前端选区域后被静默丢弃
2. **模型无 NULL 兜底**：`batch_EXPTask` 非引擎类型 zone=NULL 无默认值
3. **前端无默认选中**：`openAddForm()` 初始 `zone_id=''`，没选中"公网"
4. **详情 API 不返 zone_id**：三个任务详情 API `.values()`/响应 dict 漏 `zone_id`，编辑时为空
5. **Select 懒加载滞后**：zones 在 onFocus 才加载，编辑表单打开时没选项，只显示原始 id
6. **单任务结果页无 zone 过滤**：`Task_result` / `facet` 只看 task_relations，不限定 zone
7. **zone 切换不生效**：任务页 zone 下拉被后端忽略，且切换后不自动搜索
8. **HTML 检索未分流**：`:=` 和 `:` 走同一条 LIKE，tsvector 索引闲置

## 修复

| # | 文件 | 改动 |
|---|------|------|
| 1 | `auto_scan_task.py` | Meta.fields + "zone"；zone.required=False |
| 2 | `batch_exp_task.py` | Meta.fields + "zone"；新增 __init__ 设 zone.required=False；save() 加 NULL→公网 |
| 3 | `dirscan_task_manage.py` | Meta.fields + "zone"；zone.required=False |
| 4 | `models.py` | auto_scan_tasks/batch_EXPTask/DirScanTask save() zone=NULL→公网 |
| 5 | `AutoScanTaskListPage.tsx` | useEffect 预加载 zones + 默认公网 |
| 6 | `BatchTaskListPage.tsx` | 同上 |
| 7 | `DirscanTaskListPage.tsx` | 同上 |
| 8 | `auto_scan_task_api.py` | task_detail_api .values() + "zone_id" |
| 9 | `batch_exp_task.py` detail | .values() + "zone_id" |
| 10 | `dirscan_task_manage.py` task_detail | 响应 dict + "zone_id" |
| 11 | `auto_scan_result.py` | Task_result + facet 加 zone 过滤，支持用户传 zone_id 切换 |
| 12 | `GlobalAssetSearchPage.tsx` | zone 切换立即搜索 + 默认读任务 zone + 样式对齐 |
| 13 | `asset_search_parser.py` | `:` 走 tsvector 快捷检索，`:=` 保留 LIKE 深度检索 |
| 14 | `settings.py` | STATICFILES_DIRS DEBUG 时含 STATIC_ROOT（favicon 开发 404） |
| 15 | `deploy/nginx/react-shell.conf` | 新增 `/static/favicons/` location 指向 STATIC_ROOT |
| 16 | `tests.py` | 新增 ModelFormZoneFieldTests（5）+ HtmlSearchSemanticSplitTests（4） |

## 验证

- 新增 9 个测试全绿
- 全量 434 测试 0 失败
- TypeScript 编译 0 错误
- Django check 0 issues
- 数据库 5745 条 NULL zone 已回填 public
