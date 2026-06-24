# CLAUDE.md — 13 条核心规则 + 项目特定约束

以下规则适用于本项目所有任务（琐碎任务可自主裁量是否简化流程，但不降低质量底线）。
倾向：非琐碎工作中，严谨胜过速度。

## 规则 1 — 编码前思考
明确陈述假设。不确定就提问，禁止沉默猜测。
存在歧义时列出多种解读。有更简单方案就提出。
遇到不明确处立即停止并指出困惑点。

## 规则 2 — 简约至上
用最少代码解决问题，禁止投机性功能。
不为单次使用的代码建抽象，不添加未要求的可配置性。
自问：“资深工程师会觉得太复杂吗？” 若会，就简化。

## 规则 3 — 外科手术式改动
只改必须改的地方。只清理自己留下的烂摊子。
不“优化”相邻代码、注释、格式。不重构未损坏的部分。
严格匹配现有代码风格。

## 规则 4 — 目标驱动执行
把任务转化为可验证的成功标准，循环直到验证通过。
多步骤任务先列简要计划和每步验证方式。不要在复杂系统里反复试错，要在最小环境中快速验证。
最后一步必须是运行完整自检（编译/lint/测试通过），未通过不算完成。

## 规则 5 — 仅用AI模型做判断性决策
只使用 AI模型 进行分类、起草、总结、信息提取。
严禁用本模型做路由、重试、状态码处理等确定性逻辑。
能用代码实现的判断就不要交给模型。

## 规则 6 — 硬性 Token 预算
当预估剩余 Token 低于总预算的 10% 时，Agent 应立即停止深度推理，并输出一份执行摘要，包括已完成事项、关键结论及未完成任务。然后必须明确告知用户“已达 Token 上限”，并建议重新开始会话。

## 规则 7 — 暴露冲突，不平滑处理
代码库中存在两种冲突模式时，选择其中一个（更新或更经测试的），
解释理由并把另一个标记为待清理，绝不混合生成“平均”代码。

## 规则 8 — 先读后写
在文件中添加代码前，必须理解该文件的导出、直接调用者、共享工具。
如果不理解现有代码为何那样构建，先询问再动手。
禁止以“看起来是独立的”为理由跳过阅读。

## 规则 9 — 测试验证意图，而非仅行为
每个测试必须说明行为为什么重要，而不只是断言结果。
如果业务逻辑改变时测试不会失败，该测试就是无效的。

## 规则 10 — 长任务建立检查点
多步骤任务每完成一个重要步骤后，总结已完成、已验证、剩余工作。
不允许从一个无法向人清晰描述的状态继续推进。
迷失方向时立即停止并重新陈述当前状态，并向用户求助。

## 规则 11 — 遵循代码库惯例
即使不认同，也必须使用代码库已有的命名、模式、框架范式。
若真心认为当前惯例有害，单独指出并建议改造，但禁止在代码中静默分叉。

## 规则 12 — 大声报错
任何模糊的成功声明（“迁移完成”“测试通过”）必须有确切证据。
静默跳过记录、跳过测试、缺少边缘验证时，必须明确说明不确定之处。
默认暴露不确定性，绝不隐藏。

## 规则 13 — 解决难题的方法论
当分析不出问题和解决办法时，主动获取更多信息从而定位问题和解决问题：
- 从互联网查找资料
- 给关键位置的代码添加日志打印，通过读日志内容来做分析
- 若情况允许，汇报当前情况给用户，向用户寻求帮助

# 项目特定约束
## 沟通方式
- 使用中文沟通。
- 回答的风格和编写的技术文档风格一致：直白简洁，通俗易懂，面向普通业务程序员，摒弃一切底层架构、分布式、运维小众专业术语，不用行业暗语、不用项目内部自定义词汇，解释功能只用最简单直白的代码逻辑描述，总结工作进度清晰直白。不堆砌技术名词。
- **解释bug/描述功能/解答用户疑惑时，用具体场景举例，给出数据从前到后的完整流转,默认视作用户并不清楚上下文和代码具体情况**。如"新任务 id=200 扫了一个资产 → 资产表里已有 id=100 写的记录 → 更新时忘了改 task_id → 页面用 200 去查自然为空"。禁止用行业术语（upsert、幂等、脏读等）替代场景描述。


## 任务与文档流程
- 非琐碎任务必须先创建/更新 `plans/<日期>-<任务名>.md`（含做什么、为什么、怎么做、风险），并动态维护状态。
- 完成后必须更新 `CHANGELOG.md`，并同步受影响的 `docs/` 文档；无需更新时说明原因。
- 涉及功能、接口、数据模型变动时，同步创建或更新相关 `docs/` 设计文档（需求、概要、接口、DB 等），但文档应极简，只记录决策和维护信息。
- 记录已决策但暂不执行的后续开发事项到 `docs/后续开发事项.md`。
- 任务提交前必须满足完成定义（DoD）：代码/doc 已更新、自检通过、计划已更新、变更日志已记录、相关文档已同步。


## 文件内容检索方式
- 对于代码的的探索、查找引用、理解结构时，优先用 Serena LSP
- 若Serena LSP不可靠，回退使用rg。若rg用不了，使用grep
- 在做"有没有 X"这类存亡判断时，搜索范围不能从之前交互中已知的文件推导。必须从目录级或项目级重新搜索，因为不同功能点分布在不同的文件中，上一次在哪找到的不代表下一次也在那。零匹配的正确解读是"这个范围里没有"，不是"不存在"，缩小范围等于自证偏见。

## 项目控制面
- 阶段规划、Backlog 拆分/执行、验收等使用 `project-control-plane` skill，根指令仅保留此入口。
- Backlog 开发状态只用：未开始、进行中、已完成。验收状态独立记录：未验收、待验收、已验收、验收未通过。

## 安全约束（硬性）
所有实现必须确保：
- 无 SQL 注入、命令注入、路径遍历
- 无敏感信息硬编码
- 输入完整验证，错误信息不泄露敏感数据
- 不安全的反序列化必须处理

## 测试规范
- 新增功能必须写测试，无法测试时说明豁免原因。
- 覆盖率目标 ≥70%，使用项目对应测试框架。
- 测试命名清晰体现场景。
- 禁止在测试中使用固定 sleep（用异步等待/同步机制），禁止依赖外部真实服务（用 mock），禁止修改全局状态，禁止跳过失败测试。


## 目录级知识积累
- 实现完成后，若在某目录发现可复用模式，在该目录创建或追加 `CLAUDE.md`。
- 只写可复用共识（API 约定、依赖关系、模式、架构约束、常见陷阱），禁止写入临时调试信息、敏感信息、一次性 workaround。

## 跨层字段对齐
引用跨系统边界的字段前，必须先到对面确认字段名和类型是否一致。写完立即逐字段比对，不允许假设。

常见跨边界场景：
- 前端 `interface` / 渲染里用了 `p.name` → 先确认后端 API 是否真的返回 `name`（可能实际叫 `proxy_type_label` / `proxy_address` / `proxy_port`）
- Django Model `clean()` 里引用了 `self.source_tasks` → 先确认 Form `Meta.fields` 是否包含 `source_tasks`（表单不认识的字段永远是默认值）
- 反向同理：后端新增/改名了 API 字段 → 确认前端引用处是否同步


<!-- serena:start -->
# Serena — Symbolic Code Intelligence

项目通过 `.serena/project.yml` 配置了 Python LSP（Pyright）。Serena 基于 LSP 提供语义级代码理解，比 grep 更准确，但存在边界。
当前仅为python配置了serena。

## Always Do

- **探索陌生文件，第一步用 `get_symbols_overview`**：返回文件内所有符号（Class/Function/Method/Variable）的结构化列表，不消耗 token 读全文件。
- **读特定函数体，用 `find_symbol` + `include_body=True`**：精确获取某个函数/类/方法的完整代码，无需先 rg 行号再 Read。
- **查"谁调用了这个模型/函数"，用 `find_referencing_symbols`**：这是 Serena 最强能力。对 Django Model 类做引用查找，一次性返回所有 `.objects.filter()` / `.objects.get()` / `.save()` 等 ORM 调用点，带行号和上下文片段。查询时应指定 `relative_path` 缩小范围。
- **做跨文件影响分析时，先 `find_referencing_symbols` 再看 `find_implementations`**：前者找调用者，后者找子类/接口实现。
- **搜索结果过长时用 `max_answer_chars` 控制**：默认可能超限，设置 `max_answer_chars=5000` 等合理值。

## Use with Judgment

- **小范围精确编辑 → 用内置 `Edit`，不用 Serena 的 `replace_content`**。`Edit` 的精确字符串替换比 regex 更安全。Serena 编辑工具仅在全函数替换（`replace_symbol_body`）或大量重复替换时有优势。
- **Django 动态属性不可追踪**：`Model.objects`、`connection.cursor()`、`getattr(obj, field)` 等运行时属性 Serena 无法识别为独立符号。评估此类调用点数量时仍可用 grep 辅助。
- **`relative_path` 是必填参数**：所有 Serena 查询都应指定目标目录或文件，否则可能扫到大量无关结果（尤其是 `static/` 下的第三方 JS）。
- **搜索结果受限时仍可用 rg** rg 用于发现性搜索（找到一个字符串的所有出现位置），然后对找到的符号用 Serena 做语义分析。

## Never Do

- NEVER 在编辑代码后使用 `Read` 验证 — Serena 的编辑工具（`replace_symbol_body`、`replace_content`）成功即可靠，编辑失败会报错。
- NEVER 用 `Read` 读一个你还没看过符号结构的文件 — 先用 `get_symbols_overview`。
- NEVER 在没有 `relative_path` 的情况下做 `find_referencing_symbols` — 会扫全项目，token 爆炸。

## Recommended Decision Flow

```
看到新文件 → get_symbols_overview → 定位目标符号
                                     ↓
                          需要读代码？→ find_symbol + include_body=True
                          需要找调用者？→ find_referencing_symbols + relative_path
                          需要找实现？→ find_implementations
                          需要改几行？→ 内置 Edit（精确字符串替换）
                          需要重写整个函数？→ replace_symbol_body
```
<!-- serena:end -->

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **docker-claude-example** (8075 symbols, 13313 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/docker-claude-example/context` | Codebase overview, check index freshness |
| `gitnexus://repo/docker-claude-example/clusters` | All functional areas |
| `gitnexus://repo/docker-claude-example/processes` | All execution flows |
| `gitnexus://repo/docker-claude-example/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

<!-- rtk-instructions v2 -->
# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:
```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)
```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (60-99% savings)
```bash
rtk cargo test          # Cargo test failures only (90%)
rtk go test             # Go test failures only (90%)
rtk jest                # Jest failures only (99.5%)
rtk vitest              # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk pytest              # Python test failures only (90%)
rtk rake test           # Ruby test failures only (90%)
rtk rspec               # RSpec test failures only (60%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)
```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)
```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### JavaScript/TypeScript Tooling (70-90% savings)
```bash
rtk pnpm list           # Compact dependency tree (70%)
rtk pnpm outdated       # Compact outdated packages (80%)
rtk pnpm install        # Compact install output (90%)
rtk npm run <script>    # Compact npm script output
rtk npx <cmd>           # Compact npx command output
rtk prisma              # Prisma without ASCII art (88%)
```

### Files & Search (60-75% savings)
```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%). Format flags (-c, -l, -L, -o, -Z) run raw.
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90% savings)
```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Infrastructure (85% savings)
```bash
rtk docker ps           # Compact container list
rtk docker images       # Compact image list
rtk docker logs <c>     # Deduplicated logs
rtk kubectl get         # Compact resource list
rtk kubectl logs        # Deduplicated pod logs
```

### Network (65-70% savings)
```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands
```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Claude Code sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to CLAUDE.md
rtk init --global       # Add RTK to ~/.claude/CLAUDE.md
```

## Token Savings Overview

| Category | Commands | Typical Savings |
|----------|----------|-----------------|
| Tests | vitest, playwright, cargo test | 90-99% |
| Build | next, tsc, lint, prettier | 70-87% |
| Git | status, log, diff, add, commit | 59-80% |
| GitHub | gh pr, gh run, gh issue | 26-87% |
| Package Managers | pnpm, npm, npx | 70-90% |
| Files | ls, read, grep, find | 60-75% |
| Infrastructure | docker, kubectl | 85% |
| Network | curl, wget | 65-70% |

Overall average: **60-90% token reduction** on common development operations.
<!-- /rtk-instructions -->
