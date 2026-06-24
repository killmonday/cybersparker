# 修复自动扫描指纹识别产品合并问题

- 日期：2026-05-18
- 关联 Backlog：BL-AUTO-001
- 风险等级：标准

## 问题

自动扫描任务对每个 URL 执行指纹识别时，`Identifyner.handle()` 正确地遍历了所有指纹规则并返回了全部匹配的产品列表。但后续的事件写入流程中，`_write_identify_event()` 在更新已有行时先执行 `.update(**defaults)` 把 `products` 覆盖为当前事件的单个产品，然后再尝试合并 — 此时原有产品数据已被覆盖，合并始终无效。

**结果**：一个 URL 匹配了 3 个产品（nginx、apache、tomcat），最终 DB 里只保留最后一个。

## 修改

### result_event_service.py `_write_identify_event`

- 已存在行时：先从 `row.products` 读取已有产品，与新产品的 `product` 做 set 合并，再把合并后的列表写入 `defaults["products"]`，然后执行 `.update()`
- 去掉无效的「更新后合并」代码

### tests.py

- 新增 `test_identify_events_merge_products_for_same_target`：对同一 target 依次写入 3 个不同产品的事件，断言最终 `products` 为 `["apache", "nginx", "tomcat"]`（排序后）

## 验证

- Django check: 0 issues
- ResultEventServiceTests: 8/8 通过（含新增的合并测试）
- 完整测试套件中的 44 个错误为预存基础设施问题（SQLAlchemy pool + test DB flush），与本次修改无关

## 风险

无。修改仅影响 `_write_identify_event` 内部逻辑，不改变事件格式、API 或数据模型。

---

## 补充修改（2026-05-18）：前端资产检索页"端口-产品-协议"展示调整

### 问题

数据库修复后，一个 target 可正确存储多个产品。但前端"端口-产品-协议"区域仍按每个产品一行展示，同一端口会重复出现多行。

### 修改

**`auto_scan_identify_result_standalone.html`**：

1. **"端口-产品-协议"** — 从表格行（每产品一行）改为按端口分组展示：
   - 同一端口的所有产品用圆角徽章（`.product-chips span`）并排显示
   - 每个端口组一行：`协议:端口` 标签 + 产品徽章列表
   - 端口组按协议:端口排序

2. **"识别产品"** — 添加截断：超过 6 个产品时显示前 6 个 + "…"（title 提示总数）

3. **CSS** — 新增 `.ppg-row`、`.ppg-label`、`.product-more` 样式

### 补充修改（2026-05-18）：第一个 ri-col 宽度约束

"识别产品"徽章在过宽的列中视觉松散。将 `.ri-detail .ri-col:first-child` 改为 `flex:0 1 280px; max-width:320px`，基准宽度与 sidebar 一致，剩余空间由后两列平分。

### 验证

- Django check: 0 issues
- 纯前端修改，不影响后端逻辑

---

## 补充修改（2026-05-18）：引擎任务重跑"复用引擎数据"生效

### 问题

`reuse_engine_data` 字段在创建/编辑时被写入，但执行层从未读取，实际行为仅由文件是否存在决定。重跑时也无法让用户选择是否重新拉取。

### 修改

**前端**（`auto_scan_task_list.html` + `Identify_task.js`）：
- 所有 `.btn-rerun` 增加 `data-input-type` 属性
- 模态框新增 `#engineReusePanel`（复选框，默认勾选"复用已有引擎数据"）
- 点击重跑时检测 `input_type==4` 则显示该面板
- 确认时传 `reuse_engine_data` 参数到后端

**后端**（`auto_scan_task.py` + `tasks.py`）：
- `Task_operate`：接收前台参数，转为 `force_refresh_engine`，通过 `dispatch_task(kwargs)` 直接传给 Celery（不写 DB 字段）
- `run_auto_scan_task` / `_run_auto_scan_task`：接收并下传 `force_refresh_engine`
- `prepare_engine_target_before_start`：新增 `force_refresh` 参数，为 `True` 时强制 `need_refresh`
- `startTask`：新增 `skip_engine_prepare` 参数，Celery 路径传入 `True` 避免 `prepare_engine_target_before_start` 被调用两次

### 后续修复

- `run_auto_scan_task`（Celery 装饰器层）漏收 `force_refresh_engine` → 补上并下传
- `startTask` 冗余调用 `prepare_engine_target_before_start` → Celery 路径加 `skip_engine_prepare=True`

### 验证

- Django check: 0 issues
- TestCase 测试 8/8 通过
- Celery 日志确认：未勾选复用 → `force_refresh=True` → 删除旧文件 → FETCH 新文件

---

## 补充修改（2026-05-18）：HTTP 响应 title 解析优化

### 问题

`BS(content, "lxml")` 为提取 `<title>` 标签构建整个 HTML DOM 树，内存和 CPU 开销大，且会产生 `XMLParsedAsHTMLWarning` 噪音。

### 修改

**`auto_exp_task.py`**：
- 移除 `from bs4 import BeautifulSoup`，改用 `re.search(r"<title[^>]*>(.*?)</title>", ...)` 正则提取
- `html.unescape()` 处理 HTML 实体（原 BS 自动处理）
- 移除 `lxml`/`beautifulsoup4` 依赖

### 验证

- Django check: 0 issues
