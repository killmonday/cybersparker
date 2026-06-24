# zone 字段保存不生效 — 排查与修复

## 问题

用户报告：自动扫描任务（如 id=5），创建/编辑时设置 zone="内网1"，保存后再编辑显示为"公网"。

## 排查结论

**根因**：前端 POST 数据键名 (`zone_id`) 与 Django ModelForm 字段名 (`zone`) 不匹配。

### 完整数据流

1. 前端 `AutoScanTaskListPage.tsx` 表单提交时，`FormData` 里是 `zone_id=2`（AssetZone 主键）
2. 后端 `add()`/`edit()` 创建 `ModelForm(data=request.POST)`
3. Django 表单字段名是 `zone`（ForeignKey 字段名），去找 `request.POST['zone']`
4. POST 里只有 `zone_id`，没有 `zone` → `cleaned_data['zone'] = None`
5. `construct_instance()` 执行 `instance.zone = None` → `instance.zone_id = None`
6. 模型 `save()` 检测到 `zone_id is None` → 兜底逻辑 `self.zone_id = 1`（公网）
7. 用户选的"内网1"被静默丢弃，数据库存的是公网

### 为什么其他 FK 字段没报问题

`proxy` 和 `engine_proxy` 也是 ForeignKey，前端也发 `proxy_id` / `engine_proxy_id`，理论上同样的不匹配。但它们是可空字段（`null=True, blank=True`），模型 `save()` 没有 None→默认值的兜底逻辑，所以静默失败不会产生可见错误。

## 修复

### 前端修复（根因修正）

`AutoScanTaskListPage.tsx`：表单 state 键名从 `zone_id` 改为 `zone`，与 Django ModelForm 字段名完全对齐。

POST 数据：`zone=2` → Django 表单字段 `zone` 直接绑定 → `cleaned_data['zone']=2` → `instance.zone_id=2` → DB 正确保存。

### 后端兜底（防御性保留）

`auto_scan_task.py` 的 `add()` 和 `edit()`：如果收到旧的 `zone_id`（未刷新缓存的浏览器），自动映射到 `zone`。

## 验证

- 4 个新测试全部通过
- 全量 438 测试 0 失败（3 skipped 预存）
