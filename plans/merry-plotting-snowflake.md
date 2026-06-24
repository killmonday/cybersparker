# 批量 EXP 任务新增“网络空间测绘引擎输入源”实施计划（2026-04-21）

## Context
当前 `/batch_expload_Task/list` 仅支持 3 类输入源（上传文件、历史漏洞资产、历史上传文件），无法直接从测绘引擎拉取资产。目标是在**不改动现有扫描执行主链路**（`batch_task_executor.py` 仍按 txt 输入运行）的前提下，新增第 4 类输入源“从网络空间测绘引擎”，支持：
- 引擎：`fofa`、`zoomeye`、`quake`、`hunter(鹰图)`、`shodan`
- 任务侧参数：搜索语句、最大资产数、代理三态（跟随引擎配置 / 强制直连 / 强制代理地址）
- 新增测绘引擎配置页：API 地址、邮箱、API Key、是否使用代理、代理地址
- 运行语义：
  - **stop 后继续（进度<100%）**：复用旧资产文件，不重拉
  - **finish 后重跑**：删除旧测绘资产文件并重新拉取

## 成功标准
1. 批量任务新增 `input_type=4` 并可正常创建/编辑/回填。  
2. 启动任务时能调用所选测绘引擎 API，生成 txt 到测绘专用目录，并沿用现有扫描流程。  
3. stop 继续与 finish 重跑语义符合约定。  
4. 新增测绘引擎配置页面可管理 5 个引擎配置并支持代理。  
5. 不破坏现有 input_type=1/2/3 与现有结果页面逻辑。

## 复用现有实现（必须沿用）
- 批量任务主流程：`app_cybersparker/views/expload/task_manage/batch_exp_task.py`（`add/edit/detail/operate/startTask/resolve_target_source`）
- 扫描执行器：`app_cybersparker/views/expload/task_manage/batch_task_executor.py`（继续读取 `target_file`）
- 代理模型与 CRUD 模式：
  - `app_cybersparker/models.py` `ProxySetting`
  - `app_cybersparker/views/expload/proxy_setting.py`
- 现有输入文件落盘模式：`build_target_file_from_targets`（写入 `EXP_input/`）

## 实施步骤（含验证节点）

### 1) 模型与迁移（最小侵入）
**修改文件**
- `app_cybersparker/models.py`

**变更**
1. `batch_EXPTask.inputType_choices` 新增：`(4, "cyberspace engine")`。  
2. 为 `batch_EXPTask` 新增可空字段（兼容旧数据）：
   - `engine_type`（choices: fofa/zoomeye/quake/hunter/shodan）
   - `engine_query`（TextField）
   - `engine_max_assets`（IntegerField，默认值如 100）
   - `engine_proxy_mode`（SmallIntegerField，0跟随/1直连/2强制代理）
   - `engine_proxy`（FK `ProxySetting`，可空）
3. 新增模型 `CyberspaceEngineSetting`：
   - `engine_type`（唯一）
   - `api_base_url`
   - `account_email`（可空）
   - `api_key`
   - `use_proxy`（bool）
   - `proxy`（FK `ProxySetting`，可空）
   - `remark`、`update_time`（可空）

**验证项**
- 运行 `python manage.py makemigrations && python manage.py migrate` 成功。
- 旧 `batch_EXPTask` 数据可正常查询和展示。

---

### 2) 新增测绘引擎配置页面
**修改文件**
- `cybersparker/urls.py`
- `app_cybersparker/views/expload/cyberspace_engine_setting.py`（新）
- `app_cybersparker/templates/project/expload/cyberspace_engine_setting.html`（新）
- `app_cybersparker/templates/project/index.html`

**变更**
1. 仿照 `proxy_setting.py` 增加 list/add/edit/delete/detail。  
2. 菜单新增入口（与 `http_proxy_setting` 同层级风格一致）。  
3. 表单字段包含 API 地址、邮箱、API Key、是否代理、代理地址。

**验证项**
- 页面可新增/编辑/删除 5 个引擎配置。
- 代理下拉能读取 `ProxySetting`，空值表示不使用代理。

---

### 3) 批量任务表单扩展（前后端）
**修改文件**
- `app_cybersparker/views/expload/task_manage/batch_exp_task.py`
- `app_cybersparker/templates/project/expload/task_manage/bath_exp_task_list.html`
- `app_cybersparker/static/project2/expload/js/batch_Expload_Task.js`

**变更**
1. 在 `input_type` UI 下新增 type=4 的专属区域：
   - 引擎选择、搜索语句、最大资产数、代理模式、代理地址。
2. `toggleInputTypeUI()` 新增 type=4 显隐分支。  
3. `doAdd/doEdit` 提交新增字段，`detail` 返回并回填新增字段。  
4. `resolve_target_source()` 新增 `input_type==4` 校验分支：
   - 校验引擎、搜索语句、最大资产数、代理模式与代理地址组合是否合法
   - **创建/编辑阶段不拉取资产**（仅保存配置）

**验证项**
- 任务新增/编辑时 type=4 字段可正确保存、回填。
- type=1/2/3 表单行为无回归。

---

### 4) 新增测绘引擎查询服务层
**修改文件**
- `app_cybersparker/services/cyberspace_engine_service.py`（新）
- `app_cybersparker/services/cyberspace_engine_adapters.py`（新）

**变更**
1. 统一入口 `fetch_and_dump_targets(task_obj)`：
   - 读取任务参数 + 引擎配置
   - 解析最终代理
   - 分页调用对应引擎 adapter
   - 标准化 target 行并去重
   - 落盘到测绘专用目录 txt
   - 返回相对路径用于写回 `batch_EXPTask.target`
2. Adapter 设计（5 个引擎一引擎一适配器）：
   - `search(query, page, page_size, config, proxies)`
   - `extract_targets(resp)`
3. 控制策略：
   - `engine_max_assets` 做上限夹紧（防超大拉取）
   - 请求超时与有限重试
   - 空结果返回明确业务错误

**验证项**
- 可针对每个引擎在相同入口完成查询并产出 txt。
- 同一资产多页返回时最终文件无重复行。

---

### 5) 运行语义改造（operate 分支）
**修改文件**
- `app_cybersparker/views/expload/task_manage/batch_exp_task.py`

**变更**
1. 新增 `prepare_engine_target_before_start(task_obj, is_restart)`：
   - 仅在 `input_type==4` 触发
   - stop 继续（`status=="0"` 且 `process<100%`）：直接复用旧 `target`
   - finish 重跑（`status=="1"` 或 `process==100%`）：删除旧测绘文件并重拉
   - 首次运行：若无有效 target，则拉取并生成
2. 单任务和批量启动都先走该准备逻辑，再调用现有 `startTask`。
3. 保持 `batch_task_executor.py` 不改（继续读取 `target_file`）。

**验证项**
- stop 后继续不会新建测绘文件，进度从断点推进。
- finish 后重跑会替换为新测绘文件并从 0% 跑。

---

### 6) 文件目录与安全清理
**修改文件**
- `app_cybersparker/views/expload/task_manage/batch_exp_task.py`
- （可选）`app_cybersparker/services/cyberspace_engine_service.py`

**变更**
1. 测绘导出目录固定：`EXP_input/engine_assets/`。  
2. 新增安全删除函数，仅允许删除该目录内文件（`realpath` 前缀校验）。  
3. 删除任务时：若是测绘来源且 target 在测绘目录，才执行删除。  
4. 不修改历史文件选择逻辑（`history_files` 继续面向 `EXP_input` 已有文件）。

**验证项**
- 删除测绘任务不会误删 `EXP_input` 下其他来源文件。
- 历史上传文件功能保持可用。

## 代理优先级（已确认）
任务级三态覆盖策略：
1. `force_proxy`：必须使用任务指定 `engine_proxy`
2. `no_proxy`：强制直连
3. `follow_engine_config`：按 `CyberspaceEngineSetting.use_proxy/proxy`

## 关键兼容性说明
- `input_type=1/2/3` 流程不变。
- 执行器不改，降低风险。
- 新字段全部可空，避免迁移后旧任务报错。

## 端到端验证清单
1. 配置页：5 个引擎配置 CRUD + 代理设置。  
2. 任务页：type=4 新建/编辑/回填。  
3. 首次启动：生成 `EXP_input/engine_assets/*.txt` 并开始扫描。  
4. stop→start：不重拉、不删文件、断点继续。  
5. finish→restart：删旧测绘文件并重拉。  
6. 删除任务：仅清理任务对应测绘文件。  
7. 回归：type=1/2/3、history_files、结果页查询无异常。

## 建议测试
- `python manage.py test`（全量）
- 新增测试模块建议：
  - `app_cybersparker/tests/test_batch_engine_input.py`
  - `app_cybersparker/tests/test_cyberspace_engine_service.py`

重点覆盖：
- `resolve_target_source(input_type=4)` 校验
- `operate` 继续/重跑分支判定
- 代理优先级解析
- 安全删除逻辑
