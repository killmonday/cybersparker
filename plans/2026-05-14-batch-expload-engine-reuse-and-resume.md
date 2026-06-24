# 批量任务：空间测绘引擎数据复用控制 + 续跑功能

- 状态：已完成
- 关联 Backlog：BL-BATCH-005, BL-BATCH-006
- 关联模块：docs/modules/02-任务执行模块.md

## 做什么

两个独立功能，均针对批量 EXPLOAD 任务：

### Feature 1: 编辑页 "是否重新获取数据" 下拉菜单（BL-BATCH-005）

当用户编辑 input_type=4（空间测绘引擎）的批量任务时，在编辑表单中显示一个下拉菜单，让用户控制是否重新从测绘引擎获取数据。

**有效性规则**（服务端判定）：
- 条件 A：用户提交的 engine_query 与数据库中上次的 engine_query 相同
- 条件 B：上次成功获取到了数据（target 字段非空、文件存在且为 engine_asset 文件）
- 当 A ∧ B 成立 → 选项有效，尊重用户选择
- 当 A ∧ B 不成立 → 选项无效，后端强制重新获取

### Feature 2: 列表页 "续跑" 按钮（BL-BATCH-006）

在 `/batch_exploadTask/list` 页面上为未完成的任务添加续跑按钮，点击后提示用户这是接着跑未完成的任务，后端从上次未完成的目标开始接着跑。

## 怎么做

### Feature 1 实现方案

**模型层**：
- `batch_EXPTask` 新增 `reuse_engine_data` BooleanField（default=False）
- 生成 migration 0007

**后端视图**：
- `detail()` 在 method=None 时额外返回 `reuse_engine_data` 和条件判断结果 `can_reuse_engine_data`
- `edit()` 中 `resolve_target_source()` 的 input_type=4 分支：根据条件决定是否复用已有 target
- 复用逻辑：如果 `reuse_engine_data=True` 且条件成立，保留现有 target 字段不变（不重新获取）

**前端**：
- 模板：在 engine-source-field 区域新增 `reuse_engine_data` 下拉菜单（option: "是，重新获取" / "否，复用已有数据"），默认"是"
- JS：编辑时根据 `can_reuse_engine_data` 控制下拉菜单是否可用（不可用时置灰+强制选"是"）
- JS：提交时将 `reuse_engine_data` 值附加到 FormData

### Feature 2 实现方案

**后端视图**：
- `operate()` 新增 action="resume" 分支：不重置 process="0%"，保留当前进度传入 startTask
- `detail()` method="OperateTask" 返回 process 值供前端判断是否可续跑

**前端**：
- 模板：列表页为 status=stop 且 process > 0% 且 process < 100% 的任务显示"续跑"按钮
- JS：新增 `ResumeTask()` 函数，弹窗提示"确认要从上次中断位置继续执行任务吗？"

## 风险

- 低风险：两个功能均为局部修改，不影响现有任务执行流程
- `reuse_engine_data` 字段默认 False，向后兼容

## 验证

- Django 系统检查 0 issues
- 数据库迁移正常应用
- pytest 通过
