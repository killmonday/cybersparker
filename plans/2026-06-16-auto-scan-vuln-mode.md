# 自动扫描任务 "仅漏洞扫描" 模式 — 开发计划 v3

## 1. 需求摘要

`auto_scan_tasks.Vulnerability_scanning` 从 是/否 改为 3 选 1：

| 值 | 含义 | 行为 |
|----|------|------|
| 0 | 不进行漏洞扫描 | 只做 web 探测 + 产品识别（= 原"否"） |
| 1 | Web 扫描 + 漏洞扫描 | web 探测 + 指纹匹配 → 漏洞测试（= 原"是"） |
| 2 | 仅漏洞扫描 | 跳过 web 探测，从已有资产反查 POC → 漏洞测试 |

---

## 2. 数据流（模式 2）

```
AssetTaskRelation(task_id=当前任务ID)
  → identify_result_id[] → auto_scan_indentify_result.id__in
    → [target, products]
      → 过滤 products/target 为空的
        → 去重 (target, frozenset(products))
          → {target: products[]} → queue_EXP_input
            → exp_consumer → verify → queue_EXP_result → save_exp_result
```

---

## 3. 执行模型：全程线程，不走 asyncio

模式 2 共用模式 1 的漏洞扫描管道，全程线程：

- **入队**：`_run_vuln_only_mode()` — 同步 for 循环，`queue_EXP_input.put()`
- **消费**：`exp_consumer` — `threading.Thread`，`call_runtime_method(exp, "verify", target)` 同步调用
- **结果攒批**：`save_exp_result` — `threading.Thread`，攒批写 DB

asyncio / aiohttp 只在 web 扫描阶段用（`request_consumer`），模式 2 跳过整个 web 扫描阶段，全程不碰 asyncio。

---

## 4. 暂停/恢复/进度语义

### 暂停
- 设 `self.producer_done = True` → 等 `queue_EXP_input.join()` + `queue_EXP_result.join()` 排空 → 落 status=4
- `current_line` 存当前 `relation_ids` 中的索引位置（恢复从该位置继续）

### 恢复
- `current_line` 作为 offset，跳过 `relation_ids` 的前 N 个元素

### 进度
- 每 10 个资产更新一次 `process` 字段
- 分母 = 有效资产数（有 products + 有 target + 去重后）

---

## 5. 改动清单

### 4.1 模型层

**文件**：`app_cybersparker/models.py` 行 265-270

```python
# 改前
    expScan_start = (
        (1, "yes"),
        (0, "no"),
    )
    Vulnerability_scanning = models.SmallIntegerField(
        verbose_name="Vulnerability_scanning", choices=expScan_start, default=0
    )

# 改后
    expScan_start = (
        (0, "不进行漏洞扫描"),
        (1, "Web扫描后漏洞扫描"),
        (2, "仅漏洞扫描（跳过Web探测）"),
    )
    Vulnerability_scanning = models.SmallIntegerField(
        verbose_name="漏洞扫描模式", choices=expScan_start, default=0
    )
```

**Migration**：新建 `0062_alter_auto_scan_tasks_vulnerability_scanning.py`，`AlterField` 改 choices + verbose_name。不新建列。

---

### 4.2 执行器 — 核心改动

**文件**：`app_cybersparker/views/expload/task_manage/auto_exp_task.py`

#### 4.2.1 6 处 `== 1` 引用处理

| 行号 | 原代码 | 改动 | 原因 |
|------|--------|------|------|
| 192-196 | `if self.Vulnerability_scanning == 1` (缓存构建) | `in (1, 2)` | 模式 2 也需要缓存 |
| 348 | `if self.Vulnerability_scanning == 1:` (exp_worker_count) | `in (1, 2)` | 不启动 exp 线程则无法消费 |
| 361 | `if ... Vulnerability_scanning == 1:` (phase=2) | `in (1, 2)` | 模式 2 需显示"正在漏洞扫描" |
| 398 | `if ... Vulnerability_scanning == 1:` (队列 drain) | `in (1, 2)` | 不 drain 则结果丢失 |
| 1291 | fingerpoint consumer 内推 exp 队列 | **保留 `== 1`** | 模式 2 不启动 fingerpoint 线程 |
| 1303 | producer 内推 exp 队列（跳转） | **保留 `== 1`** | 模式 2 不启动 producer 线程 |

#### 4.2.2 `__init__` 中强制转 int

行 170 加类型转换，防止 form POST 字符串导致比较失败：

```python
# 改前
        self.Vulnerability_scanning = data["Vulnerability_scanning"]

# 改后
        self.Vulnerability_scanning = int(data["Vulnerability_scanning"] or 0)
```

#### 4.2.3 `run()` 方法重构

**核心思路**：模式 2 和模式 0/1 共用 exp_consumer + save_exp_result，只是不需要 web 扫描线程。所以先把队列和 exp 线程建好，再分叉。

**重构后的 `run()` 结构**：

```
run():
    # 1. 原有：更新 phase=1 (行 330)
    # 2. 原有：构建 fingerprint_exp_cache (行 192-196, 已改为 in (1,2))
    # 3. 原有：计算 fingerpoint_worker_count, exp_worker_count (行 346-351)
    #    对模式2：fingerpoint_worker_count=0, exp_worker_count=全预算
    # 4. 原有：创建队列 (行 352-353)
    #    → 模式2 的 _exp_qsize = max(100, exp_worker_count*2)
    # 5. 原有：创建 save_exp_result 线程 (行 343-344)
    # 6. 原有：创建 exp_consumer 线程 (行 357-359)
    #
    # ---- 分叉 ----
    # 7. 模式 2:
    #    → 不启动 producer / request_consumer / fingerpoint_consumer 线程
    #    → producer_done = True
    #    → 调用 _run_vuln_only_mode()
    #    → 检查 pause_requested / exit_flag
    #    → 完成/暂停处理 + return
    #
    # 8. 模式 0/1: 原有流程不变
    #    → 启动 fingerpoint_consumer 线程 (行 354-356)
    #    → 启动 producer / request_consumer 线程 (行 337-341)
    #    → 原有 drain + 完成逻辑 (行 361-433)
```

具体代码改动（逐行标注）：

```python
# ---- 行 330-336: 保持不变（update phase=1 + 缓存构建） ----

# ---- 行 346-353: 改为模式感知 ----
        fingerpoint_worker_count = min(3, max(1, min(self.thread_num, app_settings.MAX_EXPLOIT_THREAD_NUM, self._thread_budget)))
        exp_worker_count = 0
        if self.Vulnerability_scanning in (1, 2):                    # <-- 改为 in (1,2)
            exp_worker_budget = max(1, self._thread_budget - fingerpoint_worker_count)
            exp_worker_count = max(1, min(self.vulnerability_thread_num, app_settings.MAX_EXPLOIT_THREAD_NUM, exp_worker_budget))
        if self.Vulnerability_scanning == 2:
            fingerpoint_worker_count = 0                             # <-- 新增：模式2无需指纹线程
            exp_worker_count = max(1, min(self.vulnerability_thread_num, app_settings.MAX_EXPLOIT_THREAD_NUM))  # <-- 新增：全部预算给exp，加帽子
        _exp_qsize = max(10, exp_worker_count * 2)
        if self.Vulnerability_scanning == 2:
            _exp_qsize = max(100, exp_worker_count * 2)              # <-- 新增：模式2队列要大
        self.queue_EXP_input = Queue(maxsize=_exp_qsize)
        self.queue_EXP_result = Queue(maxsize=_exp_qsize)

        save_exp_result_thread = threading.Thread(target=self.save_exp_result, args=(), name='save_exp_result', daemon=True)
        save_exp_result_thread.start()
        for _ in range(exp_worker_count):
            exp_consumer_thread = threading.Thread(target=self.exp_consumer, args=(), daemon=True)
            exp_consumer_thread.start()

        # ---- 模式 2 专用分叉 ----
        if self.Vulnerability_scanning == 2:
            try:
                self._run_vuln_only_mode()
            except ValueError as exc:
                # 无资产错误向上抛，由 _run_auto_scan_task 的 except 捕获
                raise
            if self.exit_flag or self.pause_requested:
                return  # 暂停/停止已在 _run_vuln_only_mode 内写入 DB
            # 正常完成
            endtime = timezone.now()
            try:
                models.auto_scan_tasks.objects.filter(id=self.task_id).update(
                    endTime=endtime, status=1, process="100%", phase=3,
                    pause_requested=False, stop_requested=False,
                )
            finally:
                connection.close()
            return

        # ---- 模式 0/1: 原有流程（启动 web 扫描线程） ----
        for _ in range(fingerpoint_worker_count):
            fingerprint_consumer_thread = threading.Thread(target=self.fingerpoint_consumer_thread, args=(), daemon=True)
            fingerprint_consumer_thread.start()

        producer_thread = threading.Thread(target=self.producer, args=(), name='producer', daemon=True)
        producer_thread.start()
        self.request_scheduler_thread = threading.Thread(target=self.request_consumer, ...)
        self.request_scheduler_thread.start()

        # ---- 以下全部不变（行 361-433） ----
        if not self.exit_flag and self.Vulnerability_scanning in (1, 2):  # <-- 改为 in (1,2)
            ...
        # ... 原有 drain / 完成 / 暂停逻辑不变
```

#### 4.2.4 新增方法 `_run_vuln_only_mode()`

```python
def _run_vuln_only_mode(self):
    """模式 2：仅漏洞扫描。读已有资产→product→POC→入队→等结果。"""
    from app_cybersparker.models import AssetTaskRelation, auto_scan_indentify_result

    # 1. 查询该任务关联资产 ID
    close_old_connections()
    try:
        relation_ids = list(
            AssetTaskRelation.objects
            .filter(task_id=self.task_id)
            .values_list("identify_result_id", flat=True)
            .order_by("identify_result_id")
        )
    finally:
        connection.close()

    if not relation_ids:
        raise ValueError("该任务还没有资产，请先运行 Web 扫描")

    # 2. 批量取资产的 target + products
    close_old_connections()
    try:
        asset_rows = list(
            auto_scan_indentify_result.objects
            .filter(id__in=relation_ids)
            .values("id", "target", "products")
        )
    finally:
        connection.close()

    # 3. 构建 id→asset 映射 + 去重 target→products
    asset_map = {a["id"]: a for a in asset_rows}
    seen_pairs = set()
    valid_pairs = []  # [(target, products_list), ...]
    for asset_id in relation_ids:
        asset = asset_map.get(asset_id)
        if not asset or not asset["target"] or not asset["products"]:
            continue
        key = (asset["target"], frozenset(asset["products"]))
        if key not in seen_pairs:
            seen_pairs.add(key)
            valid_pairs.append((asset["target"], list(asset["products"])))

    total = len(valid_pairs)
    if total == 0:
        raise ValueError("该任务的资产均未识别到产品")

    # 4. 更新 phase
    try:
        models.auto_scan_tasks.objects.filter(id=self.task_id).update(phase=2)
    finally:
        connection.close()

    # 5. 入队 exp_consumer
    start_offset = max(0, int(self.current_line or 0))
    for idx, (target, products) in enumerate(valid_pairs):
        if self.exit_flag:
            return
        if self.check_stop_bridge():
            return

        if idx < start_offset:
            continue

        # 检查暂停（复用现有逻辑）
        if self.check_pause_signal():
            # 暂停前先排空已入队结果
            self.queue_EXP_input.put({target: products})
            self.producer_done = True
            self.queue_EXP_input.join()
            self.queue_EXP_result.join()
            self.current_line = start_offset + idx + 1
            try:
                models.auto_scan_tasks.objects.filter(id=self.task_id).update(
                    status=4, phase=3, pause_requested=False,
                    endTime=timezone.now(), current_line=self.current_line,
                )
            finally:
                connection.close()
            self.pause_requested = True
            return

        self.queue_EXP_input.put({target: products})

        # 进度更新（每 10 个写一次）
        if (idx + 1) % 10 == 0 or idx == total - 1:
            pct = min(99, round((idx + 1) / total * 100))
            self.current_line = idx + 1
            try:
                models.auto_scan_tasks.objects.filter(id=self.task_id).update(
                    process=f"{pct}%", current_line=self.current_line,
                )
            finally:
                connection.close()

    # 6. 等待队列排空
    self.producer_done = True
    if not self.exit_flag:
        self.queue_EXP_input.join()
        self.queue_EXP_result.join()
```

---

### 4.3 资源预算服务

**文件**：`app_cybersparker/services/resource_lease_service.py` 行 332

```python
# 改前
    if int(vulnerability_scanning or 0) == 1:

# 改后
    if int(vulnerability_scanning or 0) in (1, 2):
```

---

### 4.4 视图层

**文件**：`app_cybersparker/views/expload/task_manage/auto_scan_task.py`

#### 4.4.1 表单

`AutoScanTaskForm` 是 `ModelForm(Meta.model = auto_scan_tasks)`，Django ModelForm 自动从模型继承 choices。4.1 节改了 `models.py` 的 `expScan_start` 后表单自动获得新选项，**无需手动修改**。

#### 4.4.2 Task_operate (行 782-872)

**模式 2 跳过 force_refresh_engine**（行 789-791）：

```python
# 改前
    force_refresh_engine = False
    if status == "0":
        force_refresh_engine = int(row_dict.get("input_type") or 1) == 4

# 改后
    vuln_mode = int(row_dict.get("Vulnerability_scanning") or 0)
    force_refresh_engine = False
    if status == "0" and vuln_mode != 2:
        force_refresh_engine = int(row_dict.get("input_type") or 1) == 4
```

**模式 2 的 current_line 处理**（行 800-801）：

```python
# 改前
    else:
        next_current_line = int(row_dict.get("current_line") or 1)

# 改后
    elif vuln_mode == 2:
        next_current_line = int(row_dict.get("current_line") or 0)  # 资产游标从0开始
    else:
        next_current_line = int(row_dict.get("current_line") or 1)
```

**rerun 时重置 current_line**（用户可能在模式 2 和模式 0 之间切换，需防止光标串）：

```python
# status == "rerun" 分支中
    if vuln_mode == 2:
        next_current_line = 0
    elif int(row_dict.get("input_type") or 1) == 4:
        ...
```

#### 4.4.3 startTask (行 693-751)

```python
# 行 699-700: 模式 2 跳过 engine prepare
# 改前
    if task_obj and not skip_engine_prepare:
        restart_flag = ...

# 改后
    if task_obj and not skip_engine_prepare and int(task_obj.Vulnerability_scanning or 0) != 2:
        restart_flag = ...
```

---

### 4.5 tasks.py（Celery dispatch 路径）

**文件**：`app_cybersparker/tasks.py` 行 49-51

```python
# 改前
    is_restart = (task_obj.process or "0%") == "100%" or task_obj.process is None
    is_ok, error = auto_scan_task.prepare_engine_target_before_start(
        task_obj, is_restart=is_restart, force_refresh=force_refresh_engine)

# 改后
    if int(task_obj.Vulnerability_scanning or 0) != 2:
        is_restart = (task_obj.process or "0%") == "100%" or task_obj.process is None
        is_ok, error = auto_scan_task.prepare_engine_target_before_start(
            task_obj, is_restart=is_restart, force_refresh=force_refresh_engine)
    else:
        is_ok, error = True, None
```

---

### 4.6 前端 API

**文件**：`app_cybersparker/views/expload/task_manage/auto_scan_task_api.py` 行 226-230

```python
# 改前
        "vulnerability_scanning_choices": [
            {"value": 0, "label": "否"},
            {"value": 1, "label": "是"},
        ],

# 改后
        "vulnerability_scanning_choices": [
            {"value": 0, "label": "不进行漏洞扫描"},
            {"value": 1, "label": "Web扫描后漏洞扫描"},
            {"value": 2, "label": "仅漏洞扫描（跳过Web探测）"},
        ],
```

---

### 4.7 前端 UI

**文件**：`frontend/src/pages/AutoScanTaskListPage.tsx`

行 466-470 的 `<Select>` 组件已从 API 读 choices，无需改。仅需在模式 2 时隐藏 input_type 等输入源行。

```tsx
// 在 form 的 input_type / target 等 label 外包条件
{form.Vulnerability_scanning !== '2' && (
  <>
    {/* input_type Select */}
    {/* target 上传 */}
    {/* engine 配置 */}
    {/* search_query */}
  </>
)}
```

---

### 4.8 文档

- `docs/modules/03-指纹与自动识别模块.md`：补充模式 2
- `docs/当前实现总览.md`：更新漏洞扫描描述
- `docs/设计总览.md`：记录 Vulnerability_scanning 从 bool 改为 3 选 1 的设计决策

---

## 6. 不做

- 不支持跨任务资产聚合
- 不新增 Celery 队列
- 目录扫描和批量任务不受影响
- 模式 2 不支持 input_type=6（检索语句动态圈目标）

---

## 7. 风险

| 风险 | 等级 | 说明 |
|------|------|------|
| run() 重构影响模式 0/1 | 高 | 需要仔细保证 fingerpoint 线程等在模式 0/1 下顺序不变 |
| 模式 0/1 间切换 current_line 串 | 中 | rerun 时强制重置 current_line=1/0 解决 |
| 超大资产量（>10000） | 低 | .values() 查询不含 text/html 列，安全。极端场景（>100k）需分页 |

---

## 8. 改动文件汇总

| 文件 | 改动量 | 类型 |
|------|--------|------|
| `models.py` | -3+5 行 | choices 扩展 |
| `migrations/0062_*.py` | ~20 行 | 新建 AlterField |
| `auto_exp_task.py` | ~120 行 | run() 重构 + 新方法 + 4 处 in(1,2) |
| `resource_lease_service.py` | 1 行 | ==1 → in (1,2) |
| `auto_scan_task.py` | ~15 行 | 3 处跳过逻辑 + current_line 处理 |
| `tasks.py` | +5 行 | 模式 2 跳过 engine prepare |
| `auto_scan_task_api.py` | +1 项 | choices |
| `AutoScanTaskListPage.tsx` | ~10 行 | 条件隐藏 |
| `docs/*` | ~20 行 | 3 处文档 |

---

## 9. 验证计划

1. `python -m django check` — 0 issues
2. 模式 2 无资产 → 报错 "该任务还没有资产"
3. 模式 2 正常流程：模式 0 跑入库 → 模式 2 重跑 → exp_result 有正确结果
4. 模式 2 暂停→恢复：暂停后 `status=4, current_line=N` → 恢复从第 N 条继续 → 完成 status=1
5. 模式 2 无产品资产：全部跳过，报错 "资产均未识别到产品"
6. 模式 0/1 回归：run() 重构后功能不变
7. 模式 2 → rerun 切模式 0：`current_line` 重置正确，文件读取正常
8. 前端：3 选项可见，选模式 2 时输入源控件隐藏

---

## 10. 状态

- 状态：已评审（v3.1，2 MAJOR 修复：暂停 off-by-one + exp 线程帽子）
- 创建：2026-06-16
- 更新：2026-06-16（v3.1: 暂停 current_line +1 + exp_worker_count 加 MAX_EXPLOIT_THREAD_NUM 帽子）
