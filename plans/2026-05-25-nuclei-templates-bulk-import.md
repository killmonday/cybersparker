# Nuclei 官方模板批量导入与自动绑定方案（2026-05-25）

## 做什么

把 Nuclei 官方模板库（约 1.3 万个 YAML 模板）批量导入本系统，全量创建 EXP 记录并存入 POC 文件，同时用多轮自动匹配策略将模板与系统中已有的指纹进行绑定。无法自动匹配的模板照样导入，只是暂时没有指纹绑定。

## 为什么

- 当前系统只有 1 个 nuclei YAML 插件，虽然运行时已完整支持，但没有模板可用等于空跑。
- 1.3 万个模板手动逐条录入 + 逐条绑定指纹不可行。
- 自动匹配策略经过 200 模板验证（`validate_nuclei_fingerprint_match.py`），技术路线可行。

## 怎么做

### 总体流程

```
[阶段A] 模板导入 → [阶段B] 自动匹配指纹 → [阶段C] 匹配结果审核 → [阶段D] 增量更新
```

### 阶段 A：模板批量导入

#### A1. 模板来源

从 `projectdiscovery/nuclei-templates` 仓库（已克隆到 `/tmp/nuclei-templates`，共 12922 个非 workflows/helpers YAML 文件）。

#### A2. 导入策略

- 先解析 YAML 的 `info` 部分提取元信息（标题、CVE、描述、标签、metadata.product 等）
- 按 `info.name` + YAML 内容 SHA256 去重（避免重复导入）
- 每个模板创建一条 EXP 记录：
  - `title` = 模板文件名与 `info.name` 组合
  - `CVE` = 从 `info.classification.cve-id` 提取，多个用逗号分隔
  - `plugin_language` = 2（nuclei_yaml）
  - `Type` = 默认 1（其他），后续可按模板类别细分
  - `use` = 1（参与使用）
  - `poc` = YAML 文件路径（复制到 `EXP_plugin/` 目录）
- 错误容忍：单个 YAML 解析失败不中断整批，记录失败列表

#### A3. 实现方式

新增 Django management command：

```bash
python manage.py import_nuclei_templates \
    --source /tmp/nuclei-templates \
    --limit 100    # 可选，分批控制
```

关键实现要点：
- 用 `/tmp/nuclei-templates` 仓库路径，由脚本 `rglob("*.yaml")` 遍历
- YAML 解析同 `nuclei_runtime_engine._load_template_dict()` 的处理方式（hex 检测、preprocessor 替换等）
- 每 100 条 commit 一次，减少内存压力
- 导入前检查 SHA256 去重：SHA256(YAML 原始内容) 在 EXP.poc_content 字段或单独索引
- 每条成功/失败都输出到日志

### 阶段 B：自动匹配指纹

基于 200 模板验证结果（见 `validate_nuclei_fingerprint_match.py`），四轮匹配策略：

#### B1：metadata.product 匹配（高置信度，自动绑定）

- 从 `info.metadata.product` 提取产品名
- 对 `fingerPrint.product` 做精确匹配 → 包含匹配 → 模糊匹配（阈值 0.75）
- 验证结果：46% 模板有 metadata.product，高置信度绑定率 ~28%

#### B2：CVE 继承（高置信度，自动绑定）

- 从 `info.classification.cve-id` 提取 CVE 编号
- 查找已有 EXP 中同 CVE 的指纹绑定关系，继承过来
- 这是一个滚雪球效应：B1 绑得越多，B2 能继承的越多

#### B3：tags + name 关键词提取（中置信度，标记 auto 待审核）

- 剔除 100+ 个非产品标签（`vuln/intrusive/passive/kev/edb/cloud/devops/...` 等）
- 剩余 tag / 模板名首段 与指纹名做精确包含匹配
- 阈值调整到 0.70 以减少噪音

#### B4：剩余模板不绑定

- 未匹配到的模板仍然导入，`exp_relate_fingerprint` 中无对应记录
- 后续可在指纹调试页或专门的审核页中人工补绑

### 阶段 C：匹配结果审核

新增或增强一个审核界面：

- 按绑定置信度分组展示：高（绿色）/ 中（黄色）/ 未绑定（红色）
- 支持：
  - 批量确认高置信度绑定
  - 单条修正/解除绑定
  - 搜索筛选（按模板名、指纹名、CVE 号）
- 在 `exp_relate_fingerprint` 表中记录绑定来源（`source_auto_b1` / `source_auto_b2` / `source_auto_b3` / `source_manual`），不过当前模型无此字段，改为在日志中记录或后续按需加字段

### 阶段 D：增量更新

写一个简单的增量同步脚本，后续 nuclei 官方更新时可以跑：

```bash
python manage.py import_nuclei_templates \
    --source /tmp/nuclei-templates \
    --sync-mode  # 只导入本地没有的新模板/变更模板
```

去重依据：`info.name` + SHA256(YAML 内容)。

## 技术要点

### 导入脚本核心逻辑

```python
# 伪代码
def handle():
    existing_sha256 = set(EXP.objects.filter(
        plugin_language=2
    ).values_list('poc_content', flat=True))

    for yaml_path in Path(source).rglob("*.yaml"):
        raw = yaml_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in existing_sha256:
            continue  # 已导入，跳过

        doc = yaml.safe_load(raw)
        info = doc.get("info") or {}

        exp = EXP(
            title=f"[{info.get('name')}] {yaml_path.name}",
            CVE=_extract_cve(info),
            plugin_language=2,
            # poc 字段是 FileField，需特殊处理
        )
        # ... 创建记录 + 复制 YAML 文件到 EXP_plugin/
```

### POC 文件存储

- 每个 YAML 复制到 `EXP_plugin/` 目录
- 文件命名：`[CVE-YYYY-NNNNN]模板名_{hash8}.yaml`（和现有约定一致）
- EXP.poc 字段存储相对路径
- 不需要预编译为 `__yaml_runtime__/*.py`：YAML 是唯一真源，运行时直接调 `run_nuclei_template()`（5/25 重构已去掉中间 `.py` 编译层）

### 指纹匹配性能

当前 `_build_fingerprint_exp_cache()` 每次都加载全量 `exp_relate_fingerprint`。导入完成后绑定关系可能从几条增长到几万条。

优化方案：
- 匹配阶段不需要在线查询，直接在导入脚本内用内存 dict 完成
- 匹配结果批量写入 `exp_relate_fingerprint`
- 最终运行时 `_build_fingerprint_exp_cache()` 的查询结果数量取决于指纹命中的 EXP 数量，不是全量 EXP 数，所以即使上万个模板，每个目标匹配的指纹→EXP 查找量变化不大

## 验证方式

1. **导入完整性**：`EXP.objects.filter(plugin_language=2).count()` ≈ 12922（排除解析失败的）
2. **绑定覆盖率**：统计有至少一条指纹绑定的模板数 / 总导入模板数
3. **绑定质量**：抽查 50 条 B1/B2/B3 绑定，人工判断是否正确
4. **系统自检**：`python manage.py check` 0 issues
5. **运行时验证**：选 3-5 个已绑定指纹的模板，在调试页测试能否正常识别→执行

## 风险

| 风险 | 等级 | 说明 | 应对 |
|------|------|------|------|
| YAML 解析大面积失败 | 低 | 部分 nuclei 模板可能用了高级语法 | 先采样 500 个测试解析成功率 |
| metadata.product 不准确 | 中 | 部分模板的 metadata.product 值太泛（如 "collaboration"） | B1 只在精确/包含匹配时才确认，模糊匹配降为中置信度 |
| 绑定噪音 | 中 | B3 策略可能产生误匹配 | B3 标记为中置信度，不入自动执行链，需人工确认后才生效 |
| 万级文件写入 EXP_plugin/ | 低 | 文件系统压力 | 就是 1.3 万个小文件，任何文件系统都能承受 |
| 数据库写入性能 | 低 | 1.3 万条 INSERT + 关联关系 | 分批 commit（每 100 条），总耗时预估 < 5 分钟 |
| 模板命名冲突 | 低 | 不同目录下可能有同名模板 | 用 `info.name` + 路径拼接去重 |

## 不做

- 不修改现有指纹匹配引擎（`Identifyner`）的核心逻辑
- 不为绑定来源新增数据库字段（先用日志记录，后续按需再加）

## 依赖

- `/tmp/nuclei-templates` 仓库（已 clone）
- `fingerPrint` 表（已有 5897 条）
- `exp_relate_fingerprint` 模型
- **前置重构**：`plans/2026-05-25-yaml-runtime-remove-intermediate-py.md`（去掉中间 `.py` 编译后，导入时不用写 `__yaml_runtime__/*.py` 缓存，简化导入流程）

## 后续

1. 导入完成后，建议对未匹配模板做一次人工审查，判断是否需要补指纹
2. 考虑在指纹调试页增加"从 nuclei 模板反向查指纹"功能
3. 增量同步脚本可以定期跑（nuclei 官方每月更新几十到上百个模板）

## 实现结果

Management command 已实现：`app_cybersparker/management/commands/import_nuclei_templates.py`。参数：`--source`、`--limit`、`--dry-run`、`--skip-matching`、`--sync-mode`。

### 1000 模板验证数据

| 指标 | 数据 |
|------|------|
| 解析成功率 | 100%（0 失败） |
| 匹配覆盖率 | 95.2% |
| 平均绑定数 | 4.0 条/模板 |
| 耗时 | ~10 秒 / 1000 模板 |
| 预估 1.3 万全量耗时 | ~130 秒（~2 分钟） |

### B3 匹配质量治理（实施中多轮收紧）

- 跳过列表扩展：100+ 通用词（`enabled/disabled/access/public/cloud/devops` 等）
- 模板名分段也过 skip 检查（之前 "Enabled" 等词汇通过 name 提取绕过过滤）
- 移除描述文本关键词提取（长句子噪声极大）
- 反向包含匹配要求指纹名 ≥5 字符（防 "ess" in "access"）
- 每模板同指纹只绑一次 + 每关键词限 3 条包含匹配
- YAML 文件名和标题均加 SHA256 hash 防冲突
