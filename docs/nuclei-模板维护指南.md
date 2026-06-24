# Nuclei 模板维护指南

本文档覆盖 nuclei 模板的增量导入、去重机制、日常维护命令。协议支持边界见 `docs/nuclei-协议支持边界与模板清理.md`。

## 增量导入流程

### 一句话

脚本先拉取上游模板仓库，然后跟数据库里已有的模板（按 SHA256 指纹）比对，只导入新的，跳过已存在的。

### 执行命令

```bash
python manage.py import_nuclei_templates --source /tmp/nuclei-templates --sync-mode
```

参数说明：

| 参数 | 作用 |
|------|------|
| `--source` | 模板源目录（默认 `/tmp/nuclei-templates`） |
| `--sync-mode` | 开启增量模式，按 SHA256 去重，已存在则跳过 |
| `--dry-run` | 只统计不写入 |
| `--limit N` | 限制导入数量（0=全部） |
| `--skip-matching` | 跳过指纹自动匹配 |
| `--no-pull` | 跳过 git pull |

### 完整流程

```
用户执行命令
  → [0] git pull --ff-only 拉取上游最新模板
  → [1] 加载指纹库
  → [2] 遍历所有 YAML，逐个处理：
      - 解析失败 → 跳过
      - 不支持协议（code/javascript/headless/file/dns/ssl/websocket/whois）→ 跳过
      - SHA256 已存在 → 跳过
      - 新模板 → 创建 EXP 记录 + 复制文件到 EXP_plugin/ + 指纹匹配
  → 输出统计报告
```

## 去重机制

### 核心字段：`EXP.poc_content`

导入脚本计算模板文件的 SHA256，存入 `EXP.poc_content`。后续 `--sync-mode` 导入时，对比文件 SHA256 与数据库已有记录，相同则跳过。

### 与后台修改的关系

| 操作 | 磁盘文件 | `poc_content`（DB） | 下次同步行为 |
|------|---------|-------------------|-------------|
| 导入时写入 | 创建 | 写入 SHA256 | — |
| 用户在调试页改模板内容 | 覆盖 | **不变**（表单排除该字段） | 识别为已存在，跳过 |
| 用户在插件列表页改标题/CVE/tags | 不变 | **不变** | 识别为已存在，跳过 |
| nuclei 官方更新该模板 | — | — | 新 SHA256 → 作为新模板导入 |

关键结论：`poc_content` 是"导入时的原始指纹"，它保证了——**同一个模板只导入一次，不会因为用户在后台改模板内容就重新导入**。

这个设计的代价：如果 nuclei 官方更新了一个模板，因为新文件的 SHA256 不同，它会被当作一个全新模板导入。旧模板不会自动被替换。

### 为什么不自动覆盖旧模板

nuclei 官方更新模板时，我们无法区分两种情况：

1. 用户改过这个模板 → 覆盖会丢失用户的修改
2. 用户没改过 → 覆盖是正确的升级行为

当前设计选择保守策略（不覆盖），保证用户修改不丢失。

## 导入时的过滤

### 不支持协议

`import_nuclei_templates` 与 `nuclei_runtime_engine` 共用同一个 `find_unsupported_nuclei_protocols` 函数。

不支持的协议（`UNSUPPORTED_NUCLEI_PROTOCOLS`）：

```
code, javascript, headless, file, dns, ssl, websocket, whois
```

引擎只支持 `http`/`requests` 和 `tcp`/`network` 两种协议，其余在导入时直接跳过。

### severity=info 模板

**不跳过。** severity=info 的模板（版本探测、指纹识别等非漏洞类）正常入库。

它们在自动扫描执行阶段被跳过（`auto_exp_task.py` 中 `relate.EXP_id.severity == "info"` 过滤），但保留在库中，供批量任务手动选择运行。

## 模板在库中的存储

每个 nuclei 模板在系统中对应：

- **`EXP` 表**：一条记录，`plugin_language=2`（nuclei_yaml），`Type=12`（other）
  - `title`：`[模板名]{hash前8位}`，如 `[CVE-2024-1234]{a1b2c3d4}`
  - `poc`：文件路径，如 `EXP_plugin/cve-2024-1234_a1b2c3d4.yaml`
  - `poc_content`：SHA256 指纹
  - `severity`：来自 YAML 的 info 字段
  - `tags`：来自 YAML 的 tags 字段
- **`EXP_plugin/` 目录**：YAML 文件副本（导入时 `shutil.copy2`）
- **`exp_relate_fingerprint` 表**：自动匹配的指纹绑定（B1/B2/B3 三种策略）

## 日常维护命令

### 增量导入（最常用）

```bash
python manage.py import_nuclei_templates --source /tmp/nuclei-templates --sync-mode
```

### 预览（不写入）

```bash
python manage.py import_nuclei_templates --source /tmp/nuclei-templates --sync-mode --dry-run
```

### 跳过指纹匹配（纯导入）

```bash
python manage.py import_nuclei_templates --source /tmp/nuclei-templates --sync-mode --skip-matching
```

### 清理不支持协议的历史模板

```bash
python manage.py cleanup_nuclei_unsupported_templates --dry-run   # 先看统计
python manage.py cleanup_nuclei_unsupported_templates             # 确认后执行
```

## 相关文件

| 文件 | 用途 |
|------|------|
| `app_cybersparker/management/commands/import_nuclei_templates.py` | 导入脚本 |
| `app_cybersparker/management/commands/cleanup_nuclei_unsupported_templates.py` | 清理不支持协议模板 |
| `app_cybersparker/views/expload/task_manage/nuclei_runtime_engine.py` | 运行时引擎（含 `UNSUPPORTED_NUCLEI_PROTOCOLS`） |
| `app_cybersparker/views/expload/task_manage/auto_exp_task.py` | 自动扫描执行（severity=info 过滤） |
| `app_cybersparker/views/expload/exp_debug.py` | 调试页（模板编辑保存） |
| `app_cybersparker/models.py` | `EXP` 模型（`poc_content`/`poc`/`plugin_language` 等字段） |
| `docs/nuclei-协议支持边界与模板清理.md` | 协议支持边界说明 |
| `docs/后续开发事项.md` | 已决策但不立即执行的改进方向 |

## 已知限制与后续改进

1. **不能自动覆盖更新的模板**：nuclei 官方更新模板后，旧版保留，新版作为独立模板导入。解决方向：维护一个"用户是否修改过"的标记，未修改的模板可自动覆盖。
2. **去重依赖 SHA256，不能处理模板改名**：nuclei 官方改了模板文件名但内容相同 → SHA256 相同 → 正确跳过。但内容微调（修了个正则）→ SHA256 不同 → 作为新模板导入。
3. **没有模板版本追踪**：导入后无法回看"这个模板是哪天从哪个 nuclei commit 同步的"。
