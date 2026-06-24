"""按 (zone_id, ip, port) 去重，每个 zone 内每组只保留 id 最大的那条。"""
from django.core.management.base import BaseCommand
from django.db import models as dj_models
from app_cybersparker import models


class Command(BaseCommand):
    help = "按 zone + IP + 端口去重，每个区域每组保留最新记录"

    def handle(self, *args, **options):
        # 找有重复的 (zone_id, ip, port) 组
        dupes = (
            models.auto_scan_indentify_result.objects
            .values("zone_id", "ip", "port")
            .annotate(cnt=dj_models.Count("id"), keep_id=dj_models.Max("id"))
            .filter(cnt__gt=1)
            .order_by("zone_id", "ip", "port")
        )
        groups = list(dupes)
        total_groups = len(groups)
        if total_groups == 0:
            self.stdout.write(self.style.SUCCESS("没有重复记录"))
            return

        self.stdout.write(f"重复组数: {total_groups}（按 zone + IP + port 分组，不跨 zone 去重）")

        deleted_total = 0
        for i, group in enumerate(groups):
            zone_id, ip, port, keep_id = group["zone_id"], group["ip"], group["port"], group["keep_id"]
            result = models.auto_scan_indentify_result.objects.filter(
                zone_id=zone_id, ip=ip, port=port
            ).exclude(id=keep_id).delete()
            deleted = result[0]
            deleted_total += deleted

            if (i + 1) % 200 == 0:
                self.stdout.write(f"  进度: {i + 1}/{total_groups}  已删: {deleted_total}")

        self.stdout.write(self.style.SUCCESS(f"完成。删除 {deleted_total} 条，保留 {models.auto_scan_indentify_result.objects.count()} 条"))
