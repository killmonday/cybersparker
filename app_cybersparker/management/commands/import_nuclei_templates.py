import hashlib
import os
import re
import shutil
import subprocess
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from app_cybersparker import models
from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import (
    find_unsupported_nuclei_protocols,
)

# 非产品标签（用于 B3 关键词过滤）
SKIP_TAGS = {
    "cve", "cve-2024", "cve-2025", "cve-2026", "rce", "sqli", "xss", "lfi", "rfi",
    "ssrf", "idor", "csrf", "oast", "fuzz", "dast", "detect", "detection",
    "exposure", "misconfig", "misconfiguration", "unauth", "auth-bypass",
    "file-upload", "file-inclusion", "path-traversal", "directory-listing",
    "info-leak", "information-disclosure", "debug", "default-login",
    "brute-force", "dos", "panic", "traversal", "injection", "overflow",
    "generic", "tech", "token-spray", "credential-stuffing",
    "wordpress-plugin", "wp-plugin",
    "vuln", "vkev", "kev", "intrusive", "passive", "edb", "packetstorm",
    "wpscan", "discovery",
    "cve2010", "cve2011", "cve2012", "cve2013", "cve2014", "cve2015",
    "cve2016", "cve2017", "cve2018", "cve2019", "cve2020", "cve2021",
    "cve2022", "cve2023", "cve2024", "cve2025", "cve2026",
    "fileupload", "config", "php", "asp", "aspx", "jsp",
    "java", "python", "ruby", "perl", "shell", "bash", "sh",
    "network", "tcp", "udp", "http", "https", "dns", "ssl", "tls",
    "proxy", "reverse-proxy", "load-balancer", "firewall", "waf",
    "api", "rest", "soap", "graphql", "websocket",
    "html", "css", "javascript", "typescript", "js", "ts",
    "json", "xml", "yaml", "csv",
    "backup", "backup-file", "backup-files",
    "banner", "fingerprint", "login", "logout", "signin", "signup",
    "admin", "administrator", "console",
    "cnvd", "cnnvd", "cnvd-c", "cnnvd-c",
    "cloud", "devops",
    "wp", "oa",  # 太短，噪音大
    # B3 质量治理追加：太泛的词
    "enable", "enabled", "disable", "disabled", "health", "monitor",
    "audit", "public", "private", "access", "check", "service",
    "security", "manager", "management", "server", "client", "application",
    "report", "status", "verify", "version", "portal", "platform",
}

CVE_RE = re.compile(r'CVE-\d{4}-\d{4,}', re.IGNORECASE)
B1_FUZZY_THRESHOLD = 0.75
B3_FUZZY_THRESHOLD = 0.70
BATCH_SIZE = 100


def _extract_cve(value):
    return [m.upper() for m in CVE_RE.findall(str(value or ""))]


def _exact_match_product(keyword, fp_names_lower):
    kw = keyword.lower().strip()
    for idx, name in enumerate(fp_names_lower):
        if kw == name:
            return idx
    return None


def _contain_match_product(keyword, fp_names_lower, max_results=3):
    kw = keyword.lower().strip()
    if len(kw) < 5:
        return []
    matches = []
    for idx, name in enumerate(fp_names_lower):
        if kw in name:
            # "jira" in "Atlassian Jira"
            matches.append((idx, len(kw) / len(name)))
        elif len(name) >= 5 and name in kw:
            # "wordpress" in "wordpress admin count column"
            # 要求指纹名 >= 5 字，防止 "ess" 匹配 "access" 中的子串
            matches.append((idx, len(name) / len(kw)))
    matches.sort(key=lambda x: -x[1])
    return [m[0] for m in matches[:max_results]]


def _fuzzy_match_product(keyword, fp_names_lower, threshold):
    kw = keyword.lower().strip()
    best_score = 0
    best_idx = None
    for idx, name in enumerate(fp_names_lower):
        score = SequenceMatcher(None, kw, name).ratio()
        if kw in name or name in kw:
            score = max(score, 0.85)
        if score > best_score:
            best_score = score
            best_idx = idx
    if best_score >= threshold and best_idx is not None:
        return best_idx, best_score
    return None, 0


def extract_keywords(tags, name, description=""):
    _ = description  # 不再从描述中提取关键词（噪音大）
    tags_raw = str(tags or "")
    name_raw = str(name or "")
    keywords = set()

    for tag in tags_raw.split(","):
        tag = tag.strip().lower().replace("-", " ").replace("_", " ")
        if not tag or tag in SKIP_TAGS or len(tag) < 3 or tag.isdigit():
            continue
        keywords.add(tag)

    name_parts = name_raw.split(" - ")
    for part in name_parts[:2]:
        part = part.strip().lower()
        # 太长的名字段通常是完整句子，不提取
        if 3 <= len(part) <= 30 and part not in SKIP_TAGS:
            keywords.add(part)

    # 不提取描述文本（太长、噪音大）

    return keywords


class Command(BaseCommand):
    help = '从 nuclei-templates 仓库批量导入 YAML POC 模板并自动匹配指纹。'

    def add_arguments(self, parser):
        parser.add_argument('--source', default='/tmp/nuclei-templates', help='模板源目录')
        parser.add_argument('--limit', type=int, default=0, help='限制导入数量（0=全部）')
        parser.add_argument('--dry-run', action='store_true', help='只分析不写入')
        parser.add_argument('--skip-matching', action='store_true', help='跳过指纹匹配')
        parser.add_argument('--sync-mode', action='store_true', help='只导入新模板（按内容 SHA256 去重）')
        parser.add_argument('--no-pull', action='store_true', help='跳过 git pull')

    def handle(self, **options):
        source = options['source']
        limit = options['limit']
        dry_run = options['dry_run']
        skip_matching = options['skip_matching']
        sync_mode = options['sync_mode']

        if not os.path.isdir(source):
            self.stderr.write(f"源目录不存在: {source}")
            return

        # —— git pull 更新模板仓库 ——
        if not options['no_pull']:
            git_dir = os.path.join(source, '.git')
            if os.path.isdir(git_dir):
                self.stdout.write(f"[0] git pull {source} ...")
                try:
                    result = subprocess.run(
                        ['git', '-C', source, 'pull', '--ff-only'],
                        capture_output=True, text=True, timeout=120,
                    )
                    if result.returncode == 0:
                        self.stdout.write(f"    {result.stdout.strip() or 'Already up to date.'}")
                    else:
                        self.stderr.write(f"    git pull 失败: {result.stderr.strip()}")
                except Exception as e:
                    self.stderr.write(f"    git pull 异常: {e}")
            else:
                self.stdout.write(f"[0] {source} 不是 git 仓库，跳过 pull")

        # —— 加载指纹库 ——
        self.stdout.write("[1] 加载指纹库...")
        fp_records = list(models.fingerPrint.objects.values_list('id', 'product'))
        fp_names_lower = [r[1].lower() for r in fp_records]
        self.stdout.write(f"    指纹总数: {len(fp_records)}")

        # —— 加载已有 CVE→指纹绑定 ——
        cve_to_fps = defaultdict(set)
        if not skip_matching:
            for rel in models.exp_relate_fingerprint.objects.select_related(
                'EXP_id', 'fingerprint_id'
            ).all():
                cve = (rel.EXP_id.CVE or "").strip().upper()
                if cve and cve != "CVE-0000-0000" and "CVE-" in cve:
                    cve_to_fps[cve].add(rel.fingerprint_id.product)

        # —— 加载已导入模板的 SHA256（去重用） ——
        existing_digests = set()
        if sync_mode:
            for poc_content in models.EXP.objects.filter(
                plugin_language=2
            ).exclude(poc_content__isnull=True).values_list('poc_content', flat=True):
                existing_digests.add(poc_content)

        # —— 准备 EXP_plugin 目录 ——
        plugin_dir = os.path.join(settings.BASE_DIR, 'EXP_plugin')
        os.makedirs(plugin_dir, exist_ok=True)

        # —— 遍历 YAML ——
        all_yamls = sorted(Path(source).rglob("*.yaml"))
        # 排除 workflows 和 helpers
        all_yamls = [
            p for p in all_yamls
            if "workflows" not in str(p) and "helpers" not in str(p)
        ]
        if limit > 0:
            all_yamls = all_yamls[:limit]

        self.stdout.write(f"[2] 待处理模板: {len(all_yamls)}")

        stats = {
            "total": 0, "skipped": 0, "unsupported_skipped": 0, "parse_failed": 0,
            "created": 0, "failed": 0,
            "b1_matched": 0, "b2_matched": 0, "b3_matched": 0,
            "no_match": 0, "info_skipped": 0,
        }
        unsupported_protocol_counts = defaultdict(int)
        batch = []
        match_batch = []  # (exp_id, fp_id, strategy, confidence)
        failed_files = []

        for yaml_path in all_yamls:
            stats["total"] += 1
            rel_path = str(yaml_path.relative_to(source))

            # 读 YAML
            try:
                with open(yaml_path, "rb") as f:
                    raw = f.read()
            except Exception:
                stats["parse_failed"] += 1
                failed_files.append((rel_path, "read error"))
                continue

            digest = hashlib.sha256(raw).hexdigest()

            if sync_mode and digest in existing_digests:
                stats["skipped"] += 1
                continue

            # 解析
            try:
                import yaml
                doc = yaml.safe_load(raw) or {}
            except Exception:
                stats["parse_failed"] += 1
                failed_files.append((rel_path, "yaml parse error"))
                continue

            info = doc.get("info") or {}
            if not info:
                stats["parse_failed"] += 1
                failed_files.append((rel_path, "no info section"))
                continue

            unsupported_protocols = find_unsupported_nuclei_protocols(doc)
            if unsupported_protocols:
                stats["unsupported_skipped"] += 1
                for protocol in unsupported_protocols:
                    unsupported_protocol_counts[protocol] += 1
                continue

            # 构建 EXP 字段
            template_name = str(info.get("name") or yaml_path.stem)

            classification = info.get("classification") or {}
            metadata = info.get("metadata") or {}
            tags = info.get("tags") or ""
            severity = str(info.get("severity") or "")[:10]
            description = info.get("description") or ""

            cve_ids = []
            for field in [
                classification.get("cve-id"),
                metadata.get("cve"),
                info.get("cve"),
            ]:
                cve_ids.extend(_extract_cve(str(field or "")))
            cve_str = ",".join(sorted(set(cve_ids))) if cve_ids else ""

            # title: [模板名]{hash8}，hash 用于防碰撞
            title_base = f"[{template_name}]"
            if len(title_base) > 118:
                title_base = title_base[:114] + "..."
            title = f"{title_base}{{{digest[:8]}}}"
            # 最终截断保护
            if len(title) > 128:
                title = title[:124] + "..."

            # 目标文件路径（加 hash 防重名）
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', yaml_path.name)
            base, ext = os.path.splitext(safe_name)
            dest_name = f"{base}_{digest[:8]}{ext}"
            dest_path = os.path.join(plugin_dir, dest_name)

            if dry_run:
                exp = stats["created"]  # dry-run 用整数标识，仅用于匹配统计
                stats["created"] += 1
            else:
                # 复制文件 + 创建 EXP 记录
                try:
                    shutil.copy2(yaml_path, dest_path)

                    exp = models.EXP(
                        title=title,
                        CVE=cve_str[:128] if cve_str else "",
                        Type=12,  # other
                        plugin_language=2,  # nuclei_yaml
                        use=1,
                        poc_type=1,
                        poc=f"EXP_plugin/{dest_name}",
                        poc_content=digest,
                        severity=severity,
                        time=date.today(),
                        update_time=timezone.now(),
                    )
                    exp._raw_tags = str(tags or "")  # 暂存，_flush_batch 处理后 bulk_create 回填 PK
                    batch.append(exp)
                    stats["created"] += 1
                except Exception:
                    stats["failed"] += 1
                    failed_files.append((rel_path, "create error"))
                    continue

            # —— 指纹匹配 ——
            if skip_matching:
                continue

            # info 级别插件不做指纹绑定
            if severity == "info":
                stats["info_skipped"] += 1
                continue

            matched = False
            meta_product = (
                metadata.get("product")
                or metadata.get("vendor")
                or metadata.get("service")
            )

            # 本模板已匹配的指纹（去重用）
            matched_fp_ids = set()

            # B1: metadata.product 匹配
            if meta_product:
                mp = str(meta_product).strip()
                idx = _exact_match_product(mp, fp_names_lower)
                if idx is not None:
                    fp_id = fp_records[idx][0]
                    if fp_id not in matched_fp_ids:
                        match_batch.append((exp, fp_id, "B1-exact", "high"))
                        stats["b1_matched"] += 1
                        matched_fp_ids.add(fp_id)
                        matched = True
                else:
                    for cm_idx in _contain_match_product(mp, fp_names_lower, max_results=5):
                        fp_id = fp_records[cm_idx][0]
                        if fp_id not in matched_fp_ids:
                            match_batch.append((exp, fp_id, "B1-contain", "high"))
                            stats["b1_matched"] += 1
                            matched_fp_ids.add(fp_id)
                            matched = True
                    if not matched:
                        best_idx, _ = _fuzzy_match_product(
                            mp, fp_names_lower, B1_FUZZY_THRESHOLD
                        )
                        if best_idx is not None:
                            fp_id = fp_records[best_idx][0]
                            if fp_id not in matched_fp_ids:
                                match_batch.append((exp, fp_id, "B1-fuzzy", "medium"))
                                stats["b1_matched"] += 1
                                matched_fp_ids.add(fp_id)
                                matched = True

            # B2: CVE 继承
            for cve_id in cve_ids:
                if cve_id in cve_to_fps:
                    for fp_product in cve_to_fps[cve_id]:
                        for fp_id, fp_name in fp_records:
                            if fp_name == fp_product and fp_id not in matched_fp_ids:
                                match_batch.append((exp, fp_id, "B2-cve-inherit", "high"))
                                stats["b2_matched"] += 1
                                matched_fp_ids.add(fp_id)
                                matched = True

            # B3: tags + name 关键词
            keywords = extract_keywords(tags, template_name, description)
            for kw in keywords:
                if len(kw) < 4:
                    continue
                idx = _exact_match_product(kw, fp_names_lower)
                if idx is not None and fp_records[idx][0] not in matched_fp_ids:
                    fp_id = fp_records[idx][0]
                    match_batch.append((exp, fp_id, "B3-exact", "medium"))
                    stats["b3_matched"] += 1
                    matched_fp_ids.add(fp_id)
                    matched = True
                    continue
                for cm_idx in _contain_match_product(kw, fp_names_lower):
                    if fp_records[cm_idx][0] not in matched_fp_ids:
                        fp_id = fp_records[cm_idx][0]
                        match_batch.append((exp, fp_id, "B3-contain", "medium"))
                        stats["b3_matched"] += 1
                        matched_fp_ids.add(fp_id)
                        matched = True

            if not matched:
                stats["no_match"] += 1

            # 批量写入
            if len(batch) >= BATCH_SIZE:
                self._flush_batch(batch, match_batch)
                batch = []
                match_batch = []

            if stats["total"] % 500 == 0:
                self.stdout.write(
                    f"    进度: {stats['total']}/{len(all_yamls)} "
                    f"(创建 {stats['created']}, B1 {stats['b1_matched']}, "
                    f"B2 {stats['b2_matched']}, B3 {stats['b3_matched']}, "
                    f"未匹配 {stats['no_match']})"
                )

        # 写入剩余批次
        if batch:
            self._flush_batch(batch, match_batch)

        # —— 输出统计 ——
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write("导入完成" if not dry_run else "DRY RUN — 未实际写入")
        self.stdout.write("=" * 60)
        self.stdout.write(f"模板总数:     {stats['total']}")
        self.stdout.write(f"跳过(已存在): {stats['skipped']}")
        self.stdout.write(f"跳过(不支持协议): {stats['unsupported_skipped']}")
        self.stdout.write(f"解析失败:     {stats['parse_failed']}")
        self.stdout.write(f"成功创建:     {stats['created']}")
        self.stdout.write(f"创建失败:     {stats['failed']}")
        self.stdout.write(f"")
        self.stdout.write(f"B1 (metadata.product):  {stats['b1_matched']}")
        self.stdout.write(f"B2 (CVE 继承):         {stats['b2_matched']}")
        self.stdout.write(f"B3 (tags/name 关键词): {stats['b3_matched']}")
        self.stdout.write(f"跳过(info级别):        {stats['info_skipped']}")
        self.stdout.write(f"未匹配:                {stats['no_match']}")

        if stats["created"] > 0:
            eligible = stats["created"] - stats["info_skipped"]
            matched_count = eligible - stats["no_match"]
            if eligible > 0:
                self.stdout.write(
                    f"匹配覆盖率: {matched_count}/{eligible} "
                    f"({matched_count / eligible * 100:.1f}%)"
                )

        if unsupported_protocol_counts:
            self.stdout.write("不支持协议跳过统计:")
            for protocol, count in sorted(unsupported_protocol_counts.items()):
                self.stdout.write(f"  {protocol}: {count}")

        if failed_files:
            self.stdout.write(f"\n解析/创建失败 ({len(failed_files)} 个):")
            for rel_path, reason in failed_files[:20]:
                self.stdout.write(f"  [{reason}] {rel_path}")
            if len(failed_files) > 20:
                self.stdout.write(f"  ... 还有 {len(failed_files) - 20} 个")

    def _flush_batch(self, exp_batch, match_batch):
        """批量写入 EXP 记录、支持功能和指纹绑定"""
        # 先写 EXP 记录（bulk_create 后会回填 PK）
        models.EXP.objects.bulk_create(exp_batch)

        # 处理 tags（M2M 需要 PK，在 bulk_create 后处理）
        for exp in exp_batch:
            raw_tags = getattr(exp, '_raw_tags', '')
            if raw_tags:
                tag_names = [t.strip().lower() for t in raw_tags.split(',') if t.strip()]
                for tag_name in tag_names:
                    tag, _ = models.Tag.objects.get_or_create(name=tag_name[:128])
                    exp.tags.add(tag)

        # 写支持功能（默认 Verify）
        extensions = [models.cveExtensions(CVE=exp, function=1) for exp in exp_batch]
        models.cveExtensions.objects.bulk_create(extensions)

        # 创建指纹绑定
        if match_batch:
            relations = []
            for exp, fp_id, _strategy, _confidence in match_batch:
                relations.append(
                    models.exp_relate_fingerprint(
                        EXP_id=exp,
                        fingerprint_id_id=fp_id,
                    )
                )
            models.exp_relate_fingerprint.objects.bulk_create(
                relations, ignore_conflicts=True
            )
