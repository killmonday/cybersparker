# EXP 模板 severity + tags 分类与任务过滤

- 状态：需求澄清完成，待审计
- 关联模块：02-PoC管理（插件管理）、05-异步任务（任务执行）
- 关联 Backlog：待创建

## 做什么

给 EXP（插件/PoC）表加上危害等级（severity）和标签（tags）两个分类字段，让批量漏洞任务可以按这两个维度筛选要运行的 EXP，自动扫描在指纹匹配后自动排除非漏洞类模板。

## 为什么

当前 Nuclei 模板库 12,922 个全量入库，其中 38%（4,915 个）是探测/识别/配置检查类模板（severity=info），不是漏洞。用户跑漏洞验证时，这些模板会被一起跑，产生大量无意义"漏洞结果"（如 Nginx Version Detect）。

加上分类字段后：
- 自动扫描自动跳过 severity=info 的模板
- 批量任务用户可以按 severity + tags 灵活圈定 EXP 范围

## 数据模型

### EXP 表新增字段

```python
# EXP 表
severity = models.CharField(
    max_length=10,
    choices=[
        ("critical", "严重"),
        ("high", "高危"),
        ("medium", "中危"),
        ("low", "低危"),
        ("info", "信息"),
    ],
    blank=True,       # 允许空（未设置）
    default="",
    db_index=True,
)
tags = models.ManyToManyField("Tag", blank=True, related_name="exps")
```

### Tag 表（新建）

```python
class Tag(models.Model):
    name = models.CharField(max_length=128, unique=True, db_index=True)
```

M2M 中间表自动产生 `(exp_id, tag_id)` 联合索引。

### batch_EXPTask 新增字段

```python
# 选 EXP 方式
exp_select_mode = models.SmallIntegerField(
    choices=[(1, "手动选择"), (2, "按条件筛选")],
    default=1,
)
# 筛选配置（JSON）
severity_filter = models.JSONField(null=True, blank=True)
tag_filter = models.JSONField(null=True, blank=True)
filter_logic = models.CharField(
    max_length=3,
    choices=[("AND", "AND"), ("OR", "OR")],
    default="AND",
)
```

JSON 字段结构：

```json
// severity_filter
{"mode": "include", "values": ["critical", "high", "empty"]}
// tag_filter
{"mode": "exclude", "values": [1, 2, "empty"]}
```

- `mode`: `"include"`（包含）或 `"exclude"`（排除）
- `values`: severity 值列表（5 个固定值，不允许空）或 tag ID 列表（`"empty"` 表示未设置标签）
- `filter_logic`: 两个维度都填了时的逻辑关系，AND 或 OR
- **severity 不允许空值**：创建任务时 severity 必须至少选一个值；tags 允许"未标记"选项

### 筛选语义

设为空（两个 filter 都不设或 values 都为空）时：**默认排除 severity=info**。

有筛选条件时，示例：
- severity: high/critical（mode=include） + tags: detect/tech（mode=exclude） + AND
- → severity 是 high 或 critical，且不包含 detect/tech 标签的 EXP

## 数据来源

### Nuclei YAML 模板（首次导入 / 补数据）

从 YAML 文件的 `info` 区块提取：

```yaml
info:
  name: Nginx Version Detect
  severity: info          # → EXP.severity
  tags: tech,detect,nginx # → EXP.tags（按逗号分割，每个 tag 创建或复用 Tag 记录）
```

- 首次导入时自动提取写入
- 已有 12,922 条数据通过管理命令补全（读取 `poc` FileField 对应的 YAML 文件）
- 补全策略：逐条 `yaml.safe_load()` → 提取 `info.severity` + `info.tags` → `Tag.objects.get_or_create(name=tag)` → `exp.tags.add(tag)` → `exp.save(update_fields=['severity'])`。约 12,922 条，预计 1-3 分钟。失败记录跳过并输出日志。
- severity 和 tags 来自 YAML，用户在后台页面不可编辑（nuclei_yaml 类型）

### Python3 EXP

用户在插件表单手动设置 severity（下拉选择）和 tags（多选输入）。

## 后台 EXP 页面

- 列表页：新增 severity 列（带颜色标记）、tags 列（标签样式），可按 severity 下拉筛选、按 tag 名称搜索
- 编辑页：severity 下拉选择 + tags 多选输入，所有类型 EXP 均可编辑
- 筛选：列表页可按 severity 和 tag 筛选

## 执行引擎改动

### 自动扫描（auto_exp_task.py）

漏洞扫描阶段，当前流程是 `_build_fingerprint_exp_cache()` 一次性把全部 `exp_relate_fingerprint` 关系加载到内存缓存（dict），再通过 `get_exp_ids_for_products()` 按产品名过滤出 EXP ID。

**改动点**：在 `get_exp_ids_for_products()` 返回后、传给漏洞验证循环前，加一层过滤。

注：`get_exp_ids_for_products()` 返回的是 `{exp_id: info_dict}` 字典，同时包含 python3 和 nuclei_yaml EXP（通过 `exp_relate_fingerprint` 关联）。python3 EXP 的 severity 通常为空（不会匹配 info），但为安全起见，过滤仍作用在全部 EXP 上。

```python
# auto_exp_task.py 漏洞验证阶段，get_exp_ids_for_products() 调用之后
if poc_info_dict:
    info_exp_ids = set(
        models.EXP.objects.filter(
            id__in=list(poc_info_dict.keys()), severity="info"
        ).values_list("id", flat=True)
    )
    for eid in info_exp_ids:
        del poc_info_dict[eid]
```

不改 UI，不加模型字段。

### 批量任务（batch_task_executor.py）

**表单层**（`batch_exp_task.py`）：

`batch_ExpTask_ModelForm` 当前用 `fields = [...]` 白名单方式列举字段。新增 4 个字段需要加到 `fields` 列表中：

```python
fields = [
    # ... 原有字段 ...
    "exp_select_mode",   # 1=手动选择, 2=按条件筛选
    "severity_filter",   # JSONField（前端 JS 写入）
    "tag_filter",        # JSONField（前端 JS 写入）
    "filter_logic",      # AND/OR
]
```

前端：`exp_select_mode=1` 时显示原有的插件多选框；`exp_select_mode=2` 时隐藏多选框，显示 severity 勾选 + tags 多选 + include/exclude 切换 + AND/OR 切换。

**执行层**（`batch_task_executor.py`）：

当前 `_build_exp_cache()` 从 `self.expID_list`（CharField 的逗号分隔 ID 字符串）构建缓存。新增 `exp_select_mode=2` 后，需要在上游把 `expID_list` 从筛选结果派生：

```python
# 在 operate() / startTask() 入口处
if task.exp_select_mode == 2:
    exp_qs = resolve_exp_filter(task)  # 按条件查 EXP
    return parser.parse(exp_qs.values_list("id", flat=True))  # 转为 expID_list
```

`resolve_exp_filter(task)` 构建筛选 queryset：

```python
def resolve_exp_filter(task):
    qs = models.EXP.objects.filter(plugin_language=2)
    severity_filter = task.severity_filter or {}
    tag_filter = task.tag_filter or {}
    logic = task.filter_logic or "AND"

    severity_q = _build_severity_q(severity_filter)
    tag_q = _build_tag_q(tag_filter)

    # 两个都为空 → 默认排除 severity=info
    if not severity_q and not tag_q:
        return qs.exclude(severity="info")

    if logic == "AND":
        if severity_q and tag_q:
            return qs.filter(severity_q & tag_q)
        return qs.filter(severity_q or tag_q)
    else:
        q = Q()
        if severity_q: q |= severity_q
        if tag_q: q |= tag_q
        return qs.filter(q)


def _build_severity_q(filter_cfg):
    mode = filter_cfg.get("mode", "include")
    values = [v for v in filter_cfg.get("values", []) if v != "empty"]
    has_empty = "empty" in filter_cfg.get("values", [])
    if not values and not has_empty:
        return None
    q = Q()
    if values:
        q |= Q(severity__in=values)
    if has_empty:
        q |= Q(severity="")
    if mode == "exclude":
        q = ~q
    return q


def _build_tag_q(filter_cfg):
    mode = filter_cfg.get("mode", "include")
    tag_ids = [v for v in filter_cfg.get("values", []) if v != "empty"]
    has_empty = "empty" in filter_cfg.get("values", [])
    if not tag_ids and not has_empty:
        return None
    q = Q()
    if tag_ids:
        q |= Q(tags__id__in=tag_ids)
    if has_empty:
        q |= Q(tags__isnull=True)
    if mode == "exclude":
        q = ~q
    return q
```

## 迁移计划

1. 创建 Tag 模型 + M2M → mig 0043
2. EXP 加 severity → mig 0044

注意：分两步迁移，0043 先建 Tag 表，0044 再加 severity 字段，中间可以补数据。

## 索引策略

| 索引 | 位置 | 用途 |
|------|------|------|
| `severity` | EXP 表 | `WHERE severity != 'info'` |
| `name` | Tag 表 | `WHERE name = 'xss'` |
| `(exp_id, tag_id)` | M2M 中间表 | `JOIN` 自动创建 |

## 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| 12,922 个 YAML 全量解析耗时 | 低 | 管理命令逐条处理，预计 30s-2min |
| YAML 文件可能不存在（路径迁移） | 低 | 解析失败跳过，记录日志 |
| 批量任务现有 EXP 字段（CharField 存插件名）与新筛选模式共存 | 低 | `exp_select_mode=1` 时走原逻辑，=2 时走新逻辑 |
| severity=info 误杀 | 低 | info 级模板 99% 是非漏洞探测，极少数 info 级漏洞（如低危信息泄露）用户可通过批量任务筛选模式手动纳入 |

## 不做

- 不做 severity 值的自定义（用户不能新增或修改 severity 枚举值）
- 不做 Tag 管理页面（CRUD 通过 Django Admin 或命令行）
- 不做标签层级（父子标签、分类）
- 不修改 Python3 EXP 的自动分类（完全由用户手设）
- 不修改目录扫描（漏洞引擎未接入）
- 不修改单任务
