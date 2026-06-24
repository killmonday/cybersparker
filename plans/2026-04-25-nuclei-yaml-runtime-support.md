# nuclei YAML PoC 支持实施计划（2026-04-25）

## 做什么
1. 在现有 EXP 体系中支持 `nuclei_yaml` 插件语言，并允许上传 `.yaml/.yml`。  
2. 新增统一运行时解析层，支持 `.py` 直接加载与 `.yaml/.yml` 转换后加载。  
3. 将调试、单任务、批量任务、结果复验、自动扫描 EXP 执行链路统一切换到 resolver 调用。  
4. 保持现有线程/gevent/子进程执行模型、结果入库模型和页面协议不变。

## 为什么
- 现有执行入口分散且大量硬编码 `.py` 导致 YAML 无法接入。  
- 统一 resolver 可以降低改造面和回归风险，避免“某链路可用、某链路不可用”的割裂。  
- 复用已有执行器和结果模型可实现最小侵入改造。

## 怎么做
1. 模型与迁移：
   - `app_cybersparker/models.py` 的 `EXP.plugin_language` 扩展为 `python3/nuclei_yaml`。
   - 新增迁移 `app_cybersparker/migrations/0005_exp_plugin_language_nuclei_yaml.py`。
2. 上传校验：
   - `app_cybersparker/views/expload/plugin_manage.py` 在 add/edit 入口按 `plugin_language` 强校验后缀。
3. 统一运行时：
   - 使用 `app_cybersparker/views/expload/task_manage/poc_runtime_resolver.py` 提供统一加载与方法分发。
4. 业务链路接入：
   - `app_cybersparker/views/expload/result__manage/expResult.py` 的 `targetRunVerify`。
   - `app_cybersparker/views/expload/task_manage/batch_exp_task.py` 的 `TaskResult_verify` 与语言映射。
   - `app_cybersparker/views/expload/task_manage/auto_exp_task.py` 的 `exp_consumer`。
   - 其余链路（调试、单任务、批量执行器）按同样模式走 resolver。
5. 最小验证：
   - 运行 `python manage.py check`。
   - 全局检索残留 `.py` 硬编码加载。

## 结果
- 已完成：
  - `models.py` 与迁移已支持 `nuclei_yaml`。  
  - `plugin_manage.py` 已完成上传后缀校验（python3->`.py`，nuclei_yaml->`.yaml/.yml`）。  
  - `batch_exp_task.py` 与 `result__manage/expResult.py` 已切换到 `load_runtime_module_from_poc + call_runtime_method`。  
  - `auto_exp_task.py` 已从 `split(".py") + importlib` 切换到 resolver（verify 调用）。  
  - `exp_debug.py` 已修复“新增插件时强制写死 `.py`”的问题：现在按 `plugin_language` 选择保存后缀（python3->`.py`，nuclei_yaml->`.yaml`），避免 YAML 被当作 Python 执行。
  - `poc_runtime_resolver.py` 已切换 YAML 运行时代码生成逻辑：不再 `from pocsuite3... import Nuclei`，改为调用本地 `nuclei_runtime_engine.run_nuclei_template(...)`，并移除 pocsuite3 路径注入。
  - 新增本地最小 nuclei 运行器 `nuclei_runtime_engine.py`，支持 HTTP + Network 协议主流程（matchers/extractors/变量替换的最小子集）。
  - `python manage.py check` 通过（0 issues）。
  - 本地 smoke 验证通过：HTTP 模板与 Network 模板均能通过 resolver -> `_verify` 路径执行并返回结果。
- 当前全局检索结果：`app_cybersparker/views/expload/task_manage` 下未检索到 `pocsuite3` 或 `Nuclei(` 运行时调用残留。

## 可能存在的问题
1. YAML 复杂语法（尤其高级 DSL 场景）可能存在兼容边界。  
2. 非 verify 模式目前是兼容入口，语义仍以 verify 为主。  
3. Pyright 对 Django ORM 的类型噪声仍存在（不影响运行时）。

## 下一步可能优化的点
1. 增加 YAML 模板静态预校验并给出更友好的错误定位。  
2. 增加运行时缓存淘汰策略（按访问时间清理）。  
3. 增补端到端自动化测试用例（调试/单任务/批量/自动扫描混合插件）。
