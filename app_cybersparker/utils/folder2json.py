#!/usr/bin/env python3
"""
将文件夹中的文件转换为 JSON 字符串，供非多模态 AI 模型使用。

功能：
1. 文本文件（源码/配置/文档等）→ 直接读取内容
2. 二进制文件 → content 标记为 "can not extract for now"
3. Markdown 文件 → 提取图片链接，下载远程图片，用 AI 转文字描述后插入原文

用法：
    python folder2json.py /path/to/folder -o output.json
    python folder2json.py /path/to/folder --download-dir ./images --api-key sk-xxx
"""

import os
import sys
import json
import re
import hashlib
import mimetypes
import argparse
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from dashscope import MultiModalConversation
import dashscope

# ============================================================
# 配置
# ============================================================

# dashscope API 地址
dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

# 图片转文字用的模型
VISION_MODEL = "qwen3-vl-flash"

# 图片转文字的提示词
IMAGE_PROMPT = (
    "识别图片，并把你对整张图片的理解（不超过800个字）、"
    "每个识别到的部位的描述和对应内容输出为json格式，"
    "若图中有http请求、http响应、代码、命令行命令，需要完整记录不能省略"
)

# 已知的二进制文件后缀（用于快速判断）
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".tif",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv",
    ".o", ".a", ".class", ".pyc", ".pyo",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".ipynb", ".db", ".sqlite", ".sqlite3",
    ".iso", ".img", ".dmg", ".vmdk",
    ".psd", ".ai", ".sketch",
    ".whl", ".egg",
}

# 明确是文本类型的后缀（即使 mimetypes 判断不准确时优先使用）
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".org",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".c", ".cpp", ".cc", ".cxx",
    ".h", ".hpp", ".cs", ".rb", ".php", ".rs", ".swift", ".kt", ".kts",
    ".scala", ".clj", ".cljs", ".lua", ".r", ".m", ".mm",
    ".json", ".yaml", ".yml", ".xml", ".toml", ".ini", ".cfg", ".conf",
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".sh", ".bash", ".zsh", ".fish", ".bat", ".ps1",
    ".sql", ".graphql", ".proto",
    ".dockerfile", ".makefile", ".cmake",
    ".vue", ".svelte",
    ".env", ".gitignore", ".editorconfig",
}

# qwen3-vl-flash 模型对图片的限制
MAX_IMAGE_DIMENSION = 4096   # 长边不超过 4096px
MAX_IMAGE_FILE_SIZE = 10 * 1024 * 1024  # 文件大小不超过 10MB

# 读取文件时检查的头部字节数
HEAD_CHECK_BYTES = 8192


# ============================================================
# 文件类型判断
# ============================================================

def is_text_file(filepath: str) -> bool:
    """判断文件是否为文本类型。综合后缀 + 文件头内容判断。"""
    ext = Path(filepath).suffix.lower()

    # 1. 后缀明确是二进制 → 直接否
    if ext in BINARY_EXTENSIONS:
        return False

    # 2. 后缀明确是文本 → 直接是
    if ext in TEXT_EXTENSIONS:
        return True

    # 3. 无后缀或未知后缀 → 检查文件头
    try:
        with open(filepath, "rb") as f:
            head = f.read(HEAD_CHECK_BYTES)
    except (IOError, OSError):
        return False

    # 空文件视为文本
    if len(head) == 0:
        return True

    # 包含 null 字节 → 二进制
    if b"\x00" in head:
        return False

    # 用 mimetypes 辅助判断
    mime_type = mimetypes.guess_type(filepath)[0]
    if mime_type:
        if mime_type.startswith("text/") or mime_type in (
            "application/json",
            "application/xml",
            "application/javascript",
            "application/x-yaml",
        ):
            return True
        # image/audio/video/application 中非明确的都再检查一下
        if mime_type.startswith(("image/", "audio/", "video/", "font/")):
            return False

    # 默认：无 null 字节就视为文本
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        pass

    # UTF-8 解不了但无 null 的，可能是其他编码，也当作文本
    try:
        head.decode("latin-1")
        return True
    except UnicodeDecodeError:
        return False


# ============================================================
# Markdown 图片处理
# ============================================================

# 匹配 markdown 图片语法: ![alt](url)  — [^)]* 允许空 URL，兜底处理
MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")


def extract_image_urls(md_content: str) -> list[tuple[str, str, str]]:
    """
    从 markdown 内容中提取所有图片。
    返回 [(完整匹配文本, alt文本, url), ...]
    """
    return [(m.group(0), m.group(1), m.group(2)) for m in MD_IMAGE_RE.finditer(md_content)]


def is_remote_url(url: str) -> bool:
    """判断是否为远程 URL（http/https）。"""
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https")


def download_image(url: str, save_dir: str) -> str | None:
    """
    下载远程图片到本地目录。
    返回本地文件路径，失败返回 None。
    """
    os.makedirs(save_dir, exist_ok=True)

    try:
        resp = requests.get(url, timeout=30, stream=True)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [WARN] 下载图片失败: {url} — {e}", file=sys.stderr)
        return None

    # 用 URL 的 hash 作为文件名，保留原始后缀
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    content_type = resp.headers.get("content-type", "")
    ext = ".png"
    if "jpeg" in content_type or "jpg" in content_type:
        ext = ".jpg"
    elif "gif" in content_type:
        ext = ".gif"
    elif "webp" in content_type:
        ext = ".webp"
    elif "svg" in content_type:
        ext = ".svg"
    elif "bmp" in content_type:
        ext = ".bmp"

    filename = f"{url_hash}{ext}"
    filepath = os.path.join(save_dir, filename)

    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    return filepath


def preprocess_image(image_path: str, work_dir: str) -> str:
    """
    预处理图片以符合 qwen3-vl-flash 的限制：
    - 长边 > 4096px → 等比缩放到 4096px
    - 文件 > 10MB → 压缩/降质直到满足

    处理后的图片保存到 work_dir，返回新路径。若无需处理或处理失败，返回原路径。
    """
    try:
        from PIL import Image
    except ImportError:
        print("  [WARN] Pillow 未安装，跳过图片预处理", file=sys.stderr)
        return image_path

    file_size = os.path.getsize(image_path)
    if file_size == 0:
        return image_path

    try:
        img = Image.open(image_path)
    except Exception:
        print(f"  [WARN] 无法打开图片: {image_path}", file=sys.stderr)
        return image_path

    width, height = img.size
    longest = max(width, height)
    needs_resize = longest > MAX_IMAGE_DIMENSION
    needs_compress = file_size > MAX_IMAGE_FILE_SIZE

    if not needs_resize and not needs_compress:
        img.close()
        return image_path

    print(f"  [PREPROCESS] {os.path.basename(image_path)} "
          f"({width}x{height}, {file_size / 1024 / 1024:.1f}MB)", file=sys.stderr)

    # 步骤 1：缩放尺寸
    if needs_resize:
        ratio = MAX_IMAGE_DIMENSION / longest
        new_w = int(width * ratio)
        new_h = int(height * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        print(f"    缩放: {width}x{height} → {new_w}x{new_h}", file=sys.stderr)
        width, height = new_w, new_h

    # 步骤 2：保存并检查文件大小
    os.makedirs(work_dir, exist_ok=True)
    base_name = Path(image_path).stem
    ext = Path(image_path).suffix.lower()

    if ext in (".jpg", ".jpeg"):
        save_ext = ".jpg"
    elif ext == ".png":
        save_ext = ".png"
    elif ext == ".webp":
        save_ext = ".webp"
    else:
        # 其他格式统一转 PNG（无损）
        save_ext = ".png"
        img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")

    out_path = os.path.join(work_dir, f"{base_name}_processed{save_ext}")

    if save_ext == ".jpg":
        # JPEG：逐步降质直到满足大小要求
        for quality in (85, 70, 55, 40):
            img.save(out_path, format="JPEG", quality=quality, optimize=True)
            if os.path.getsize(out_path) <= MAX_IMAGE_FILE_SIZE:
                break
    elif save_ext == ".png":
        img.save(out_path, format="PNG", optimize=True)
        # PNG 优化后仍超限 → 转 JPEG
        if os.path.getsize(out_path) > MAX_IMAGE_FILE_SIZE:
            if img.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                img = background
            else:
                img = img.convert("RGB")
            for quality in (85, 70, 55, 40):
                img.save(out_path, format="JPEG", quality=quality, optimize=True)
                if os.path.getsize(out_path) <= MAX_IMAGE_FILE_SIZE:
                    break
    else:
        img.save(out_path, optimize=True)

    img.close()
    print(f"    最终: {os.path.getsize(out_path) / 1024:.1f}KB", file=sys.stderr)

    return out_path if os.path.getsize(out_path) <= MAX_IMAGE_FILE_SIZE else image_path


def image_to_text(image_path: str, api_key: str, max_retries: int = 3) -> str | None:
    """
    调用 dashscope 多模态 API 将图片转为文字描述。
    参考 qwen-img2text-localfile.py 的调用方式。
    """
    abs_path = os.path.abspath(image_path)
    image_url = f"file://{abs_path}"

    messages = [
        {
            "role": "user",
            "content": [
                {"image": image_url},
                {"text": IMAGE_PROMPT},
            ],
        }
    ]

    for attempt in range(max_retries):
        try:
            response = MultiModalConversation.call(
                api_key=api_key,
                model=VISION_MODEL,
                messages=messages,
            )
            text = response.output.choices[0].message.content[0]["text"]
            return text
        except Exception as e:
            print(f"  [WARN] 图片转文字失败 (第{attempt+1}次): {image_path} — {e}", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                return f"[图片解析失败: {e}]"


def resolve_image_path(image_url: str, base_dir: str, download_dir: str, base_url: str = "") -> str | None:
    """
    解析图片路径：远程 URL → 下载；域名相对路径 → 补全 scheme 后下载；本地路径 → 拼接。
    返回本地文件路径，失败返回 None。
    """
    if is_remote_url(image_url):
        return download_image(image_url, download_dir)
    # 域名相对路径（如 /Threekiii/.../images/xxx.png）→ 补全 scheme
    if base_url and image_url.startswith("/"):
        from urllib.parse import urljoin
        resolved = urljoin(base_url, image_url)
        if is_remote_url(resolved):
            return download_image(resolved, download_dir)
    # 本地相对路径，拼上 markdown 所在目录
    local_path = os.path.join(base_dir, image_url)
    if os.path.isfile(local_path):
        return local_path
    print(f"  [WARN] 本地图片不存在: {local_path}", file=sys.stderr)
    return None


def process_markdown(md_path: str, download_dir: str, api_key: str, base_url: str = "") -> str:
    """
    处理单个 Markdown 文件：
    1. 提取图片链接
    2. 下载远程图片 / 定位本地图片
    3. 调用 AI 转文字（仅当 api_key 非空且图片下载成功）
    4. 将描述插入到图片下方

    返回处理后的 markdown 内容。
    """
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    images = extract_image_urls(content)
    if not images:
        return content

    print(f"  [MD] {md_path} 发现 {len(images)} 张图片")

    base_dir = os.path.dirname(os.path.abspath(md_path))
    replacements = {}  # 原始匹配文本 → 替换文本

    for i, (full_match, _alt_text, url) in enumerate(images, 1):
        print(f"    [{i}/{len(images)}] 处理图片: {url}")

        # 跳过已经是 data URI 的图片
        if url.startswith("data:"):
            replacements[full_match] = f"{full_match}\n\n> [图片描述]: (内嵌 data URI，无法解析)"
            continue

        local_img = resolve_image_path(url, base_dir, download_dir, base_url)
        if not local_img:
            replacements[full_match] = f"{full_match}\n\n> [图片描述]: (图片获取失败)"
            continue

        # 更新 markdown 中的图片引用为本地相对路径
        rel_path = os.path.relpath(local_img, os.path.dirname(md_path))
        local_ref = full_match.replace(url, rel_path)

        if api_key:
            processed_img = preprocess_image(local_img, download_dir)
            desc = image_to_text(processed_img, api_key)
            if desc:
                desc_oneline = desc.replace("\n", " ")
                replacements[full_match] = f"{local_ref}\n\n> [图片描述]: {desc_oneline}"
            else:
                replacements[full_match] = f"{local_ref}\n\n> [图片描述]: (解析失败)"
        else:
            replacements[full_match] = local_ref

    # 按匹配文本长度降序替换
    for match_text in sorted(replacements.keys(), key=len, reverse=True):
        content = content.replace(match_text, replacements[match_text])

    return content


# ============================================================
# 主流程
# ============================================================

def folder_to_json(
    input_dir: str,
    download_dir: str = "./downloaded_images",
    api_key: str | None = None,
) -> dict:
    """
    遍历文件夹，将所有文件转换为 JSON 结构。
    """
    input_dir = os.path.abspath(input_dir)
    if not os.path.isdir(input_dir):
        raise ValueError(f"目录不存在: {input_dir}")

    api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("[WARN] 未设置 DASHSCOPE_API_KEY，Markdown 图片将跳过 AI 解析", file=sys.stderr)

    files_output = []
    # 统计信息
    text_count = 0
    binary_count = 0
    md_count = 0

    for root, dirs, filenames in os.walk(input_dir):
        # 跳过图片下载目录（避免递归处理下载的图片）
        dirs[:] = [d for d in dirs if os.path.abspath(os.path.join(root, d)) != os.path.abspath(download_dir)]

        for filename in sorted(filenames):
            filepath = os.path.join(root, filename)
            # 跳过大文件和无法读的文件
            if not os.path.isfile(filepath):
                continue

            rel_path = os.path.relpath(filepath, input_dir)

            print(f"[SCAN] {rel_path}", end="", file=sys.stderr)

            if not is_text_file(filepath):
                binary_count += 1
                print(" → 二进制，跳过", file=sys.stderr)
                files_output.append({
                    "path": rel_path,
                    "content": "can not extract for now",
                })
                continue

            print(" → 文本", file=sys.stderr)
            text_count += 1

            ext = Path(filepath).suffix.lower()
            content = None

            # Markdown 特殊处理
            if ext in (".md", ".markdown") and api_key:
                md_count += 1
                content = process_markdown(filepath, download_dir, api_key)
            else:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                except UnicodeDecodeError:
                    # 编码问题，尝试 latin-1
                    try:
                        with open(filepath, "r", encoding="latin-1") as f:
                            content = f.read()
                    except Exception:
                        content = "can not extract for now"
                except Exception:
                    content = "can not extract for now"

            files_output.append({
                "path": rel_path,
                "content": content,
            })

    print(f"\n[DONE] 文本文件: {text_count}, 二进制文件: {binary_count}, Markdown(含图片处理): {md_count}",
          file=sys.stderr)

    return {"files": files_output}


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="将文件夹转换为 JSON 字符串，含 Markdown 图片 AI 解析",
    )
    parser.add_argument("input_dir", help="要转换的文件夹路径")
    parser.add_argument("-o", "--output", default=None, help="输出 JSON 文件路径（默认自动保存到目标文件夹下）")
    parser.add_argument("--download-dir", default="./downloaded_images", help="远程图片下载目录（默认 ./downloaded_images）")
    parser.add_argument("--api-key", default=None, help="DashScope API Key（也可通过环境变量 DASHSCOPE_API_KEY 设置）")
    parser.add_argument("--indent", type=int, default=2, help="JSON 缩进空格数（默认 2）")
    parser.add_argument("--no-md-images", action="store_true", help="跳过 Markdown 图片解析（只做纯文本转换）")

    args = parser.parse_args()

    api_key = args.api_key or os.getenv("DASHSCOPE_API_KEY")
    if args.no_md_images:
        api_key = None

    if not api_key:
        print("[INFO] 未提供 API Key，Markdown 中的图片将不会被 AI 解析", file=sys.stderr)

    result = folder_to_json(
        input_dir=args.input_dir,
        download_dir=args.download_dir,
        api_key=api_key,
    )

    json_str = json.dumps(result, ensure_ascii=False, indent=args.indent)

    if args.output:
        output_path = args.output
    else:
        output_path = os.path.join(os.path.abspath(args.input_dir), "folder2json_output.json")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(json_str)
    print(f"[OUTPUT] → {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
