import os
from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand

from app_cybersparker import models
from app_cybersparker.views.expload.task_manage.nuclei_runtime_engine import (
    find_unsupported_nuclei_protocols,
)


class Command(BaseCommand):
    help = "删除当前引擎不支持协议的 nuclei 模板，并清理批量任务中的悬空引用。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只统计不删除",
        )

    def handle(self, **options):
        dry_run = options["dry_run"]
        exp_qs = models.EXP.objects.filter(plugin_language=2).order_by("id")

        delete_rows = []
        protocol_counts = {}

        for exp in exp_qs.iterator(chunk_size=500):
            doc = self._load_yaml(exp)
            if doc is None:
                continue
            unsupported = find_unsupported_nuclei_protocols(doc)
            if not unsupported:
                continue
            delete_rows.append(
                {
                    "id": exp.id,
                    "title": exp.title,
                    "poc": str(exp.poc or ""),
                    "unsupported": unsupported,
                }
            )
            for protocol in unsupported:
                protocol_counts[protocol] = protocol_counts.get(protocol, 0) + 1

        delete_ids = [row["id"] for row in delete_rows]
        delete_id_strings = {str(item) for item in delete_ids}
        affected_batch_tasks = self._collect_batch_tasks(delete_id_strings)

        self.stdout.write(f"待删除模板: {len(delete_rows)}")
        if protocol_counts:
            self.stdout.write("按协议统计:")
            for protocol, count in sorted(protocol_counts.items()):
                self.stdout.write(f"  {protocol}: {count}")
        self.stdout.write(f"受影响批量任务: {len(affected_batch_tasks)}")

        if dry_run:
            for row in delete_rows[:20]:
                self.stdout.write(
                    f"  [dry-run] {row['id']} {row['title']} -> {', '.join(row['unsupported'])}"
                )
            for task in affected_batch_tasks[:20]:
                self.stdout.write(
                    f"  [dry-run task] {task['id']} {task['task_name']} -> 删除 {task['removed_ids']}"
                )
            return

        deleted_files, updated_tasks = self._apply_cleanup(delete_rows, affected_batch_tasks)

        self.stdout.write(f"已删除模板: {len(delete_rows)}")
        self.stdout.write(f"已删除文件: {deleted_files}")
        self.stdout.write(f"已清理批量任务: {updated_tasks}")

    def _apply_cleanup(self, delete_rows, affected_batch_tasks):
        deleted_files = 0
        updated_tasks = 0

        for task in affected_batch_tasks:
            task_obj = models.batch_EXPTask.objects.get(id=task["id"])
            task_obj.EXP = task["new_exp"]
            task_obj.save(update_fields=["EXP"])
            updated_tasks += 1

        for row in delete_rows:
            exp = models.EXP.objects.get(id=row["id"])
            poc_name = str(exp.poc.name if getattr(exp.poc, "name", "") else exp.poc or "")
            if poc_name:
                file_path = Path(settings.BASE_DIR) / poc_name
                if file_path.exists():
                    file_path.unlink()
                    deleted_files += 1
            exp.delete()

        return deleted_files, updated_tasks

    def _load_yaml(self, exp):
        poc_path = str(exp.poc or "")
        if not poc_path:
            return None
        file_path = Path(settings.BASE_DIR) / poc_path
        if not file_path.exists():
            fallback = Path(settings.BASE_DIR) / "EXP_plugin" / Path(poc_path).name
            file_path = fallback
        if not file_path.exists() or not os.path.isfile(file_path):
            return None
        try:
            return yaml.safe_load(file_path.read_text(encoding="utf-8", errors="ignore")) or {}
        except Exception:
            return None

    def _collect_batch_tasks(self, delete_id_strings):
        affected = []
        qs = models.batch_EXPTask.objects.exclude(EXP__isnull=True).exclude(EXP="")
        for task in qs.iterator(chunk_size=200):
            parts = [item.strip() for item in str(task.EXP or "").split(",") if item.strip()]
            removed = [item for item in parts if item in delete_id_strings]
            if not removed:
                continue
            new_parts = [item for item in parts if item not in delete_id_strings]
            affected.append(
                {
                    "id": task.id,
                    "task_name": task.task_name,
                    "removed_ids": removed,
                    "new_exp": ",".join(new_parts),
                }
            )
        return affected
