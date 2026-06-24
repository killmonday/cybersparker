# 种子数据

Docker 全新部署时，Django `migrate` 命令只创建空表。`seed_data.sql` 用于导入运行所需的参考数据。

## 包含的数据（9 张表，约 14.4 万行）

| 表 | 行数 | 说明 |
|---|------|------|
| `fingerprint` | 34,017 | 指纹规则（产品/服务的 HTTP 响应特征） |
| `exp` | 11,113 | PoC 插件元数据（Python/Nuclei YAML 插件信息） |
| `exp_relate_fingerprint` | 28,240 | 指纹与 PoC 插件的匹配关系 |
| `tag` | 8,200 | 插件分类标签 |
| `exp_tags` | 62,381 | 插件与标签的多对多关联 |
| `cveextensions` | 5 | CVE 漏洞扩展信息 |
| `dirscandictgroup` | 1 | 目录扫描字典组 |
| `dirscandict` | 1 | 目录扫描字典（路径列表） |
| `dirscandict_groups` | 1 | 字典与字典组关联 |

## Docker 启动时自动创建（无需导入）

| 数据 | 来源 | 说明 |
|------|------|------|
| 所有表结构 | `docker-entrypoint.sh` → `migrate --noinput` | Django migration 建表 |
| admin 管理员 | migration 0073 `init_super_admin` | admin/admin，超级管理员 |
| assetzone（公网） | migration 0075 `insert_system_zone` | code=public 的默认扫描区域 |

## 不包含的数据（需部署后手动配置）

- `proxysetting` — 代理配置
- `cyberspaceenginesetting` — 空间测绘引擎 API 密钥
- `ai_model_config` — AI 模型 API 密钥
- `ceyeconfig` — CEYE OOB 平台配置
- 所有运行时数据（任务、结果、资产、导出记录等）

## Docker 部署（自动导入）

**无需手动操作。** `docker-entrypoint.sh` 在 `migrate` 之后会自动检测：

- 如果 `fingerprint` 表为空 → 自动导入 `seed_data.sql`
- 如果 `fingerprint` 表已有数据 → 跳过（说明之前已导入过）

```bash
# 首次部署，一条命令搞定
docker compose up -d
# 日志中会看到：
#   [entrypoint] importing seed data (fingerprint table is empty)...
#   [entrypoint] seed data imported successfully
```

日志位置：`docker compose logs web | grep seed`

## 宿主机手动导入

不用 Docker 时，手动执行：

```bash
# 先 migrate（创建表结构 + admin + 公网区域）
python manage.py migrate

# 再导入种子数据
PGPASSWORD=yourpassword psql -h localhost -p 5432 -U postgres cybersparker < deploy/seed/seed_data.sql
```

## 配套文件

种子数据只包含数据库记录。PoC 插件文件（`EXP_plugin/*.py`、`EXP_plugin/*.yaml`）需要另外拷贝：

```bash
rsync -av EXP_plugin/ user@new-vps:/path/to/cybersparker/EXP_plugin/
```

Docker 部署时 `EXP_plugin/` 已通过 volume 挂载（`docker-compose.yml`），文件放入项目目录即可。

## 重新生成

当开发环境的参考数据有更新时（新增指纹、新增插件等），重新生成种子文件：

```bash
bash deploy/seed/export_seed_data.sh
```

脚本会自动统计导出前后的行数并打印对比。

## ID 重整

多次清空表再重新导入数据后，ID 会因为序列未重置而膨胀（如指纹表 3.4 万行但 ID 最大 13 万）。`reset_ids.sql` 将所有参考表 ID 重整为 1..N：

```bash
docker compose exec -T postgres psql -U postgres cybersparker < deploy/seed/reset_ids.sql
```

如果同时重导了种子数据，建议先导入再重整：

```bash
# 先导入
docker compose exec -T web psql -h postgres -U postgres cybersparker < deploy/seed/seed_data.sql

# 再重整 ID
docker compose exec -T postgres psql -U postgres cybersparker < deploy/seed/reset_ids.sql
```
