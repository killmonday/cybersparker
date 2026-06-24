# 2026-04-25 请求运行时 monkey patch 改造复盘

## 1. 做什么
本次完成了“请求运行时本地化 + 启动期全局 monkey patch + 配置热更新”改造，重点是**不改业务层 `requests` 调用代码**，而是在 Django 启动时统一注入请求行为。

已落地的核心内容：
- 新增本地请求运行时内核：`app_cybersparker/lib/request_runtime/**`
- 启动时自动 patch：`app_cybersparker/apps.py:8`
- 全局 conf 单例与 DB 热更新服务：`app_cybersparker/services/request_runtime_config_service.py:1`
- 代理配置页面增改删后即时刷新 conf：`app_cybersparker/views/expload/proxy_setting.py:54`、`:75`、`:92`
- Django AppConfig 接入：`cybersparker/settings.py:53`
- 新增最小回归测试：`app_cybersparker/tests.py:1`

## 2. 为什么
改造目标：
1. 去除对第三方 `pocsuite3.lib.request` 运行时依赖，沉淀为项目自有能力；
2. 保留并复用 `conf` 全局配置思想，实现代理/超时/请求参数统一管控；
3. 保持现有扫描链路兼容，避免大面积替换业务 `requests` 调用带来的改造风险。

关键约束（来自需求）：
- 必须使用 monkey patch（而非逐处替换调用入口）；
- 首阶段保持兼容策略：默认 `verify=False`；
- `httpx` 调用链路暂不纳入首批。

## 3. 怎么做
### 3.1 搭建本地 request_runtime 骨架
- 实现 `AttribDict` 与 `conf` 单例：
  - `app_cybersparker/lib/request_runtime/datatype.py:1`
  - `app_cybersparker/lib/request_runtime/conf.py:1`
- 预置默认参数：`http_headers/proxies/timeout/verify/cookie/agent`

### 3.2 迁移并组装 patch 能力
- 迁移并本地化关键 patch：
  - `Session.request` 改造（参数合并/代理超时兜底）
  - redirect location 编码修复
  - urllib3 parse_url 修复
  - request URI 编码策略
  - chunked `_update_chunk_length` 修复
  - `requests.httpraw` 注入
- 统一入口与幂等保护：`app_cybersparker/lib/request_runtime/patch/__init__.py:31`

### 3.3 启动期接入与热更新
- 在 `AppConfig.ready()` 中执行 `bootstrap_request_runtime()`：`app_cybersparker/apps.py:8`
- `bootstrap_request_runtime()` 中完成 patch + 从 DB 刷新 conf：`app_cybersparker/services/request_runtime_config_service.py:20`
- 在 ProxySetting 增删改成功后刷新 conf：`app_cybersparker/views/expload/proxy_setting.py:54`、`:75`、`:92`

### 3.4 验证
- 框架检查：`python manage.py check`
- 用例回归：
  - `python manage.py test app_cybersparker.tests`
  - `python manage.py test`
- 关键行为用例覆盖：
  - `requests.Session.request` 已被 patch
  - 代理三态语义：
    - `proxies is None` -> 回落 `conf.proxies`
    - `proxies = {}` -> 显式禁用代理
    - 显式 dict -> 优先于 conf
  - `refresh_conf_from_db()` 读取最新代理并生效

## 4. 结果
- 功能结果：达成“启动即 patch + 全局 conf + 热更新”目标，且未改业务层 `requests` 调用入口。
- 测试结果：共 5 个测试，全部通过。
- 运行结果：`manage.py check` 通过，系统检查无报错。
- 任务结果：本轮关联任务已收尾（回归、内核、热更新、启动接入均完成）。

## 5. 可能存在的问题
1. **安全基线问题**：当前默认 `verify=False`，兼容性优先但存在中间人风险，不适合直接用于高安全场景。
2. **monkey patch 副作用边界**：第三方库若依赖 requests/urllib3 的特定细节，可能在极端场景触发兼容问题。
3. **静态检查噪声**：存在部分 Pyright 诊断（Django ORM 动态属性/导入解析），不影响运行但会干扰静态质量门禁。
4. **测试覆盖面有限**：当前是最小回归，尚未覆盖真实网络重定向链、复杂 chunked 响应、异常代理场景。
5. **httpx 策略未统一**：目前 requests 与 httpx 并存，配置策略仍可能出现不一致。

## 6. 下一步可优化
1. 增加 `REQUEST_RUNTIME_ENABLED` 与 `REQUEST_RUNTIME_VERIFY` 开关（支持快速回退与逐步收紧 TLS 策略）。
2. 增加 requests/urllib3 版本兼容自检，启动时给出明确告警。
3. 扩展测试：
   - redirect 编码修复
   - `httpraw` GET/POST/raw body
   - chunked 边界与异常分支
4. 第二阶段统一 `httpx` 配置映射（按 conf 规则对齐代理/超时/verify 语义）。
5. 增加运行日志与可观测性（patch 启用状态、conf 刷新来源与时间、代理命中日志）。
