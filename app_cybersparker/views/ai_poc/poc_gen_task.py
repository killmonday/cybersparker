import hashlib
import json
import os
import random
import shutil
import string
import subprocess
import zipfile
import tarfile
import tempfile
import threading
from datetime import datetime as dt_datetime
from django.utils import timezone

from django.conf import settings
from django.core.files.base import ContentFile
from django.http import JsonResponse

from app_cybersparker import models
from app_cybersparker.lib.request_runtime.patch.hook_request import set_task_proxy
from app_cybersparker.utils.pagination import Pagination


def _log_error(msg: str):
    """写错误日志到 error_log/ 目录"""
    now_str = dt_datetime.now().strftime("%Y-%m-%d")
    log_path = os.path.join(BASE_DIR, "error_log", f"{now_str}_error-log.txt")
    timestamp = dt_datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[ai_poc] {timestamp} : {msg}\n")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
AI_POC_ROOT = os.path.join(BASE_DIR, "AI_PoC")

PROMPT_DOCS_DIR = os.path.join(BASE_DIR, "docs")
PLUGIN_SPEC_FILES = {
    lang: os.path.join(PROMPT_DOCS_DIR, filename)
    for lang, filename in getattr(settings, 'AI_POC_PLUGIN_SPEC_FILES', {
        1: "Python-PoC插件生成提示词.md",
        2: "Nuclei-YAML模板生成提示词.md",
    }).items()
}

TASK_DESCRIPTION_DEFAULT = getattr(settings, 'AI_POC_TASK_DESCRIPTION_PROMPT', '')

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100MB
MAX_ZIP_FILES = 500


def _json_response(data, status=200):
    return JsonResponse(data, status=status)


def _load_plugin_spec(plugin_language: int) -> str:
    path = PLUGIN_SPEC_FILES.get(plugin_language)
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _read_file_to_str(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _extract_archive(filepath: str, dest_dir: str) -> bool:
    """解压压缩包到目标目录，返回是否成功"""
    lower = filepath.lower()
    try:
        if lower.endswith(".zip"):
            with zipfile.ZipFile(filepath, "r") as zf:
                if len(zf.infolist()) > MAX_ZIP_FILES:
                    return False
                zf.extractall(dest_dir)
            return True
        elif lower.endswith((".tar.gz", ".tgz", ".tar")):
            with tarfile.open(filepath, "r:*") as tf:
                tf.extractall(dest_dir)
            return True
        elif lower.endswith(".7z"):
            import py7zr
            with py7zr.SevenZipFile(filepath, "r") as szf:
                szf.extractall(dest_dir)
            return True
        else:
            return False
    except Exception:
        return False


def _run_folder2json(material_dir: str, api_key: str | None) -> str:
    """调用 folder2json 将目录转为 JSON 字符串，api_key 传识图模型 key"""
    from app_cybersparker.utils.folder2json import folder_to_json
    try:
        result = folder_to_json(material_dir, api_key=api_key)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "files": []}, ensure_ascii=False)


def _run_crawl_urls(urls: list[str], proxy: str | None, save_dir: str = "", total_timeout: int = 300) -> dict:
    """调用 Puppeteer 脚本爬取 URL"""
    script_path = os.path.join(BASE_DIR, "scripts", "crawl_urls.js")
    per_url_ms = 100000  # 每个 URL 100s
    input_data = json.dumps({"urls": urls, "proxy": proxy, "timeout_ms": per_url_ms, "save_dir": save_dir or None}, ensure_ascii=False)
    _log_error(f"开始爬取 {len(urls)} 个 URL，per_url_timeout={per_url_ms}ms，total_timeout={total_timeout}s，proxy={proxy}，save_dir={save_dir}")
    result = None
    try:
        env = os.environ.copy()
        env.setdefault("PUPPETEER_EXECUTABLE_PATH", "/usr/bin/chromium")
        result = subprocess.run(
            ["node", script_path],
            input=input_data,
            capture_output=True,
            timeout=total_timeout,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            _log_error(f"Puppeteer 脚本返回非零 exit_code={result.returncode}，stderr={result.stderr}")
            return {"results": [{"url": u, "status": "failed", "markdown": None, "error": result.stderr or "crawl script error", "elapsed_ms": 0} for u in urls]}
        _log_error(f"Puppeteer 脚本正常结束，stdout 长度={len(result.stdout)}")
        if result.stderr:
            _log_error(f"Puppeteer stderr: {result.stderr.strip()}")
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        _log_error(f"Puppeteer 脚本超时（{total_timeout}s）")
        return {"results": [{"url": u, "status": "failed", "markdown": None, "error": f"crawl timeout ({total_timeout}s)", "elapsed_ms": 0} for u in urls]}
    except FileNotFoundError:
        _log_error(f"Node.js 未安装或脚本不存在: {script_path}")
        return {"results": [{"url": u, "status": "failed", "markdown": None, "error": f"Node.js 未安装或脚本不存在: {script_path}", "elapsed_ms": 0} for u in urls]}
    except json.JSONDecodeError as e:
        stdout_snippet = (result.stdout or "")[:500] if result else ""
        _log_error(f"Puppeteer stdout 不是有效 JSON: {e}，stdout={stdout_snippet}")
        return {"results": [{"url": u, "status": "failed", "markdown": None, "error": f"stdout 解析失败: {e}", "elapsed_ms": 0} for u in urls]}
    except Exception as e:
        _log_error(f"Puppeteer 脚本执行异常: {type(e).__name__}: {e}")
        return {"results": [{"url": u, "status": "failed", "markdown": None, "error": str(e), "elapsed_ms": 0} for u in urls]}


def _process_material_dir(task):
    """处理 material_dir 中的 markdown 图片并转 folder2json（URL crawl / file_upload 共用）"""
    material_dir = task.material_dir
    images_dir = os.path.join(material_dir, "img")
    vision_key = task.vision_model.api_key if task.vision_model else None
    _log_error(f"任务 #{task.id} 开始处理资料目录，vision={bool(vision_key)}")

    for root, _, files in os.walk(material_dir):
        for fname in files:
            if fname.lower().endswith((".md", ".markdown")):
                full = os.path.join(root, fname)
                from app_cybersparker.utils.folder2json import process_markdown
                try:
                    processed = process_markdown(full, images_dir, vision_key or "")
                    with open(full, "w", encoding="utf-8") as f:
                        f.write(processed)
                except Exception:
                    pass

    _log_error(f"任务 #{task.id} 开始 folder2json")
    json_str = _run_folder2json(material_dir, vision_key)
    task.reference_material_prompt = json_str



def _save_reference_md(material_dir: str, content: str):
    """把最终参考资料写入 material_dir/reference.md"""
    try:
        md_path = os.path.join(material_dir, "reference.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        pass


def _extract_material(task: models.PoCGenerationTask) -> dict:
    """异步提取参考资料（在创建任务后调用）"""
    _log_error(f"任务 #{task.id} 开始提取资料，task_type={task.task_type}")
    material_detail = {}

    # 设置 URL 爬取代理（仅 Puppeteer 用），不上 AI API 调用
    if task.proxy:
        proto_map = {1: "http", 4: "socks5"}
        proto = proto_map.get(task.proxy.proxy_type, "http")
        proxy_str = f"{proto}://{task.proxy.proxy_address}:{task.proxy.proxy_port}"
        set_task_proxy({"http": proxy_str, "https": proxy_str})
    else:
        set_task_proxy({})

    try:
        if task.task_type == "url_crawl":
            urls = json.loads(task.urls or "[]")
            if not urls:
                _log_error(f"任务 #{task.id} URL 列表为空")
                task.crawl_status = "failed"
                task.crawl_detail = json.dumps({"error": "no urls provided"})
                task.status = "failed"
                task.save()
                return {"error": "no urls provided"}

            proxy_str = None
            if task.proxy:
                proto_map = {1: "http", 4: "socks5"}
                proto = proto_map.get(task.proxy.proxy_type, "http")
                proxy_str = f"{proto}://{task.proxy.proxy_address}:{task.proxy.proxy_port}"

            _log_error(f"任务 #{task.id} 开始爬取 URL: {urls}")
            # Node.js 端在爬取时直接把已加载的图片保存到 images/，markdown 中引用已改为本地路径
            save_dir = os.path.join(task.material_dir, "img")
            total_timeout = max(len(urls) * 100 + 30, 300)  # 每个 URL 100s + 30s 浏览器启停缓冲，最少 300s
            crawl_result = _run_crawl_urls(urls, proxy_str, save_dir, total_timeout=total_timeout)
            task.crawl_detail = json.dumps(crawl_result, ensure_ascii=False)

            success_count = sum(1 for r in crawl_result.get("results", []) if r.get("status") == "success")
            _log_error(f"任务 #{task.id} 爬取结果: {success_count}/{len(urls)} 成功")
            if success_count == 0:
                _log_error(f"任务 #{task.id} 所有 URL 爬取失败，详情: {crawl_result}")
                task.crawl_status = "failed"
                task.status = "failed"
                task.save()
                return crawl_result

            # 合并 markdown → 写入 reference.md（图片已是 img/xxx.png 本地路径）
            md_parts = []
            for r in crawl_result.get("results", []):
                if r.get("status") == "success" and r.get("markdown"):
                    md_parts.append(f"## URL: {r['url']}\n\n{r['markdown']}")

            combined_md = "\n\n---\n\n".join(md_parts)
            _log_error(f"任务 #{task.id} 合并 markdown 完成，总长度={len(combined_md)}")
            _save_reference_md(task.material_dir, combined_md)

            # URL 爬取完成。换成 AI API 代理（如果有配置），用于后续 image_to_text 调用
            set_task_proxy({})
            if task.api_proxy:
                api_proto_map = {1: "http", 4: "socks5"}
                api_proto = api_proto_map.get(task.api_proxy.proxy_type, "http")
                api_proxy_str = f"{api_proto}://{task.api_proxy.proxy_address}:{task.api_proxy.proxy_port}"
                set_task_proxy({"http": api_proxy_str, "https": api_proxy_str})
            _process_material_dir(task)
            set_task_proxy({})

            task.crawl_status = "success"
            task.status = "ready"
            task.save()
            _log_error(f"任务 #{task.id} 资料提取完成，状态=ready")
            material_detail = crawl_result

        elif task.task_type == "file_upload":
            _log_error(f"任务 #{task.id} 文件上传模式，material_dir={task.material_dir}")
            material_dir = task.material_dir
            filepath = os.path.join(material_dir, os.path.basename(task.uploaded_file)) if task.uploaded_file else None

            if filepath and os.path.isfile(filepath):
                _log_error(f"任务 #{task.id} 解压文件: {filepath}")
                if _extract_archive(filepath, material_dir):
                    _log_error(f"任务 #{task.id} 解压成功")

            _process_material_dir(task)
            task.crawl_status = "success"
            task.status = "ready"
            task.save()
            _log_error(f"任务 #{task.id} 资料提取完成，状态=ready")
            material_detail = {"folder2json": "done"}

    except Exception as e:
        _log_error(f"任务 #{task.id} 资料提取异常: {type(e).__name__}: {e}")
        task.crawl_status = "failed"
        task.crawl_detail = json.dumps({"error": str(e)})
        task.status = "failed"
        task.save()
        material_detail = {"error": str(e)}

    return material_detail


def _task_to_dict(task: models.PoCGenerationTask) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "api_proxy_id": task.api_proxy_id,
        "task_type": task.task_type,
        "task_type_label": task.get_task_type_display(),
        "plugin_language": task.plugin_language,
        "plugin_language_label": task.get_plugin_language_display() if task.plugin_language is not None else "",
        "thinking_model_id": task.thinking_model_id,
        "thinking_model_name": task.thinking_model.name,
        "vision_model_id": task.vision_model_id,
        "vision_model_name": task.vision_model.name if task.vision_model else None,
        "proxy_id": task.proxy_id,
        "urls": task.urls,
        "uploaded_file": task.uploaded_file,
        "crawl_status": task.crawl_status,
        "crawl_status_label": task.get_crawl_status_display(),
        "crawl_detail": task.crawl_detail,
        "task_description_prompt": task.task_description_prompt,
        "plugin_spec_prompt": task.plugin_spec_prompt,
        "reference_material_prompt": task.reference_material_prompt,
        "custom_prompt": task.custom_prompt,
        "generated_poc_content": task.generated_poc_content,
        "generated_metadata": task.generated_metadata,
        "generated_extra_info": task.generated_extra_info,
        "saved_to_exp": task.saved_to_exp,
        "saved_exp_id": task.saved_exp_id,
        "status": task.status,
        "status_label": task.get_status_display(),
        "celery_task_id": task.celery_task_id,
        "created_at": task.created_at.strftime("%Y-%m-%d %H:%M") if task.created_at else "",
        "updated_at": task.updated_at.strftime("%Y-%m-%d %H:%M") if task.updated_at else "",
    }


# ======================== API 视图 ========================


def api_tasks(request):
    """GET /api/v1/poc-gen-tasks — 列表 | POST — 创建"""
    if request.method == "GET":
        queryset = models.PoCGenerationTask.objects.all().order_by("-created_at")
        page_object = Pagination(request, queryset, page_size=10)
        items = [_task_to_dict(t) for t in page_object.page_queryset]
        return JsonResponse({
            "status": True,
            "items": items,
            "total": page_object.total_count,
            "page": page_object.page,
            "total_pages": page_object.total_page_count,
            "rows_per_page": page_object.page_size,
        })

    if request.method == "POST":
        content_type = request.content_type or ""
        if "application/json" in content_type:
            body = json.loads(request.body.decode("utf-8"))
        else:
            body = request.POST.dict()

        title = (body.get("title") or "").strip()
        task_type = (body.get("task_type") or "").strip()
        thinking_model_id = body.get("thinking_model_id")
        vision_model_id = body.get("vision_model_id") or None
        urls_text = (body.get("urls") or "").strip()
        proxy_id = body.get("proxy_id") or None
        api_proxy_id = body.get("api_proxy_id") or None

        errors = {}
        if not title:
            errors["title"] = "标题不能为空"
        if task_type not in ("url_crawl", "file_upload", "text_input"):
            errors["task_type"] = "任务类型无效"
        if not thinking_model_id:
            errors["thinking_model_id"] = "请选择思考模型"

        thinking_model = models.AIModelConfig.objects.filter(id=thinking_model_id, model_type="thinking").first()
        if thinking_model_id and not thinking_model:
            errors["thinking_model_id"] = "思考模型不存在或类型不是思考模型"

        vision_model = None
        if vision_model_id:
            vision_model = models.AIModelConfig.objects.filter(id=vision_model_id, model_type="vision").first()
            if not vision_model:
                errors["vision_model_id"] = "识图模型不存在或类型不是识图模型"

        reference_text = (body.get("reference_text") or "").strip()
        if task_type == "url_crawl" and not urls_text:
            errors["urls"] = "至少输入一个 URL"
        if task_type == "text_input" and not reference_text:
            errors["reference_text"] = "参考资料文本不能为空"

        if errors:
            return JsonResponse({"status": False, "errors": errors}, status=400)

        urls = []
        if task_type == "url_crawl":
            urls = [u.strip() for u in urls_text.splitlines() if u.strip()]

        # 创建任务（plugin_language 在执行页面由用户选择）
        task = models.PoCGenerationTask.objects.create(
            title=title,
            task_type=task_type,
            thinking_model=thinking_model,
            vision_model=vision_model,
            urls=json.dumps(urls) if urls else "",
            proxy_id=int(proxy_id) if proxy_id else None,
            api_proxy_id=int(api_proxy_id) if api_proxy_id else None,
            task_description_prompt=TASK_DESCRIPTION_DEFAULT,
            reference_material_prompt="",
            custom_prompt="",
            status="pending",
        )

        # 创建资料目录
        material_dir = os.path.join(AI_POC_ROOT, f"task_{task.id}")
        os.makedirs(material_dir, exist_ok=True)
        task.material_dir = material_dir
        task.save()

        # 文件上传处理
        if task_type == "file_upload":
            upload_file = request.FILES.get("file") if hasattr(request, "FILES") else None
            if upload_file:
                if upload_file.size > MAX_UPLOAD_SIZE:
                    task.status = "failed"
                    task.crawl_status = "failed"
                    task.crawl_detail = json.dumps({"error": "文件超过 100MB 限制"})
                    task.save()
                    return JsonResponse({"status": False, "errors": {"file": "上传文件不能超过 100MB"}}, status=400)
                dest_path = os.path.join(material_dir, upload_file.name)
                with open(dest_path, "wb") as f:
                    for chunk in upload_file.chunks():
                        f.write(chunk)
                task.uploaded_file = dest_path
                task.save()

        # 异步启动资料提取（text_input 直接写入，不需要异步）
        if task_type == "text_input":
            task.reference_material_prompt = reference_text
            task.crawl_status = "success"
            task.status = "ready"
            task.save()
        else:
            task.status = "crawling"
            task.crawl_status = "processing"
            task.save()

            t = threading.Thread(target=_extract_material, args=(task,), daemon=True)
            t.start()

        return JsonResponse({"status": True, "data": {"id": task.id}})

    return JsonResponse({"status": False, "error": "method not allowed"}, status=405)


def api_task_detail(request, uid):
    """GET/POST/DELETE /api/v1/poc-gen-tasks/<id>"""
    task = models.PoCGenerationTask.objects.filter(id=uid).first()
    if not task:
        return JsonResponse({"status": False, "error": "任务不存在"}, status=404)

    if request.method == "GET":
        return JsonResponse({"status": True, "data": _task_to_dict(task)})

    if request.method == "POST":
        body = json.loads(request.body.decode("utf-8"))
        errors = {}

        # 任务元数据编辑（新建后允许修改的基础信息）
        if "title" in body:
            title = (body.get("title") or "").strip()
            if not title:
                errors["title"] = "标题不能为空"
            else:
                task.title = title

        if "thinking_model_id" in body:
            tid = body["thinking_model_id"]
            tm = models.AIModelConfig.objects.filter(id=tid, model_type="thinking").first() if tid else None
            if not tm:
                errors["thinking_model_id"] = "思考模型不存在或类型不是思考模型"
            else:
                task.thinking_model = tm

        if "vision_model_id" in body:
            vid = body["vision_model_id"]
            if vid:
                vm = models.AIModelConfig.objects.filter(id=vid, model_type="vision").first()
                if not vm:
                    errors["vision_model_id"] = "识图模型不存在或类型不是识图模型"
                else:
                    task.vision_model = vm
            else:
                task.vision_model = None

        if "proxy_id" in body:
            pid = body["proxy_id"]
            if pid:
                from app_cybersparker.models import ProxySetting
                if not ProxySetting.objects.filter(id=pid).exists():
                    errors["proxy_id"] = "代理不存在"
                else:
                    task.proxy_id = int(pid)
            else:
                task.proxy_id = None

        if "api_proxy_id" in body:
            apid = body["api_proxy_id"]
            if apid:
                from app_cybersparker.models import ProxySetting
                if not ProxySetting.objects.filter(id=apid).exists():
                    errors["api_proxy_id"] = "API代理不存在"
                else:
                    task.api_proxy_id = int(apid)
            else:
                task.api_proxy_id = None

        if "urls" in body and task.task_type == "url_crawl":
            urls_text = (body.get("urls") or "").strip()
            urls = [u.strip() for u in urls_text.splitlines() if u.strip()]
            if not urls:
                errors["urls"] = "至少输入一个 URL"
            else:
                task.urls = json.dumps(urls)

        if "reference_material_prompt" in body:
            task.reference_material_prompt = body["reference_material_prompt"] or ""

        # 插件类型切换：更新字段 + 自动加载对应提示词
        if "plugin_language" in body:
            lang = int(body["plugin_language"])
            if lang in (1, 2):
                task.plugin_language = lang
                task.plugin_spec_prompt = _load_plugin_spec(lang)

        # 更新提示词（执行页面用的四个文本框）
        for field in ("task_description_prompt", "plugin_spec_prompt", "reference_material_prompt", "custom_prompt"):
            if field in body:
                setattr(task, field, body[field] or "")

        if errors:
            return JsonResponse({"status": False, "errors": errors}, status=400)

        task.save()
        return JsonResponse({"status": True, "data": _task_to_dict(task)})

    if request.method == "DELETE":
        # 清理资料目录
        if task.material_dir and os.path.isdir(task.material_dir):
            shutil.rmtree(task.material_dir, ignore_errors=True)
        # 如果 crawling 状态需要 kill 子进程（无法直接 kill daemon thread，但线程会自然结束）
        task.delete()
        return JsonResponse({"status": True})

    return JsonResponse({"status": False, "error": "method not allowed"}, status=405)


def api_retry(request, uid):
    """POST /api/v1/poc-gen-tasks/<id>/retry — 清空资料目录并重新爬取（仅 url_crawl）"""
    if request.method != "POST":
        return JsonResponse({"status": False, "error": "method not allowed"}, status=405)

    task = models.PoCGenerationTask.objects.filter(id=uid).first()
    if not task:
        return JsonResponse({"status": False, "error": "任务不存在"}, status=404)

    if task.task_type != "url_crawl":
        return JsonResponse({"status": False, "error": "仅 URL 爬取类型的任务支持重试"}, status=400)

    if task.status == "generating":
        return JsonResponse({"status": False, "error": "任务正在生成中，无法重试"}, status=409)

    # 清空资料目录
    if task.material_dir and os.path.isdir(task.material_dir):
        shutil.rmtree(task.material_dir, ignore_errors=True)
    os.makedirs(task.material_dir, exist_ok=True)

    # 重置状态并重新提取资料
    task.crawl_status = "processing"
    task.crawl_detail = ""
    task.status = "crawling"
    task.reference_material_prompt = ""
    task.save()

    t = threading.Thread(target=_extract_material, args=(task,), daemon=True)
    t.start()

    return JsonResponse({"status": True, "data": _task_to_dict(task)})


def api_generate(request, uid):
    """POST /api/v1/poc-gen-tasks/<id>/generate — 触发 Celery 生成"""
    if request.method != "POST":
        return JsonResponse({"status": False, "error": "method not allowed"}, status=405)

    task = models.PoCGenerationTask.objects.filter(id=uid).first()
    if not task:
        return JsonResponse({"status": False, "error": "任务不存在"}, status=404)

    if task.status == "generating":
        return JsonResponse({"status": False, "error": "任务正在生成中，请等待"}, status=409)

    if task.status not in ("ready", "generated", "failed"):
        return JsonResponse({"status": False, "error": f"当前状态 {task.status} 不允许生成"}, status=400)

    if task.plugin_language is None:
        return JsonResponse({"status": False, "error": "请先在执行页面选择插件类型（Python/Nuclei）"}, status=400)

    task.status = "generating"
    task.save()

    from app_cybersparker.tasks import run_poc_generation
    celery_task = run_poc_generation.delay(task.id)

    task.celery_task_id = celery_task.id
    task.save(update_fields=["celery_task_id"])

    return JsonResponse({"status": True, "data": {"celery_task_id": celery_task.id}})


def api_preview_prompt(request, uid):
    """GET /api/v1/poc-gen-tasks/<id>/preview-prompt — 返回拼接后的完整提示词（和发送给AI的一致）"""
    if request.method != "GET":
        return JsonResponse({"status": False, "error": "method not allowed"}, status=405)

    task = models.PoCGenerationTask.objects.filter(id=uid).first()
    if not task:
        return JsonResponse({"status": False, "error": "任务不存在"}, status=404)

    from app_cybersparker.tasks import _build_poc_prompt
    user_message = _build_poc_prompt(task)
    system_message = getattr(settings, 'AI_POC_SYSTEM_PROMPT', '')
    full_prompt = f"[System]: {system_message}\n\n[User]:\n{user_message}"

    return JsonResponse({"status": True, "data": {"prompt": full_prompt}})


SEVERITY_VALID = {"critical", "high", "medium", "low", "info"}


def _save_ai_generated_poc(task: models.PoCGenerationTask) -> tuple[bool, str, int | None]:
    """保存生成的 PoC 到 EXP 插件库。返回 (成功, 错误信息, exp_id)"""
    metadata = {}
    if task.generated_metadata:
        try:
            metadata = json.loads(task.generated_metadata)
        except json.JSONDecodeError:
            return False, "元数据 JSON 解析失败", None

    title = (metadata.get("title") or "").strip()
    if not title:
        return False, "缺少插件标题（title），请先在元数据中补充", None

    severity = (metadata.get("severity") or "").strip().lower()
    if severity not in SEVERITY_VALID:
        return False, f"severity 值无效：{severity}，合法值为 {', '.join(SEVERITY_VALID)}", None

    poc_type = int(metadata.get("type", 12))
    if poc_type < 1 or poc_type > 12:
        return False, f"type 值无效：{poc_type}，合法范围为 1-12", None

    poc_content = task.generated_poc_content or ""
    if not poc_content.strip():
        return False, "生成的 PoC 内容为空", None

    if task.plugin_language is None:
        return False, "插件类型未设置，请先在执行页面选择", None

    # SHA256 去重
    sha256 = hashlib.sha256(poc_content.encode("utf-8")).hexdigest()
    if models.EXP.objects.filter(poc_content__icontains=poc_content[:200]).exists():
        # 简单检查：查看是否有非常相似的内容
        # 更严格的检查是 SHA256 比较所有已有 poc_content
        existing = models.EXP.objects.all()
        for exp in existing:
            if exp.poc_content and hashlib.sha256(exp.poc_content.encode("utf-8")).hexdigest() == sha256:
                return False, "该 PoC 已存在于插件库中（SHA256 匹配）", None

    # 写入文件
    ext = ".py" if task.plugin_language == 1 else ".yaml"
    filename = f"{sha256}{ext}"
    filepath = os.path.join(BASE_DIR, "EXP_plugin", filename)

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(poc_content)

    # 处理 title 唯一约束冲突
    final_title = title
    if models.EXP.objects.filter(title=title).exists():
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
        final_title = f"{title}-{suffix}"

    # 解析 ctime
    ctime_str = (metadata.get("ctime") or "").strip()
    exp_time = None
    if ctime_str:
        try:
            exp_time = dt_datetime.strptime(ctime_str, "%Y/%m/%d").date()
        except ValueError:
            pass

    # 创建 EXP 记录
    try:
        with open(filepath, "rb") as f:
            file_content = ContentFile(f.read(), name=filename)
        exp = models.EXP.objects.create(
            title=final_title,
            CVE=(metadata.get("cve") or "").strip(),
            severity=severity,
            Type=poc_type,
            plugin_language=task.plugin_language,
            poc=file_content,
            poc_content=poc_content,
            poc_type=2,
            use=1,
            time=exp_time,
            update_time=timezone.now(),
        )
    except Exception as e:
        # 清理已写入的文件
        if os.path.isfile(filepath):
            os.unlink(filepath)
        return False, f"创建 EXP 记录失败：{e}", None

    # 创建 cveExtensions
    ext_str = (metadata.get("extentions") or "1").strip()
    for ext_item in ext_str.split(","):
        ext_item = ext_item.strip()
        if ext_item.isdigit():
            try:
                models.cveExtensions.objects.create(CVE=exp, function=int(ext_item))
            except Exception:
                pass

    # 创建 tags
    tags_str = (metadata.get("tags") or "").strip()
    if tags_str:
        tag_names = [t.strip() for t in tags_str.split(",") if t.strip()]
        tag_objs = []
        for tname in tag_names:
            tag_obj, _ = models.Tag.objects.get_or_create(name=tname)
            tag_objs.append(tag_obj)
        if tag_objs:
            exp.tags.set(tag_objs)

    # 更新任务
    task.saved_to_exp = True
    task.saved_exp_id = exp.id
    task.save()

    return True, "", exp.id


def api_save_to_exp(request, uid):
    """POST /api/v1/poc-gen-tasks/<id>/save-to-exp — 保存到 EXP 插件库"""
    if request.method != "POST":
        return JsonResponse({"status": False, "error": "method not allowed"}, status=405)

    task = models.PoCGenerationTask.objects.filter(id=uid).first()
    if not task:
        return JsonResponse({"status": False, "error": "任务不存在"}, status=404)

    if task.saved_to_exp:
        return JsonResponse({"status": False, "error": "已保存到插件库，不可重复操作"}, status=409)

    if task.status != "generated":
        return JsonResponse({"status": False, "error": "请先生成 PoC 再保存"}, status=400)

    # 如果请求中有 title 字段，更新 metadata
    body = json.loads(request.body.decode("utf-8") or "{}")
    if body.get("title"):
        try:
            metadata = json.loads(task.generated_metadata or "{}")
        except json.JSONDecodeError:
            metadata = {}
        metadata["title"] = body["title"].strip()
        task.generated_metadata = json.dumps(metadata, ensure_ascii=False)
        task.save()

    success, error_msg, exp_id = _save_ai_generated_poc(task)
    if not success:
        return JsonResponse({"status": False, "error": error_msg}, status=400)

    return JsonResponse({"status": True, "data": {"exp_id": exp_id}})
