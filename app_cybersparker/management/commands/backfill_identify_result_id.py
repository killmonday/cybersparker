from urllib.parse import urlparse

from django.core.management.base import BaseCommand
from django.db import connection
from app_cybersparker import models


class Command(BaseCommand):
    help = "回填 auto_scan_exp_result.identify_result_id（从 target 解析三元组匹配根资产）"

    def handle(self, *args, **options):
        rows = models.auto_scan_exp_result.objects.filter(
            identify_result_id__isnull=True
        ).values_list('id', 'target')
        total = rows.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("无需回填，所有记录已有 identify_result_id"))
            return

        table = connection.ops.quote_name(models.auto_scan_exp_result._meta.db_table)
        updated = 0
        updates = []
        batch_size = 5000

        for exp_id, target in rows.iterator():
            if "://" not in target:
                target = "http://" + target
            parsed = urlparse(target)
            protocol = parsed.scheme or "http"
            host = parsed.hostname or ""
            port = parsed.port or (443 if protocol == "https" else 80)
            asset = models.auto_scan_indentify_result.objects.filter(
                protocol=protocol, host=host, port=port
            ).values_list('id', flat=True).first()
            # 注意：同 protocol+host+port 可能跨多个 zone 存在多条资产。
            # 若需精确匹配，可通过 exp_result.task_id → auto_scan_tasks.zone_id 限定 zone。
            # 当前仅取第一条匹配（按 id 排序），适用于 zone 化之前的历史数据。
            if asset:
                updates.append((asset, exp_id))
            if len(updates) >= batch_size:
                with connection.cursor() as c:
                    c.executemany(
                        f'UPDATE {table} SET identify_result_id = %s WHERE id = %s',
                        updates,
                    )
                updated += len(updates)
                self.stdout.write(f"  已回填 {updated}/{total}")
                updates.clear()

        if updates:
            with connection.cursor() as c:
                c.executemany(
                    f'UPDATE {table} SET identify_result_id = %s WHERE id = %s',
                    updates,
                )
            updated += len(updates)

        pct = (updated / total * 100) if total else 0
        self.stdout.write(self.style.SUCCESS(
            f"回填完成: {updated}/{total} ({pct:.1f}%)"
        ))
