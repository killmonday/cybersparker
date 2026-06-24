# BL-AUTO-010 聚类统计分批异步加载

- 状态：已完成
- 创建时间：2026-05-19

## 做什么

继续优化 standalone 结果页和全局资产检索页左侧聚类统计：
- 用户展开任一聚类项时，首次只异步加载前 40 条。
- 若还有剩余项，则在底部显示“更多”按钮。
- 用户点击“更多”后继续异步加载下一批 40 条，直到全部展示完成。

## 为什么

当前 facet 虽然已经做到按展开懒加载，但仍然一次性返回该分类下全部统计项。字段基数大时，后端聚合结果和前端渲染仍会一次性放大，尤其是 `title`、`product`、`vuln`、`cve` 这类分组数量较多的统计项。

## 怎么做

### 后端
1. 扩展 `facet()` / `global_facet()`，新增 `offset` 参数，固定每批返回 40 条。
2. `build_facet_result()` 改为返回分页结果结构：`items`、`has_more`、`next_offset`、`count_label`。
3. 普通字段和 `ipc` 继续用数据库 `GROUP BY + ORDER BY + LIMIT/OFFSET`。
4. `product`、`vuln`、`cve` 继续走 raw SQL 聚合，但补上 `LIMIT/OFFSET`，避免一次性取回全部分组结果。
5. 每次只多取 1 条（41 条）判断是否还有下一批，不额外做全量 group count。

### 前端
1. facet 缓存从“整包数据”改成“已加载条目 + 下一偏移量 + 是否还有更多”。
2. 展开时请求首批 40 条并渲染。
3. 若 `has_more=true`，在底部显示“更多”按钮；点击后继续加载并追加。
4. 搜索/翻页后清空 facet 缓存，重新从第 1 批开始。

## 风险

- 影响单任务 standalone 页和全局资产检索页两条 facet 接口，因为它们共用同一套分页聚合逻辑。
- raw SQL 分页若排序条件不稳定，会导致“更多”加载时重复或漏项；必须统一按 `count DESC, name ASC` 排序。
- 当前缺少浏览器端人工证据，前端“更多”按钮展示与追加交互仅有代码级证据。

## 验证

- [x] `python manage.py check` 0 issues
- [x] `python manage.py test app_cybersparker.tests.AutoScanResultSearchTests --keepdb -v 2` 通过
- [x] facet 接口首次只返回 40 条且带 `has_more=true`
- [x] 第二次带 `offset=40` 请求能返回后续数据且不重复
- [x] 分类标题右侧数字显示该分类总子项数，不再显示 `40+`
- [ ] 前端存在“更多”按钮并能继续追加展示（代码已改，未做浏览器人工验收）
- [x] 搜索条件变化后 facet 缓存重置
