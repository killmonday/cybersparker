# seed_data.sql 头部污染修复

## 做什么

- 给 `deploy/seed/export_seed_data.sh` 补回归测试，确保生成的 `seed_data.sql` 头部只包含 SQL 注释，不混入 shell 命令。
- 修复导出脚本 heredoc 写法，避免把 `date` 和 `cat >>` 文本写进 SQL 文件。
- 修正仓库里的 `deploy/seed/seed_data.sql` 头部内容，保证生产环境可直接 `psql < seed_data.sql` 导入。
- 同步更新部署模块文档、种子数据说明和 CHANGELOG。

## 为什么做

生产环境 fresh deploy 时，`docker-entrypoint.sh` 会在指纹表为空时自动执行 `deploy/seed/seed_data.sql`。
当前 SQL 文件头部混入了：

- `date '+%Y-%m-%d %H:%M:%S' >> "${OUTPUT}"`
- `cat >> "${OUTPUT}" << 'HEADER'`

PostgreSQL 读到这些文本会把它们当 SQL 执行，直接在 `date` 处报语法错误，导致种子数据导入失败。

## 怎么做

1. 先补一个最小回归测试：复制导出脚本到临时目录，用假的 `psql/pg_dump` 生成测试用 seed 文件，断言输出中不包含 shell 命令文本。
2. 跑目标测试，确认当前脚本会失败。
3. 修复 `export_seed_data.sh` 的文件头生成逻辑。
4. 修正仓库内 `seed_data.sql` 头部内容。
5. 运行目标测试和相关自检。
6. 同步 backlog / 项目控制台 / 模块文档 / README / CHANGELOG。

## 风险

- 如果只修脚本不修仓库内现有 `seed_data.sql`，生产环境仍会继续用坏文件报错。
- 如果测试直接执行真实导出脚本到仓库目录，可能误覆盖正式种子文件，所以测试必须在临时目录里跑。

## 状态

- 2026-06-23 已完成：已按 TDD 补回归测试、修复导出脚本 heredoc 头部生成逻辑、重新导出仓库内 `deploy/seed/seed_data.sql`，并同步部署文档与 backlog 状态。

## 验证结果

- `python manage.py test app_cybersparker.tests.SeedExportScriptTests --verbosity 2`：2/2 通过
- `python manage.py test --verbosity 1`：446 tests 全量通过（3 skipped）
- `python manage.py check`：0 issues
- `bash -n deploy/seed/export_seed_data.sh`：通过
- 重新执行 `bash deploy/seed/export_seed_data.sh`：成功生成新的 `deploy/seed/seed_data.sql`
- 检查 `deploy/seed/seed_data.sql` 头部：已为纯 SQL 注释，首个非注释内容回到 pg_dump 正常输出

## 剩余风险

- 当前执行 `bash deploy/seed/export_seed_data.sh` 时会打印 locale warning，但不影响种子文件生成和导入；本轮未处理环境 locale 配置。
- backlog 当前保持“已完成 / 待验收”口径，表示本地修复和自检已完成，是否记为“已验收”留给后续验收动作统一收口。
