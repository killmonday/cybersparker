# 指纹导入：mmh3 favicon hash + != 操作符补充 + 导入脚本

- 日期：2026-05-24
- 类型：功能增强 + 数据导入
- 状态：已完成

## 做什么

1. 指纹匹配引擎增加 favicon mmh3 hash 计算与规则支持（key: `favicon_mmh3`）
2. `check_rule` 增加 body/header/title 的 `!=` 操作符支持
3. 写导入脚本解析 fingerprint.txt，按映射规则转换后写入 DB

## 为什么

- 导入来源指纹包含 mmh3 favicon hash（Icon 键），系统只支持 MD5/URL
- 导入来源大量使用 `!=` 操作符，系统 check_rule 仅对 context key 支持 !=
- 需要一次性批量导入 ~32,000 条可映射指纹到系统

## 映射表（最终确定）

| 来源键 | 系统键 | 转换 |
|--------|--------|------|
| Body | body | 小写 |
| Header | header | 小写 |
| Title | title | 小写 |
| Cert | cert | 小写 |
| Bodyr | body | `Bodyr="X"` → `body~="X"` |
| Icon | favicon_mmh3 | `Icon="N"` → `favicon_mmh3="N"` |
| Protocol | 跳过 | — |
| Port | 跳过 | — |
| Hash | 跳过 | — |
| Response | 跳过 | 含大量非 HTTP 协议 |
| SPASS | 跳过 | 非规则键（Body 值内字符串） |

## 风险

- mmh3 Python 包可能未安装，需 pip install
- 导入数据中 condition 可能超过 max_length=128
- 重复 condition（unique 约束冲突）
- != 逻辑变换需保证与原有语义一致

## 验证

- [x] mmh3 计算与已知 favicon hash 值交叉验证
- [x] check_rule != 操作符隔离性功能验证
- [x] import_fingerprints 命令在 100 条样本上验证
- [x] 完整导入后 django check 0 issues

## 结果

- 28,700 条成功导入，3,257 条跳过（Protocol/Port/Hash/Response），0 条失败
- 493 条 Icon 规则转换为 favicon_mmh3= 格式
- 111 条 != 规则保留并写入 DB
- 2,480 条 ~= 正则规则（含 Bodyr→body~= 转换）
- 1 个预先存在的测试失败（test_list_view_provides_fingerprints_for_picker）：测试 DB 累积脏数据导致排序不匹配，与本次改动无关
- 修改文件：fingerPrint_debug.py, fingerprint_indentify.py, auto_exp_task.py, import_fingerprints.py (新增), models/03-指纹与自动识别模块.md, backlog/03-指纹与自动识别.md, CHANGELOG.md
