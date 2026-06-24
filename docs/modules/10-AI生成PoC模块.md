# 10-AI生成PoC模块

> 状态：需求已澄清，backlog 已审查 | 2026-06-07

## 模块职责

用户配置 AI 模型 → 通过 URL 爬取、上传文件或直接输入文本提供参考资料 → AI 自动生成 Python/Nuclei 漏洞验证 PoC → 保存到 EXP 插件库。

## 代码位置规划

| 层 | 位置 | 说明 |
|----|------|------|
| 数据模型 | `app_cybersparker/models.py` | `AIModelConfig` + `PoCGenerationTask` |
| AI模型配置视图 | `app_cybersparker/views/ai_poc/ai_model_config.py` | CRUD API |
| PoC生成任务视图 | `app_cybersparker/views/ai_poc/poc_gen_task.py` | 任务 CRUD + 生成 + 保存 |
| Celery 任务 | `app_cybersparker/tasks/poc_gen.py` | PoC 生成异步任务 |
| 工具函数 | `app_cybersparker/utils/folder2json.py` | 从 `test-ai2poc/folder2json.py` 迁移 |
| Puppeteer 脚本 | `scripts/crawl_urls.js` | Node.js 爬虫脚本 |
| npm 依赖 | `scripts/package.json` | puppeteer + turndown |

## 核心实体

### AIModelConfig（AI模型配置）

| 字段 | 类型 | 说明 |
|------|------|------|
| name | CharField | 配置名称 |
| model_id | CharField | 模型 ID（如 gpt-4o） |
| api_url | URLField | API 地址 |
| api_key | CharField | API Key（明文，前端脱敏） |
| model_type | CharField | thinking（思考/生成PoC）/ vision（识图） |
| created_at | DateTimeField | |

### PoCGenerationTask（PoC生成任务）

一条记录承载完整生命周期：创建 → 资料提取 → 提示词编辑 → AI 生成 → 保存到 EXP。

| 字段 | 类型 | 说明 |
|------|------|------|
| title | CharField | 任务标题 |
| task_type | CharField | url_crawl / file_upload / text_input |
| plugin_language | IntegerField | null=True, 1=Python / 2=Nuclei YAML，创建时不设置，在执行页面由用户选择 |
| thinking_model | FK→AIModelConfig | |
| vision_model | FK→AIModelConfig | null=True |
| urls | TextField | URL 列表（JSON 数组） |
| proxy | FK→ProxySetting | null=True, on_delete=SET_NULL |
| uploaded_file | CharField | 上传文件在 AI_PoC 下的路径 |
| crawl_status | CharField | pending/processing/success/failed |
| crawl_detail | TextField | JSON，每个 URL 的爬取结果 |
| material_dir | CharField | `AI_PoC/task_<id>/` |
| task_description_prompt | TextField | 硬编码默认值，可改，持久化 |
| plugin_spec_prompt | TextField | 按 plugin_language 选默认值，可改，持久化 |
| reference_material_prompt | TextField | 系统自动生成，可改，持久化 |
| custom_prompt | TextField | 默认空，持久化 |
| generated_poc_content | TextField | 最新一次生成的 PoC 代码 |
| generated_metadata | TextField | 元数据 JSON |
| generated_extra_info | TextField | 额外信息（报错/总结） |
| saved_to_exp | BooleanField | 是否已保存到 EXP 库 |
| saved_exp_id | IntegerField | 对应的 EXP ID |
| status | CharField | pending/crawling/ready/generating/generated/failed |
| celery_task_id | CharField | Celery task_id |
| created_at | DateTimeField | |
| updated_at | DateTimeField | |

## 状态机

```
pending ──(触发爬取)──→ crawling ──(成功)──→ ready
                          │                    │
                          └──(全部失败)──→ failed
                                               │
generating ←──(点"生成")── ready ←──(僵尸回收)── pending/generating/crawling
     │
     └──(Celery完成)──→ generated
```

启动僵尸回收（在 `apps.py` 的 `_recover_zombie_tasks()` 中追加）：
- `pending` → `ready`
- `crawling` → `pending`（爬虫子进程已随进程退出而消失）
- `generating` → `ready`（Celery 任务可能仍在执行，但旧 task_id 已无法追踪）

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/ai-model-configs | 模型配置列表 |
| POST | /api/v1/ai-model-configs | 新增模型配置 |
| PUT | /api/v1/ai-model-configs/\<id\> | 编辑模型配置 |
| DELETE | /api/v1/ai-model-configs/\<id\> | 删除模型配置 |
| GET | /api/v1/poc-gen-tasks | 任务列表 |
| POST | /api/v1/poc-gen-tasks | 创建任务（含文件上传/URL列表） |
| GET | /api/v1/poc-gen-tasks/\<id\> | 任务详情（含提示词、生成结果） |
| POST | /api/v1/poc-gen-tasks/\<id\> | 更新任务（提示词/插件类型/元数据编辑） |
| DELETE | /api/v1/poc-gen-tasks/\<id\> | 删除任务（级联清理） |
| POST | /api/v1/poc-gen-tasks/\<id\>/generate | 触发 Celery 生成 |
| POST | /api/v1/poc-gen-tasks/\<id\>/save-to-exp | 保存到 EXP 插件库 |
| POST | /api/v1/poc-gen-tasks/\<id\>/retry | 重试URL爬取（仅url_crawl，清空目录重爬） |

## Celery 配置

| 项目 | 值 |
|------|-----|
| 队列名 | `poc_generation`（独立队列，避免阻塞 maintenance） |
| Task time_limit | 180s（openai 超时 120s + 缓冲） |
| Task soft_time_limit | 150s |
| 路由 | `app_cybersparker.tasks.poc_gen.*` → `poc_generation` 队列 |

需在 `celery.py` 中新增 `Queue('poc_generation', ...)` 和对应路由规则。

启动 worker：`celery -A cybersparker worker -Q poc_generation -n poc_gen@%h`

## AI → EXP 字段映射表

`save_ai_generated_poc()` 写入 EXP 表时的字段转换：

| AI JSON 字段 | EXP 模型字段 | 转换逻辑 |
|-------------|-------------|---------|
| `title` | `title` | 直接赋值（冲突时追加随机后缀） |
| `cve` | `CVE` | 直接赋值 |
| `type` | `Type` | 直接赋值（int），入库前校验 1-12 范围 |
| `severity` | `severity` | 直接赋值，入库前校验合法值列表 |
| `ctime` | `time` | `datetime.strptime(ctime, '%Y/%m/%d').date()`，空则 None |
| `tags` | `tags` | `split(",")` → get_or_create Tag → `.set()` |
| `extentions` | `cveExtensions` | `split(",")` → 逐个 `cveExtensions.objects.create(CVE=exp, function=int(...))` |
| `poc_content` | `poc_content` | 直接赋值 |
| (硬编码) | `poc_type` | 固定 `2`（Custom Add） |
| (硬编码) | `plugin_language` | 从 `PoCGenerationTask.plugin_language` 复制 |
| (硬编码) | `use` | 固定 `1`（启用） |
| (文件写入) | `poc` | 写 `.py`/`.yaml` 文件到 `EXP_plugin/`，文件名为 `{sha256}.{ext}` |

## Puppeteer 爬取接口（crawl_urls.js）

Python 端通过 `subprocess.run(["node", "/app/scripts/crawl_urls.js"], input=json_str, capture_output=True, timeout=total_timeout)` 调用。`total_timeout = max(N * 100 + 30, 300)`，N 为 URL 数量。

**输入**（stdin JSON）：

```json
{
  "urls": ["https://example.com/vuln", "https://example.com/advisory"],
  "proxy": "http://proxy_host:8080",
  "timeout_ms": 100000,
  "save_dir": "/path/to/task_<id>/img"
}
```

- `proxy` 为 `null` 时不使用代理；非 `null` 时协议前缀由 `ProxySetting.proxy_type` 决定（1→`http://`, 4→`socks5://`）
- `timeout_ms` 是每个 URL 的 page.goto 超时（100s）
- `save_dir`：可选，指定后浏览器已加载的图片 buffer 直接写入该目录，markdown 引用替换为 `img/xxx.png`

**输出**（stdout JSON）：

```json
{
  "results": [
    {
      "url": "https://example.com/vuln",
      "status": "success",
      "markdown": "# 页面标题\n...",
      "error": null,
      "elapsed_ms": 3200
    },
    {
      "url": "https://example.com/blocked",
      "status": "failed",
      "markdown": null,
      "error": "net::ERR_CONNECTION_REFUSED",
      "elapsed_ms": 30100
    }
  ]
}
```

- `status` 为 `success` 或 `failed`
- 失败时 `markdown` 为 null，`error` 描述原因
- 多个 URL 顺序执行（非并行），避免资源耗尽

**清洗管线**（四层，在 `crawlUrl()` 中按顺序执行）：

1. **浏览器端内容提取**（`page.evaluate`）：先移除通用噪音元素（script/style/nav/footer/header/sidebar 等 + HTML 注释），再按域名匹配站点选择器（GitHub→`article.markdown-body` 或 blob 代码行、知乎→`.RichContent-inner`、微信公众号→`#js_content`），未匹配则按 `article → main → .markdown-body → body` 顺序查找正文。
2. **turndown 自定义规则**：`<table>`→markdown table、`<kbd>`→行内代码、`<details>/<summary>`→HTML 穿透、空链接（不含 `<img>` 子元素）/空元素→移除。
3. **图片保存**：`page.on('response')` 拦截已加载图片的 buffer → 正则匹配 markdown 中 `![](url)` → hash 命名写入 `save_dir` → markdown 引用改为本地路径 `img/xxx.png`。
4. **后清洗**：正则去除残留 HTML 标签（保留 `<details>` `<summary>`）、解码 `&amp;` `&lt;` `&gt;` `&nbsp;` 及数字实体、合并 3+ 连续空行为 2 个、去除行尾空格。

**环境依赖**：chromium 浏览器（`/usr/bin/chromium`），Python 端调用 `subprocess.run` 时通过环境变量 `PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium` 指定 Chromium 路径，Puppeteer 启动参数 `--no-sandbox --disable-setuid-sandbox`

## 提示词默认值初始化时序

创建任务时（POST /api/v1/poc-gen-tasks 处理中）：

1. `task_description_prompt` ← 硬编码默认值（见需求澄清文档）
2. `plugin_spec_prompt` ← 空字符串（等待用户在执行页面选择插件类型后填充）
3. `reference_material_prompt` ← 空字符串（资料提取完成后再填充）
4. `custom_prompt` ← 空字符串

执行页面切换插件类型时（POST /api/v1/poc-gen-tasks/<id> 含 `plugin_language`）：
- `plugin_language` 更新 → `plugin_spec_prompt` ← 读 `docs/Python-PoC插件生成提示词.md` 或 `docs/Nuclei-YAML模板生成提示词.md` 全文

资料提取完成后（爬取/解压→JSON后）：
- `reference_material_prompt` ← 爬取的 markdown / folder2json 的 JSON 字符串
- 保存到任务记录

## URL 安全校验规则

Puppeteer 脚本内置 URL 校验（Python 侧也做一次）：

- 只允许 `http://` 和 `https://` 协议
- 解析 host → 拒绝以下 IP 段：
  - `127.0.0.0/8` (loopback)
  - `10.0.0.0/8` (private)
  - `172.16.0.0/12` (private)
  - `192.168.0.0/16` (private)
  - `169.254.0.0/16` (link-local)
  - `0.0.0.0/8` (RFC 1122 "this network")
  - `::1` (IPv6 loopback)
  - `fe80::/10` (IPv6 link-local)
- host 不是合法 IP 时，先 DNS 解析再校验（防止 DNS rebinding 指向内网）

## 依赖

- 01-插件管理：EXP 表入库
- 05-异步任务：Celery worker + Beat
- 03-指纹与自动识别：ProxySetting 模型
- 外部 Node.js：Puppeteer + turndown（`scripts/package.json`）
- 外部 Python：openai、dashscope、py7zr（`requirements.txt`）
- 现有：Pillow（`requirements.txt` 已存在，folder2json 需要）

## Dockerfile 要求

新增以下依赖：
```
RUN apt-get update && apt-get install -y \
    chromium-browser \
    nodejs npm \
    libnss3 libatk-bridge2.0-0 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2
RUN cd /app/scripts && npm install
```

## 前端页面

| 页面 | React 路由 | 源文件 |
|------|-----------|--------|
| AI模型配置 | /react-shell/ai-model-configs | pages/AiModelConfigPage.tsx |
| AI生成PoC（列表+创建） | /react-shell/poc-gen-tasks | pages/PocGenTaskListPage.tsx |
| PoC任务执行页 | /react-shell/poc-gen-tasks/:id | pages/PocGenTaskExecutePage.tsx |

前端路由由 `_serve_react_shell` 兜底，不需要新增 Django 路由。3 个新页面文件创建后自动被 Vite 打包（`pages/**/*.tsx` 由 react-router lazy import 识别）。

## 安全

- 上传文件 ≤ 100MB，zip 内 ≤ 500 文件
- URL 爬取拒绝内网 IP 段（含 IPv4 + IPv6）
- `subprocess.run` 超时动态计算（N × 100 + 30s，最少 300s），捕获 `TimeoutExpired`
- 提示词注入防护（参考资料段 `"""` 包裹 + 无效指令警告）
- 删除任务同步清理 `AI_PoC/task_<id>/`
- SHA256 去重防止重复入库
- `save_ai_generated_poc()` 入库前校验 type 范围 1-12、severity 合法值

## 风险标注

- **AI 输出质量不可控**：模型可能生成语法错误的代码或 halluciated API。系统不做代码正确性验证，完全依赖用户手动检视。
- **Puppeteer 内存占用**：多 URL 顺序执行，单个页面内存峰值取决于页面复杂度。生产环境需监控 Node.js 进程内存。
