"""回填已有 Nuclei YAML 模板的 severity 和 tags 数据"""
import os
import traceback

import yaml
from django.core.management.base import BaseCommand
from django.db import connection as db_connection

from app_cybersparker import models


class Command(BaseCommand):
    help = '回填已有 nuclei_yaml EXP 的 severity 和 tags（从 YAML 文件读取）'

    def handle(self, **options):
        qs = models.EXP.objects.filter(plugin_language=2)
        total = qs.count()
        updated = 0
        tag_created = 0
        skipped = 0
        failed = 0

        self.stdout.write(f"共 {total} 条 nuclei_yaml EXP 待处理")

        for exp in qs.iterator(chunk_size=500):
            try:
                poc_path = str(exp.poc) if exp.poc else ""
                if not poc_path or not os.path.isfile(poc_path):
                    skipped += 1
                    continue

                with open(poc_path, "r", encoding="utf-8") as f:
                    doc = yaml.safe_load(f.read()) or {}

                info = doc.get("info") or {}
                if not info:
                    skipped += 1
                    continue

                severity = str(info.get("severity") or "")[:10]
                tags_raw = str(info.get("tags") or "")

                if not severity and not tags_raw:
                    skipped += 1
                    continue

                # 更新 severity
                if severity and exp.severity != severity:
                    exp.severity = severity
                    exp.save(update_fields=["severity"])

                # 更新 tags
                if tags_raw:
                    tag_names = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
                    current_tag_ids = set(exp.tags.values_list("id", flat=True))
                    new_tags = []
                    for tag_name in tag_names:
                        tag, created = models.Tag.objects.get_or_create(name=tag_name[:128])
                        if created:
                            tag_created += 1
                        if tag.id not in current_tag_ids:
                            new_tags.append(tag)
                    if new_tags:
                        exp.tags.add(*new_tags)

                updated += 1

                if updated % 500 == 0:
                    self.stdout.write(
                        f"  进度: {updated}/{total} (更新 {updated}, "
                        f"跳过 {skipped}, 失败 {failed}, 新建 tag {tag_created})"
                    )

            except Exception:
                failed += 1
                if failed <= 10:
                    self.stdout.write(f"  失败: {exp.id} {exp.title[:60]} — {traceback.format_exc().strip().split(chr(10))[-1]}")

        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write("回填完成")
        self.stdout.write("=" * 60)
        self.stdout.write(f"总条数:   {total}")
        self.stdout.write(f"已更新:   {updated}")
        self.stdout.write(f"跳过:     {skipped}")
        self.stdout.write(f"失败:     {failed}")
        self.stdout.write(f"新建 Tag: {tag_created}")
