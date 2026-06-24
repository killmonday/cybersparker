# 漏洞结果关联根资产：identify_result_id 集中写入方案

> 审核状态：Architect v2 PARTIALLY APPROVE → 修复后 Critic REJECT（2致命+1严重）→ 修订为 v3 → 2026-06-14 实现完成

## 目标

三种任务（自动扫描、目录扫描、批量任务）产出的漏洞统一通过 `identify_result_id` 关联到 `auto_scan_indentify_result`，资产检索页能跨任务展示和搜索所有漏洞。

## 核心思路

只改写入点 `_write_auto_exp_event`：从 target URL 解析 `(protocol, host, port)`，`get_or_create` 查/建资产，拿到 `identify_result_id` 写入 `auto_scan_exp_result`。

不碰 shuffle_file、Redis、DirScanPool、Phase 1/3、pool.recover()。

## 改动清单

### 1. 数据模型

```python
# auto_scan_exp_result 新增
identify_result_id = models.IntegerField(null=True, blank=True, db_index=True)
```

### 2. 写入点 result_event_service.py

```python
from urllib.parse import urlparse
from functools import lru_cache

@lru_cache(maxsize=256)
def _resolve_identify_result_id(target):
    parsed = urlparse(target)
    protocol = parsed.scheme or "http"
    host = parsed.hostname or ""
    port = parsed.port or (443 if protocol == "https" else 80)
    asset, _ = models.auto_scan_indentify_result.objects.get_or_create(
        protocol=protocol, host=host, port=port,
        defaults={"target": f"{protocol}://{host}:{port}", "products": []},
    )
    return asset.id


def _write_auto_exp_event(payload):
    target = _strip_nul(payload["target"])[:128]
    identify_result_id = _resolve_identify_result_id(target)
    # ... existing EXP_id logic ...
    models.auto_scan_exp_result.objects.create(
        task_id=payload["task_id"],
        task_type=payload.get("task_type", 1),
        identify_result_id=identify_result_id,
        target=target,
        EXP_id=exp_obj,
        product=...,
        result=...,
    )
```

### 3. 查询端 7 处（含 vuln_by_key 映射变更 + task_type 决策）

**task_type 决策**：列表区和导出保留 `task_type=1`（只展示自动扫描+目录扫描的漏洞，批量任务暂不同步）；facet 和搜索路径放宽为 `IN (1,2,3)`（统计和过滤覆盖全量）。批量任务的列表展示待写入路径验证稳定后再开放。

#### #1 Task_result 列表区（auto_scan_result.py ~L760-780）

```python
# 改前
targets = list({item.target for item in items})
vuln_rows = auto_scan_exp_result.objects.filter(target__in=targets, task_type=1)
vuln_by_key.setdefault(row.target, []).append(row)
vulns = vuln_by_key.get(item.target, [])

# 改后
asset_ids = [item.id for item in items]
vuln_rows = auto_scan_exp_result.objects.filter(identify_result_id__in=asset_ids, task_type=1)
vuln_by_key.setdefault(row.identify_result_id, []).append(row)
vulns = vuln_by_key.get(item.id, [])
```

#### #2 global_asset_search 列表区（auto_scan_result.py ~L1005-1040）

```python
# 改前
targets = list({item.target for item in items})
vuln_rows = auto_scan_exp_result.objects.filter(target__in=targets, task_type=1)
vuln_by_key.setdefault(row.target, []).append(row)
vulns = vuln_by_key.get(item.target, [])

# 改后
asset_ids = [item.id for item in items]
vuln_rows = auto_scan_exp_result.objects.filter(identify_result_id__in=asset_ids, task_type=1)
vuln_by_key.setdefault(row.identify_result_id, []).append(row)
vulns = vuln_by_key.get(item.id, [])
```

#### #3 ip_detail_api（auto_scan_result.py ~L1228-1260）

```python
# 改前
targets = list({a.target for a in assets})
vuln_rows = auto_scan_exp_result.objects.filter(target__in=targets, task_type=1)
vuln_by_key.setdefault(vr.target, []).append(vr)
for vr in vuln_by_key.get(a.target, []):
    vulns_flat.append(...)

# 改后
asset_ids = [a.id for a in assets]
vuln_rows = auto_scan_exp_result.objects.filter(identify_result_id__in=asset_ids, task_type=1)
vuln_by_key.setdefault(vr.identify_result_id, []).append(vr)
for vr in vuln_by_key.get(a.id, []):
    vulns_flat.append(...)
```

#### #4 build_facet_result vuln/cve facet SQL（auto_scan_result.py ~L570）

```sql
-- 改前
JOIN auto_scan_exp_result AS exp_result
  ON identify.target = exp_result.target AND exp_result.task_type = 1

-- 改后
JOIN auto_scan_exp_result AS exp_result
  ON identify.id = exp_result.identify_result_id AND exp_result.task_type IN (1, 2, 3)
```

#### #5 build_related_exp_exists（asset_search_parser.py ~L148）

```sql
-- 改前
JOIN auto_scan_exp_result AS exp_result
  ON identify.target = exp_result.target AND exp_result.task_type = 1

-- 改后
JOIN auto_scan_exp_result AS exp_result
  ON identify.id = exp_result.identify_result_id AND exp_result.task_type IN (1, 2, 3)
```

#### #6 build_related_exp_lookup（asset_search_parser.py ~L172）

同上，`identify.target = exp_result.target` → `identify.id = exp_result.identify_result_id`，`task_type = 1` → `task_type IN (1, 2, 3)`。

#### #7 tasks.py 导出（~L425）

```python
# 改前
targets = list({item.target for item in items})
vuln_rows = auto_scan_exp_result.objects.filter(target__in=targets, task_type=1)
vuln_by_key.setdefault(row.target, []).append(row)
vulns = vuln_by_key.get(item.target, [])

# 改后
asset_ids = [item.id for item in items]
vuln_rows = auto_scan_exp_result.objects.filter(identify_result_id__in=asset_ids, task_type=1)
vuln_by_key.setdefault(row.identify_result_id, []).append(row)
vulns = vuln_by_key.get(item.id, [])
```

### 4. 批量任务写 auto_scan_exp_result（必做）

`batch_task_executor.py` 的 `save_TaskResult` 有两处 flush，**两处都要追加**：

```python
# 行 ~438：缓存满 100 条 flush
publish_result_events(STREAM_BATCH_EXP, cache)
publish_result_events(STREAM_AUTO_EXP, auto_payloads)  # ← 新增
throttle_dispatch_result_writer(STREAM_BATCH_EXP)
throttle_dispatch_result_writer(STREAM_AUTO_EXP)         # ← 新增

# 行 ~454：退出前清空剩余缓存
publish_result_events(STREAM_BATCH_EXP, cache)
publish_result_events(STREAM_AUTO_EXP, auto_payloads)  # ← 新增
```

其中 `auto_payloads` 从 `cache` 转换：对每条 result 调用 `build_auto_exp_event_payload(task_id, None, target, "", result, plugin_name=plugin_name, task_type=3)`。需 import `build_auto_exp_event_payload` 和 `STREAM_AUTO_EXP`。

### 5. 已有数据回填（Python 脚本）

```python
def backfill_identify_result_id():
    from urllib.parse import urlparse
    from django.db import connection

    rows = models.auto_scan_exp_result.objects.filter(
        identify_result_id__isnull=True
    ).values_list('id', 'target')
    total = rows.count()
    updated = 0

    updates = []
    for exp_id, target in rows:
        parsed = urlparse(target)
        protocol = parsed.scheme or "http"
        host = parsed.hostname or ""
        port = parsed.port or (443 if protocol == "https" else 80)
        asset = models.auto_scan_indentify_result.objects.filter(
            protocol=protocol, host=host, port=port
        ).values_list('id', flat=True).first()
        if asset:
            updates.append((asset, exp_id))
        if len(updates) >= 5000:
            with connection.cursor() as c:
                c.executemany(
                    'UPDATE auto_scan_exp_result SET identify_result_id = %s WHERE id = %s',
                    updates,
                )
            updated += len(updates)
            updates = []

    if updates:
        with connection.cursor() as c:
            c.executemany(
                'UPDATE auto_scan_exp_result SET identify_result_id = %s WHERE id = %s',
                updates,
            )
        updated += len(updates)

    print(f"回填完成: {updated}/{total} ({(updated/total*100):.1f}%)")
    return updated / total
```

覆盖率 > 95% 视为达标（<5% 无法解析的 target 多为异常格式 URL）。

### 6. 部署顺序

```
1. 跑 migration：新增 identify_result_id 字段
2. 部署写入端代码（_resolve_identify_result_id + _write_auto_exp_event 改动）
3. 跑回填脚本
4. 部署查询端代码（7 处查询点 + vuln_by_key 映射变更）
```

写入端先上线，新写入的记录自带 `identify_result_id`。旧记录靠回填补齐。查询端最后上线。

## 不做

- 不修改 shuffle_file、Redis、DirScanPool、Phase 1/3、pool.recover()
- 不修改 `auto_scan_directory_result` 模型
- 不修改 `build_related_exp_facet`（死代码）
- 列表区暂不放开 task_type=3（批量任务写入路径稳定后再开放）

## vuln_by_key 变更对照

| 查询点 | 旧 key | 旧 lookup | 新 key | 新 lookup |
|--------|--------|-----------|--------|-----------|
| Task_result | `row.target` | `item.target` | `row.identify_result_id` | `item.id` |
| global_asset_search | `row.target` | `item.target` | `row.identify_result_id` | `item.id` |
| ip_detail_api | `vr.target` | `a.target` | `vr.identify_result_id` | `a.id` |
| tasks.py 导出 | `row.target` | `item.target` | `row.identify_result_id` | `item.id` |

## 风险

| 风险 | 等级 | 措施 |
|------|------|------|
| 并发创建资产 | 低 | `get_or_create` 内部 savepoint 隔离 |
| 回填不精确 | 低 | Python urlparse 逐条解析，覆盖率 > 95% |
| 写入多一次 DB 查询 | 低 | lru_cache(256)，同批次不重复查 |
| 查询端先于写入端上线 | 高 | 部署顺序严格：写入端 → 回填 → 查询端 |
| 批量任务最后一批 <100 条漏写 | 已修复 | 两处 flush 都追加 STREAM_AUTO_EXP |
| lru_cache 孤儿引用 | 低 | cache=256，事务回滚后一段时间内可能返回无效 id，无 FK 约束不抛异常，自然淘汰 |

## 验证

- [ ] migration 正常执行
- [ ] Django check 0 issues
- [ ] `_resolve_identify_result_id` 并发安全（两个写入同一新资产 → 一个 create 一个 get_or_create 重查）
- [ ] `_resolve_identify_result_id` 对已存在资产正确命中（不创建重复记录）
- [ ] `_resolve_identify_result_id` 对不存在资产正确创建最小记录
- [ ] 回填覆盖率 > 95%
- [ ] 资产检索页列表区：三种任务的漏洞在对应资产行正确展示
- [ ] 资产检索页列表区：vuln_by_key 映射正确，无漏展示
- [ ] 左侧统计区 vuln/cve facet 数字与列表区一致
- [ ] 全局搜索 vuln/cve 过滤正常（含 task_type=2 的漏洞）
- [ ] CSV 导出包含漏洞数据且正确关联资产
