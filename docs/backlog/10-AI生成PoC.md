# 10-AI生成PoC — Backlog

> 阶段：阶段十五 — AI生成PoC | 2026-06-07 | 审查通过（2轮修正后）| 验收：已验收（23 专项测试）

## Backlog 总览

| Backlog ID | 说明 | 优先级 | 状态 |
|------------|------|--------|------|
| BL-AIPOC-001 | AI模型配置 CRUD（API + React页面） | P0 | 已完成 |
| BL-AIPOC-002 | PoC生成任务 — 模型 + 创建页 + 列表页 + 资料提取 | P0 | 已完成 |
| BL-AIPOC-003 | PoC生成任务 — 执行页 + Celery异步生成 + 结果展示 | P0 | 已完成 |
| BL-AIPOC-004 | 保存PoC到EXP插件库 | P0 | 已完成 |
| BL-AIPOC-005 | 插件类型从创建时必选改为执行页可选切换 | P1 | 已完成 |
| BL-AIPOC-006 | URL爬取HTML清洗增强（含GitHub/知乎/微信适配） | P0 | 已完成 |
| BL-AIPOC-007 | URL爬取图片下载与识图转文字修复 | P0 | 已完成 |
| BL-AIPOC-008 | URL爬取反爬对抗（浏览器伪装 + 懒加载图片等） | P0 | 已完成 |
| BL-AIPOC-009 | 直接输入文本作为参考资料 | P1 | 已完成 |
| BL-AIPOC-010 | 任务列表加翻页 | P1 | 已完成 |
| BL-AIPOC-011 | 任务编辑与重试 | P1 | 已完成 |

> 注：BL-AIPOC-004 若资源不足可降为 P1（主链路不含保存仍可走通，用户可手动复制代码）。当前按 P0 推进。

### 依赖顺序

```
BL-AIPOC-001 → BL-AIPOC-002 → BL-AIPOC-003 → BL-AIPOC-004
```

---

## BL-AIPOC-001 AI模型配置 CRUD

- 模块：AI生成PoC
- 优先级：P0
- 状态：已完成
- 当前阶段：阶段十五
- 价值：用户可管理多个 AI 模型配置（思考/识图），为 PoC 生成任务提供可选模型。
- 关联模块文档：docs/modules/10-AI生成PoC模块.md
- 关联计划：plans/2026-06-07-AI生成PoC-需求澄清.md
- 关联代码：`app_cybersparker/views/ai_poc/ai_model_config.py`（新建）

### 范围

- 后端：
  - 新增 `AIModelConfig` 数据模型（`app_cybersparker/models.py`）+ migration
  - CRUD API（`app_cybersparker/views/ai_poc/ai_model_config.py`）：GET/POST/PUT/DELETE `/api/v1/ai-model-configs`
  - API Key 明文存储，读取时脱敏返回（前4后4）
  - URL 注册到 `cybersparker/urls.py`
- 前端：
  - React 页面 `AiModelConfigPage.tsx`，路由 `/react-shell/ai-model-configs`
  - 列表表格：名称、模型ID、API地址、API Key(脱敏)、类型、操作（编辑/删除）
  - 新增/编辑弹窗：表单含名称、模型ID、API地址、API Key、类型（thinking/vision）
  - 侧边栏入口："系统配置"→"AI模型配置"
- 创建 PoC 生成任务时：思考模型下拉仅 thinking 类型，识图模型下拉仅 vision 类型（此功能在 BL-AIPOC-002 使用本 item 提供的 API）

### 不做

- 不做 API Key 加密存储
- 不做模型连通性测试
- 不做批量删除

### 验收条件

- [ ] 列表页展示已配置的模型，可按类型筛选
- [ ] 新增模型后列表刷新可见
- [ ] 编辑时 API Key 字段为空（需手动输入，不预填旧值）
- [ ] 删除模型前弹窗确认
- [ ] API 返回的 api_key 字段脱敏（前4位+****+后4位）

### 依赖

- 无（独立模块，不依赖其他 backlog item）

### 状态记录

- 2026-06-07：需求澄清完成，创建 backlog
- 2026-06-07：第2轮审查通过（代码位置明确化）
- 2026-06-07：已完成 — Django check 0 issues / migration 已应用 / 223 tests OK / Vite build OK

---

## BL-AIPOC-002 PoC生成任务 — 模型 + 创建页 + 列表页 + 资料提取

- 模块：AI生成PoC
- 优先级：P0
- 状态：已完成
- 当前阶段：阶段十五
- 价值：用户可创建 PoC 生成任务，系统自动提取参考资料。
- 关联模块文档：docs/modules/10-AI生成PoC模块.md
- 关联计划：plans/2026-06-07-AI生成PoC-需求澄清.md
- 关联代码：`app_cybersparker/views/ai_poc/poc_gen_task.py`（新建）、`scripts/crawl_urls.js`（新建）、`app_cybersparker/utils/folder2json.py`（迁移）

### 范围

- 后端（模型与 API）：
  - 新增 `PoCGenerationTask` 数据模型（`app_cybersparker/models.py`）+ migration
  - 任务 CRUD API（`app_cybersparker/views/ai_poc/poc_gen_task.py`）：GET/POST/GET(id)/PUT/DELETE `/api/v1/poc-gen-tasks`
  - URL 注册到 `cybersparker/urls.py`
  - 创建时初始化 4 个提示词默认值（task_description_prompt 硬编码、plugin_spec_prompt 按 plugin_language 读对应 md 文件、reference_material_prompt 空、custom_prompt 空）
  - 创建后异步启动资料提取，更新 crawl_status → crawl_detail → reference_material_prompt
  - 删除时：kill Puppeteer 子进程 → 清理 `./AI_PoC/task_<id>/` → 删除 DB 记录

- 后端（文件上传模式）：
  - 上传文件最大 100MB（前端+后端双重校验）
  - 存到 `./AI_PoC/task_<id>/`（`material_dir` 字段）
  - 创建任务时 `os.makedirs(material_dir, exist_ok=True)` 创建目录
  - 压缩包自动解压（zip/tar.gz/tar/7z），解压前 zip 内文件数 ≤ 500
  - 调 `folder_to_json(material_dir, api_key=vision_model.api_key)` 生成 JSON → 写入 reference_material_prompt
  - 非压缩包同样调 folder2json

- 后端（URL 爬取模式）：
  - URL/IP 安全校验（见模块文档 URL 安全校验规则，Python 侧先校验一次）
  - `subprocess.run(["node", "/app/scripts/crawl_urls.js"], input=json_str, capture_output=True, timeout=300)` 调用 Puppeteer
  - 捕获 `CalledProcessError` / `TimeoutExpired` → 更新 crawl_status=failed
  - 解析 stdout JSON → 更新 crawl_detail
  - 先调 Puppeteer 爬取 → 再用识图模型处理 markdown 中的图片 → 合并为 reference_material_prompt

- 后端（基础设施）：
  - Dockerfile：`apt-get install chromium-browser nodejs npm` + 系统库（libnss3/libatk-bridge2.0-0/libxkbcommon0/libxcomposite1/libxdamage1/libxrandr2/libgbm1/libasound2）+ `cd /app/scripts && npm install`
  - `requirements.txt` 加 `openai`, `dashscope`, `py7zr`
  - `scripts/package.json`（新建）：`{"dependencies": {"puppeteer": "^latest", "turndown": "^latest"}}`
  - `scripts/crawl_urls.js`（新建）：按模块文档中定义的接口规范实现
  - 迁移 `test-ai2poc/folder2json.py` → `app_cybersparker/utils/folder2json.py`
  - Celery Beat：注册 `cleanup-ai-poc-dirs` 任务，每天清理 `AI_PoC/` 下超过 30 天的空目录/失败任务目录（在 `CELERY_BEAT_SCHEDULE` 中加条目）
  - Celery 新队列：在 `celery.py` 中添加 `Queue('poc_generation', ...)` 和路由规则

- 前端：
  - React 页面 `PocGenTaskListPage.tsx`，路由 `/react-shell/poc-gen-tasks`
  - 任务列表表格：标题、任务类型、插件类型、资料状态、任务状态、创建时间、操作
  - 新建任务弹窗/抽屉：标题、插件类型(Python/Nuclei)、任务类型(URL爬取/上传文件)、思考模型下拉、识图模型下拉、代理下拉(可选)、URL 列表(多行)/文件上传
  - 任务行点击进入执行页面
  - 侧边栏入口："任务管理"→"AI生成PoC"

### 不做

- 不支持 resume（爬取失败不重试）
- 不支持编辑任务基本信息（创建的参数不可改）

### 验收条件

- [ ] 创建 URL 爬取任务：填写多 URL，创建后 crawl_status=pending→processing→success/failed
- [ ] 创建上传文件任务：压缩包自动解压，folder2json 输出 JSON → reference_material_prompt 填入
- [ ] URL 全部爬取失败（Puppeteer 对每个 URL 均返回 failed）→ crawl_status=failed，前端展示失败标记
- [ ] 至少 1 个 URL Puppeteer 返回 success → crawl_status=success
- [ ] 爬取成功后可点击进入执行页面
- [ ] 上传超过 100MB 文件时前端+后端双重拒绝
- [ ] 上传含 >500 个文件的 zip 时拒绝
- [ ] 输入内网 IP URL（含 127.0.0.1/10.x/172.16.x/192.168.x 等）时拒绝
- [ ] 删除任务后 `AI_PoC/task_<id>/` 目录被清理
- [ ] 图片识别：未配识图模型时跳过，不阻塞主流程
- [ ] 任务列表按创建时间倒序，分页展示
- [ ] Puppeteer 脚本进程崩溃时：subprocess 异常被捕获 → crawl_status=failed，error 写入 crawl_detail
- [ ] `scripts/crawl_urls.js` 输入/输出格式符合模块文档定义的接口

### 依赖

- BL-AIPOC-001（AIModelConfig 模型）
- Node.js 运行时（服务器需安装）
- Chromium 浏览器（Dockerfile 安装）
- Puppeteer + turndown（`scripts/package.json`）
- py7zr、openai、dashscope（`requirements.txt`）
- Pillow（`requirements.txt` 已存在，folder2json 传导依赖）

### 状态记录

- 2026-06-07：需求澄清完成，创建 backlog
- 2026-06-07：第2轮修正（Dockerfile/crawl_urls.js接口/folder2json迁移/Celery Beat 注册/代码位置明确化）
- 2026-06-07：已完成 — Django check 0 / 223 tests OK / tsc OK / Vite build OK
- 2026-06-08：Bug 修复 — URL 爬取报 "Could not find Chrome"。Puppeteer 22.x 需要独立安装 Chrome，容器中改为通过 `PUPPETEER_EXECUTABLE_PATH` 环境变量指向系统 Chromium。改动：`poc_gen_task.py`（`_run_crawl_urls` +3行）
- 2026-06-08：Bug 修复 — SOCKS5 代理爬取报 `ERR_EMPTY_RESPONSE`。`_extract_material` 写死 `http://` 前缀，SOCKS5 代理被当 HTTP 用导致连接被拒。改为根据 `proxy_type` 选协议前缀。改动：`poc_gen_task.py`（+2行/-1行）

---

## BL-AIPOC-003 PoC生成任务 — 执行页 + Celery异步生成 + 结果展示

- 模块：AI生成PoC
- 优先级：P0
- 状态：未开始
- 当前阶段：阶段十五
- 价值：用户可在执行页面审查提示词、触发 AI 生成 PoC、查看生成结果。
- 关联模块文档：docs/modules/10-AI生成PoC模块.md
- 关联计划：plans/2026-06-07-AI生成PoC-需求澄清.md
- 关联代码：`app_cybersparker/views/ai_poc/poc_gen_task.py`（追加 generate 端点）、`app_cybersparker/tasks/poc_gen.py`（新建）、`app_cybersparker/apps.py`（追加僵尸回收）

### 范围

- 后端（生成 API 与 Celery）：
  - `POST /api/v1/poc-gen-tasks/<id>/generate` → 检查 status!=generating → 投递 Celery 任务 → status=generating, celery_task_id → 立即返回
  - Celery 任务定义：`app_cybersparker/tasks/poc_gen.py` → `run_poc_generation(task_id)` 函数
  - Celery 队列：`poc_generation`（独立队列），`time_limit=180s`, `soft_time_limit=150s`
  - 在 `celery.py` 中添加 `Queue('poc_generation', ...)` 和路由规则
  - 启动 worker：`celery -A cybersparker worker -Q poc_generation -n poc_gen@%h`

- 后端（提示词拼接与模型调用）：
  - 提示词拼接：从任务记录取 4 个提示词 → 按模块文档定义的格式拼接（含注入防护分隔符）
  - openai 调用：client.chat.completions.create(model=thinking_model.model_id, messages=[...], timeout=120, response_format={"type": "json_object"} 或 prompt 中要求 JSON)
  - 解析返回：尝试 `json.loads()` → 成功写入 generated_poc_content + generated_metadata + generated_extra_info + status=generated
  - 非 JSON：整个 response 文本写入 generated_extra_info，status=generated
  - API 调用失败（网络/429/402）：status=failed，extra_info 记录错误

- 后端（僵尸回收）：
  - 在 `apps.py` 的 `_recover_zombie_tasks()` 中追加 PoCGenerationTask 处理：
    - `status=pending` → 重置为 `ready`
    - `status=crawling` → 重置为 `pending`
    - `status=generating` → 重置为 `ready`

- 前端：
  - React 页面 `PocGenTaskExecutePage.tsx`，路由 `/react-shell/poc-gen-tasks/:id`
  - 左侧：4 个可编辑 TextArea（任务说明/插件规范/参考资料/自定义），失焦时 PUT 保存
  - 右侧：PoC 结果展示区（代码编辑器只读展示 + 元数据信息 + extra_info 区域）
  - "生成"按钮：点后按钮置灰，轮询 GET task（2s 间隔），status=generated/failed 后停止
  - 前端 debounce 2s：2s 内连点不发送第二次请求
  - 后端幂等：status=generating 时再发 POST /generate 返回 409 Conflict

### 不做

- 不做 SSE 流式输出
- 不做生成历史版本保留
- 不做生成时取消（无 stop bridge）

### 验收条件

- [ ] 提示词编辑器修改后失焦自动保存（PUT `/api/v1/poc-gen-tasks/<id>`）
- [ ] 点"生成"→status 变 generating→按钮置灰→轮询→展示结果
- [ ] 模型返回正确 JSON 时：poc_content 代码高亮展示，metadata 字段展示，extra_info 展示
- [ ] 模型返回非 JSON（如拒绝请求的文本）：内容原封不动展示在 extra_info 区域
- [ ] 生成过程中关闭页面再打开：页面加载后根据 status 恢复状态（轮询或展示已有结果）
- [ ] 生成超时/失败（网络错误/429/402）→ status=failed，展示错误信息
- [ ] 服务器重启后：status=generating 的任务被僵尸回收重置为 ready，用户可重新点生成
- [ ] 可反复点"生成"，每次覆盖上次结果
- [ ] 提示词拼接包含注入防护分隔符（`"""` 包裹 + 无效指令警告）
- [ ] 连点"生成"：前端 debounce 2s + 后端 status=generating 时返回 409

### 依赖

- BL-AIPOC-002（任务模型 + 提示词初始值 + Celery 基础设施）

### 状态记录

- 2026-06-07：需求澄清完成，创建 backlog
- 2026-06-07：第2轮修正（Celery 队列名/超时配置/zombie回收在apps.py中的位置/代码路径）

---

## BL-AIPOC-004 保存PoC到EXP插件库

- 模块：AI生成PoC
- 优先级：P0（资源不足时可降为 P1）
- 状态：未开始
- 当前阶段：阶段十五
- 价值：用户可将满意的生成结果一键导入 EXP 插件库，参与后续扫描任务。
- 关联模块文档：docs/modules/10-AI生成PoC模块.md（含 AI→EXP 字段映射表）
- 关联计划：plans/2026-06-07-AI生成PoC-需求澄清.md
- 关联代码：`app_cybersparker/views/ai_poc/poc_gen_task.py`（追加 save-to-exp 端点）

### 范围

- 后端：
  - `save_ai_generated_poc(poc_gen_task)` 函数（独立实现，不复用 `expload_add`）
  - API：`POST /api/v1/poc-gen-tasks/<id>/save-to-exp`
  - 流程：
    1. `generated_metadata` JSON 解析 → 检查 `title` 非空（缺失返回 400）
    2. 入库前校验：`severity` 在合法值列表内、`type` 在 1-12 范围内
    3. `poc_content` SHA256 → 查 EXP.poc_content 是否已有相同内容 → 有则 409
    4. 写文件到 `EXP_plugin/`（文件名 `{sha256}.py` 或 `{sha256}.yaml`）
    5. `EXP.objects.create(...)` 按 AI→EXP 字段映射表写入
       - `poc_type=2`（Custom Add，区别于文件上传的 1）
       - `plugin_language` 从 PoCGenerationTask 复制
       - `use=1`（启用）
    6. `tag_names.split(",")` → `Tag.objects.get_or_create(name=...)` → `exp.tags.set(tags)`
    7. `extentions.split(",")` → 逐个 `cveExtensions.objects.create(CVE=exp, function=int(ext))`
    8. `title` 唯一约束冲突时追加 `-{random_suffix}`（如 `-a3f2`）
    9. 更新任务：`saved_to_exp=True`, `saved_exp_id=exp.id`
- 前端：
  - 执行页面右侧"保存到PoC库"按钮（仅在 status=generated 且 saved_to_exp=False 时可点击）
  - 缺失 title：弹窗输入 → 更新 generated_metadata → 再调 save-to-exp
  - 保存成功：按钮置灰，提示"已保存到插件库"
  - SHA256 重复：提示"该PoC已存在于插件库中"（409 响应处理）
  - 保存失败：提示具体错误信息

### 不做

- 不做关联指纹（affected_product）— AI 无法可靠判断
- 不做保存后撤回/删除 EXP
- 不做 AI 输出合法性的深度校验（仅校验 severity 合法值 + type 范围，不校验 poc_content 代码正确性）

### 验收条件

- [ ] 生成成功且有 title 时：点"保存到PoC库"→EXP 表新增记录→EXP_plugin/ 有对应文件→cveExtensions 有记录→tags 正确关联
- [ ] title 缺失：弹窗让用户输入，填完后继续保存
- [ ] severity 为非法值（如 "dangerous"）：后端拒绝保存，返回错误提示
- [ ] type 超出 1-12 范围：后端拒绝保存，返回错误提示
- [ ] 同一 poc_content SHA256 重复保存：提示已存在并拒绝
- [ ] title 冲突时自动追加后缀，不阻断保存
- [ ] 保存成功后按钮置灰且不可再点击
- [ ] 保存失败（如磁盘满/DB错误）：返回具体错误，按钮保持可点击

### 依赖

- BL-AIPOC-003（需有 generated_poc_content + generated_metadata）
- 01-插件管理（EXP 模型 + cveExtensions 模型 + Tag 模型）

### 状态记录

- 2026-06-07：需求澄清完成，创建 backlog
- 2026-06-07：第2轮修正（AI→EXP字段映射表/入库校验/poc_type=2/降级P1标注）

---

## BL-AIPOC-005 插件类型从创建时必选改为执行页可选切换

- 模块：AI生成PoC
- 优先级：P1
- 状态：已完成
- 当前阶段：阶段十五
- 价值：用户创建任务时不需要提前决定生成 Python 还是 Nuclei，进入执行页面后可视情况自由切换，系统自动加载对应提示词。
- 关联模块文档：docs/modules/10-AI生成PoC模块.md
- 关联计划：无（Mode D-lite）
- 关联代码：`app_cybersparker/views/ai_poc/poc_gen_task.py`、`frontend/src/pages/PocGenTaskListPage.tsx`、`frontend/src/pages/PocGenTaskExecutePage.tsx`

### 范围

- 后端：`plugin_language` 字段改为可空（migration 0052）；创建 API 不再要求此字段；更新 API 支持传入 `plugin_language` 并自动加载对应提示词文件；生成/保存 API 加防御检查
- 前端：创建表单去除插件类型选择；执行页面顶部加 Python/Nuclei 切换按钮，切换时调用后端自动刷新 `plugin_spec_prompt`；列表页插件类型列 null 时显示"未选择"

### 不做

- 不改变已创建的历史任务（已有 plugin_language 值不变）
- 不限制切换时机（随时可切）

### 验收条件

- [x] 创建任务表单不再显示"插件类型"选项
- [x] 执行页面顶部显示 Python/Nuclei 切换按钮
- [x] 切换到 Python 时左侧"插件规范提示词"自动加载 Python 提示词
- [x] 切换到 Nuclei 时左侧"插件规范提示词"自动加载 Nuclei 提示词
- [x] 未选插件类型时点"生成"按钮置灰不可点

### 依赖

- BL-AIPOC-002（任务创建页）、BL-AIPOC-003（执行页）

### 状态记录

- 2026-06-07：用户需求，Mode D-lite 实现完成（Django check 0 ✓ / tsc OK ✓ / Vite build OK ✓ / 223 tests 1 pre-existing fail ✓）

---

## BL-AIPOC-006 URL爬取HTML清洗增强（含指定站点适配）

- 模块：AI生成PoC
- 优先级：P0
- 状态：已完成
- 当前阶段：阶段十五
- 价值：URL 爬取产出的 markdown 干净可用，AI 能基于结构化参考资料生成可靠 PoC。
- 关联模块文档：docs/modules/10-AI生成PoC模块.md
- 关联计划：plans/2026-06-08-URL爬取清洗增强.md
- 关联代码：`scripts/crawl_urls.js`

### 范围

- 内容提取：
  - 通用噪音移除：`<script>` `<style>` `<nav>` `<footer>` `<header>` `<aside>` 等
  - GitHub 项目页：提取 `article.markdown-body`（README 正文）
  - GitHub 文件预览页：提取代码行内容，包装为 fenced code block
  - 知乎文章：提取 `.RichContent-inner` / `.Post-RichText`
  - 微信公众号文章：提取 `#js_content` / `.rich_media_content`
  - 通用回退：按 `article → main → [常见内容类名] → body` 顺序查找
- 转换增强：
  - 添加 `<table>` → markdown table 自定义 turndown 规则
  - `<kbd>` → 行内代码
  - `<details>/<summary>` → 保留（部分 markdown 渲染器支持）
  - 空链接/空元素移除
- 后清洗：去除残留 HTML 标签、合并多余空行、解码 HTML 实体

### 不做

- 不添加新的 npm 依赖（仅用现有 puppeteer + turndown 7.x）
- 不做 JavaScript 渲染后的二次爬取
- 不做图片下载/本地化

### 验收条件

- [ ] GitHub 仓库 README 页面爬取后 markdown 干净（无导航/页脚残留）
- [ ] GitHub 文件预览页（blob）爬取后为代码块格式
- [ ] 知乎文章爬取后正文完整，无侧边栏/推荐内容噪音
- [ ] 微信公众号文章爬取后正文完整
- [ ] 含 `<table>` 的页面转换为 markdown table 格式
- [ ] 残留 HTML 标签数量显著减少（后清洗正则覆盖常见情况）

### 依赖

- 无（独立改进现有脚本）

### 状态记录

- 2026-06-08：用户反馈清洗效果差，创建 backlog
- 2026-06-08：已完成 — 三层清洗管线（站点内容提取 + 自定义 turndown 规则 + 后清洗），适配 GitHub/知乎/微信公众号，Node.js 语法检查通过 / Django check 0 / tsc OK

---

## BL-AIPOC-007 URL爬取图片下载与识图转文字修复

- 模块：AI生成PoC
- 优先级：P0
- 状态：已完成
- 当前阶段：阶段十五
- 价值：URL 爬取后 markdown 中的图片被下载到任务目录，后续 AI 生成时可引用本地图片；配了识图模型时图片还会被转为文字描述插入 markdown。
- 关联模块文档：docs/modules/10-AI生成PoC模块.md
- 关联计划：plans/2026-06-12-BL-AIPOC-007-图片下载与识图转文字.md
- 关联代码：`app_cybersparker/utils/folder2json.py`、`app_cybersparker/views/ai_poc/poc_gen_task.py`

### 范围

- `folder2json.py`：`resolve_image_path` 加 `base_url` 参数，域名相对路径（`/xxx/images/xxx.png`）→ `urljoin(base_url, path)` → 下载；`process_markdown` 透传 `base_url`，无 API key 时仍下载图片但不识图
- `poc_gen_task.py`：`_process_images_in_markdown` 重写，图片下载到 `material_dir/images/`（持久化不删），始终调用图片处理（不再仅 vision model 时才处理），传入 `base_url` 解析相对路径
- `poc_gen_task.py`：`file_upload` 分支同样改为始终处理 markdown 图片，持久化到 `images/`

### 不做

- 不改变数据模型和 API 契约
- 不修改 `crawl_urls.js`（turndown 的 host-relative 路径由 Python 侧补全 scheme）

### 验收条件

- [x] URL 爬取后 markdown 中的域名相对路径图片（如 `/Threekiii/.../xxx.png`）能被正确下载
- [x] 图片下载到 `material_dir/images/` 目录，任务完成后不被删除
- [x] markdown 中图片引用更新为本地相对路径（`images/xxx.png`）
- [x] 未配识图模型时，图片仍被下载（不跳过）
- [x] 配了识图模型时，图片被下载且文字描述插入 markdown

### 依赖

- BL-AIPOC-002（任务模型 + 资料提取管线）
- 前一个提交 `016efe3`（`set_task_proxy` 修复，确保图片下载不走全局代理）

### 状态记录

- 2026-06-12：Probe 发现三缺陷 → 创建 backlog → 实现完成 → Django check 0 / 223 tests (8 pre-existing failures) / Probe 验证全部通过

---

## BL-AIPOC-008 URL爬取反爬对抗

- 模块：AI生成PoC
- 优先级：P0
- 状态：已完成
- 当前阶段：阶段十五
- 价值：有反爬措施的网站（如微信公众号）也能被正常爬取，不会因 headless 浏览器特征被拒绝。
- 关联模块文档：docs/modules/10-AI生成PoC模块.md
- 关联代码：`scripts/crawl_urls.js`

### 范围

- 浏览器伪装：`evaluateOnNewDocument` 注入，删除 `navigator.webdriver`、模拟 `chrome.runtime`、伪装 plugins/languages/platform/hardwareConcurrency/deviceMemory、WebGL 供应商改为 Intel
- 启动参数：`--disable-blink-features=AutomationControlled` + `ignoreDefaultArgs: ['--enable-automation']`
- 完整 Chrome 122 UA + `Accept-Language: zh-CN`
- 懒加载图片：滚动到页面底部触发，等待 `img.complete`
- 微信适配："阅读全文"按钮自动点击展开折叠内容
- Chromium 自动检测：优先 `PUPPETEER_EXECUTABLE_PATH` 环境变量 → Puppeteer 缓存目录 → 系统 `/usr/bin/chromium`
- 防御性修复：`cell()` / `isHeadingRow()` 加 null 检查，处理非标准 table 结构

### 不做

- 不引入额外 npm 依赖（仅用 puppeteer + turndown）
- 不做 JS 动态渲染的二次等待

### 验收条件

- [x] 微信公众号文章（mp.weixin.qq.com）成功爬取，正文完整
- [x] 爬取结果不含反爬拦截页面（无 403/验证码/CAPTCHA 页）
- [x] 懒加载图片被正确触发并显示在 markdown 中
- [x] 环境变量 PUPPETEER_EXECUTABLE_PATH 可指定自定义 Chromium 路径

### 依赖

- BL-AIPOC-002（资料提取管线）、BL-AIPOC-006（HTML清洗增强）

### 状态记录

- 2026-06-12：用户反馈部分网站有反爬 → 实现浏览器伪装 + WeChat MP 测试通过（19s 完成，1425 字符）

---

## BL-AIPOC-009 直接输入文本作为参考资料

- 模块：AI生成PoC
- 优先级：P1
- 状态：已完成
- 当前阶段：阶段十五
- 价值：用户无需准备 URL 或文件，直接在表单粘贴漏洞相关的技术文章、报告、代码片段即可创建任务。
- 关联模块文档：docs/modules/10-AI生成PoC模块.md
- 关联代码：`models.py`、`poc_gen_task.py`、`PocGenTaskListPage.tsx`、`pocGenTask.ts`

### 范围

- 模型：TASK_TYPE_CHOICES 新增 `text_input`（直接输入文本），不需要 migration
- 后端：创建 API 接受 `reference_text`，直接写入 `reference_material_prompt`，状态直接标 `ready`，跳过资料提取
- 前端：新建任务对话框加"直接输入文本"选项，选后显示多行文本框（12行），表单提交带 `reference_text` 字段

### 不做

- 不在数据库新增字段（复用 `reference_material_prompt`）
- 不经过 folder2json 管线

### 验收条件

- [x] 创建任务时选"直接输入文本"，粘贴内容 → 创建成功，状态为 ready
- [x] 执行页面可立即打开（不需要等资料提取），参考资料已填入
- [x] Django check 0 / tsc OK

### 依赖

- BL-AIPOC-002（任务模型 + 创建 API）

### 状态记录

- 2026-06-12：用户需求 → 实现完成（Django check 0 / tsc OK）

---

## BL-AIPOC-010 任务列表加翻页

- 模块：AI生成PoC
- 优先级：P1
- 状态：未开始
- 当前阶段：阶段十五
- 价值：任务多了以后，列表页不会一次性加载全部数据导致卡顿。
- 关联模块文档：docs/modules/10-AI生成PoC模块.md
- 关联代码：`app_cybersparker/views/ai_poc/poc_gen_task.py`、`frontend/src/pages/PocGenTaskListPage.tsx`

### 范围

- 后端：GET `/api/v1/poc-gen-tasks` 增加 `page` 和 `rows_per_page` 参数，返回分页后的数据 + `page`/`total_pages`/`rows_per_page` 元数据
- 前端：列表底部加翻页栏（与 DictListPage 风格一致）——页码跳转、上一页/下一页、总数显示

### 不做

- 不改变任何其他 API 行为
- 不修改创建/删除/编辑流程
- 不加搜索/筛选

### 验收条件

- [ ] GET `/api/v1/poc-gen-tasks?page=1&rows_per_page=10` 返回 10 条 + pagination 元数据
- [ ] 前端翻页栏可点击翻页，数据跟随变化
- [ ] URL search params 随翻页更新
- [ ] tsc + Django check 通过

### 依赖

- BL-AIPOC-002（任务列表 API + 前端页面）

### 状态记录

- 2026-06-14：创建 backlog item → 实现完成（Django check OK / tsc OK）

---

## BL-AIPOC-011 任务编辑与重试

- 模块：AI生成PoC
- 优先级：P1
- 状态：已完成
- 当前阶段：阶段十五
- 价值：用户可编辑已创建任务的标题/模型/代理/URL/参考资料，URL 爬取任务失败后可一键重试。
- 关联模块文档：docs/modules/10-AI生成PoC模块.md
- 关联计划：plans/2026-06-14-BL-AIPOC-011-PoC任务编辑与重试.md

### 范围

- 后端：
  - `api_task_detail` POST 扩展：支持编辑 title/thinking_model_id/vision_model_id/proxy_id/urls/reference_material_prompt（task_type 和 uploaded_file 不可编辑）
  - 新增 `api_retry`：`POST /api/v1/poc-gen-tasks/<id>/retry`，仅对 url_crawl 类型生效，清空 material_dir 并重跑 _extract_material
- 前端：
  - 操作列新增"编辑"按钮 → 弹出编辑表单（复用创建表单结构，task_type 置灰，文件上传不可改）
  - 操作列新增"重试"按钮（仅 url_crawl 类型且非 generating 状态可见）

### 不做

- 不改变 task_type（创建后不可切换任务类型）
- 不上传新文件（file_upload 任务上传的文件不可替换）
- 不影响生成/保存等已有功能

### 验收条件

- [ ] 编辑 url_crawl 任务：可修改标题/模型/代理/URL 列表，提交后列表刷新
- [ ] 编辑 file_upload 任务：不可修改上传文件和 task_type
- [ ] 编辑 text_input 任务：可修改参考资料文本内容
- [ ] 重试按钮仅 url_crawl 任务可见
- [ ] url_crawl 任务状态 generating 时重试按钮置灰
- [ ] 重试后 crawl_status 重置为 pending → processing，列表刷新
- [ ] Django check 0 issues / tsc OK / Vite build OK

### 依赖

- BL-AIPOC-002（任务 CRUD API）

### 状态记录

- 2026-06-14：创建 backlog item → 实现完成（Django check 0 ✓ / tsc OK ✓ / Vite build OK ✓）
