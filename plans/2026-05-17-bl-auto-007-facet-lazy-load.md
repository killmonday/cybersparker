# BL-AUTO-007 聚类统计懒加载与数据库聚合

- 状态：已完成

## 验证

- [x] Django check 0 issues
- [x] 主视图移除 field_statistics 遍历、total_counts 计算
- [x] `/Identify_task/<uid>/facet` 接口已注册
- [x] 前端展开时 AJAX 请求 facet
- [x] facet 缓存 + 翻页清空
- [ ] 运行时端到端测试（需启动服务验证实际数据）
- 创建时间：2026-05-17

## 做什么

独立结果页左侧聚类统计改为懒加载 + PostgreSQL 聚合。页面首次加载不遍历全量数据，用户展开某分类时通过 AJAX 请求 facet 接口，数据库 `GROUP BY` + `COUNT` 返回结果。

## 为什么

当前 `auto_scan_result.py:309-348` 在每次页面加载/翻页时遍历 `data`（全量查询结果）逐条累加统计。数据量大时 O(N) 内存和 CPU 开销不可接受。

## 怎么做

### 后端
1. 新增 `/Identify_task/<uid>/facet` 接口
   - 接收 `field`（字段名）和 `search_data`（可选搜索条件）
   - `protocol/port/title/country/status_code`：Django ORM `values(field).annotate(count=Count('id'))`
   - `ipc`：`SplitPart` 提取 C 段后聚合
   - `product`：`unnest(ArrayField)` 后聚合
   - 搜索条件与主查询一致

2. 主视图移除 `field_statistics` 遍历计算
   - 删除 `auto_scan_result.py:309-376` 的遍历+统计代码
   - 上下文不再传入 `field_statistics_json` / `total_counts_json`（或传空对象）
   - 保留 `total`（总匹配数）的查询

### 前端
3. `auto_scan_identify_result_standalone.html` JS 修改
   - `renderAllFacets()`：标题行不显示数字（或显示 `...`），展开时触发 AJAX
   - 分类默认折叠
   - 点击展开 → `fetchFacet(field)` → 拿到数据后渲染子项和标题数字
   - 已获取的字段缓存，不重复请求
   - 翻页/搜索后清空缓存，已展开的重新请求

## 风险

- 低。仅改统计加载方式，不改结果数据展示。
- `unnest` 在 ArrayField 上的 ORM 表达可能需要 raw SQL fallback。

## 验证

- [ ] Django check 0 issues
- [ ] 页面加载后分类标题无数字
- [ ] 展开"协议"后发起 facet 请求，返回正确聚合结果
- [ ] products/IPC facet 正确
- [ ] 搜索条件下 facet 数值与搜索结果一致
