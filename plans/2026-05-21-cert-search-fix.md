# 资产检索：证书搜索修复 + 纯真 IP 地理位置 + 域名解析 IP

## 已完成变更

### 1. 证书搜索修复
- `_result_items.html` / standalone 模板：证书组织、主体、序列号添加点击搜索
- 侧边栏添加"证书主体/组织/部门"聚类
- 修复 `buildPageUrl` 未保存搜索词到 URL

### 2. 纯真 IP 地理位置库替换 GeoLite2
- 新建 `app_cybersparker/lib/qqwry.py`：高性能纯真数据库解析器（25MB/152万记录，二分查找 O(logN)，GBK 解码，全局单例）
- 替换 `auto_exp_task.py` 中的 `get_ip_from()`，从纯真库解析出国家、省份、城市、运营商
- 新增模型字段：`province`、`city`、`isp`（migration 0022）
- `result_event_service.py` 的 event payload 和 writer 同步更新

### 3. 域名解析 IP 字段
- `auto_exp_task.py` 的 `request_scan()` 从 aiohttp response.connection.transport 获取对端 IP
- 新增模型字段：`resolved_ip`（GenericIPAddressField）
- 通过 extra dict 完整传播到 save_indentify_to_db → event → writer

### 4. 搜索与聚类增强
- `auto_scan_result.py`：`province:`/`city:`/`isp:`（icontains）和 `resolved_ip:`（icontains，支持通配符）
- `all_Indentify_result.py`：同上
- 侧边栏新增省份、城市、运营商聚类
- JSON 响应包含新字段，模板展示新字段（可点击搜索）

## 修改文件

| 文件 | 改动 |
|------|------|
| `app_cybersparker/lib/qqwry.py` | 新建，纯真 IP 数据库解析器 |
| `app_cybersparker/models.py` | 添加 province/city/isp/resolved_ip 字段 |
| `app_cybersparker/migrations/0022_*.py` | 新建迁移 |
| `app_cybersparker/services/result_event_service.py` | event payload + writer 支持新字段 |
| `app_cybersparker/views/expload/task_manage/auto_exp_task.py` | 替换 GeoIP → qqwry，采集 resolved_ip |
| `app_cybersparker/views/expload/task_manage/auto_scan_result.py` | 搜索、facet、JSON 响应支持新字段 |
| `app_cybersparker/views/expload/result__manage/all_Indentify_result.py` | 搜索支持新字段 |
| `app_cybersparker/templates/.../auto_scan_identify_result_standalone.html` | 侧边栏 + 结果展示新字段 |
| `app_cybersparker/templates/.../_result_items.html` | 结果展示新字段（可点击搜索） |

## 验证

- Django system check: 0 issues
- 模型字段存在: province, city, isp, resolved_ip ✓
- 模板编译: OK
- qqwry 查询正确: "中国–江苏–南京" → country=中国, province=江苏, city=南京
- province/city/isp/resolved_ip 搜索语法: icontains ✓
- Facet allowed_fields 包含新字段 ✓

## 状态

已完成
