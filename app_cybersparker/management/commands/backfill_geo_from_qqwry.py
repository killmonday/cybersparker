"""回填旧 IP 记录的地理位置信息（省份/城市/运营商）。"""

from django.core.management.base import BaseCommand
from django.db import connection
from app_cybersparker import models
from app_cybersparker.lib.qqwry import query_ip_geo


BATCH_SIZE = 500


class Command(BaseCommand):
    help = "用纯真数据库回填已有 IP 记录的 province/city/isp 字段"

    def handle(self, *args, **options):
        qs = models.auto_scan_indentify_result.objects.filter(
            ip__regex=r"^\d+\.\d+\.\d+\.\d+$",
        ).exclude(
            province__isnull=False,
            city__isnull=False,
            isp__isnull=False,
        ).exclude(
            province="",
            city="",
            isp="",
        )

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("所有 IP 记录已有完整地理位置信息"))
            return

        self.stdout.write(f"需要回填的记录数: {total}")

        updated = 0
        failed = 0
        offset = 0

        while True:
            batch = list(qs[offset : offset + BATCH_SIZE].values_list("id", "ip"))
            if not batch:
                break

            for pk, ip in batch:
                try:
                    geo = query_ip_geo(ip)
                except Exception:
                    failed += 1
                    continue

                province = geo.get("province", "") or ""
                city = geo.get("city", "") or ""
                isp = geo.get("isp", "") or ""

                if province or city or isp:
                    models.auto_scan_indentify_result.objects.filter(id=pk).update(
                        province=province,
                        city=city,
                        isp=isp,
                    )
                    updated += 1

            offset += BATCH_SIZE
            try:
                connection.close()
            except Exception:
                pass

            self.stdout.write(f"  进度: {min(offset, total)}/{total}  已更新: {updated}")

        self.stdout.write(self.style.SUCCESS(
            f"回填完成。更新: {updated}, 失败: {failed}, "
            f"无数据: {total - updated - failed}"
        ))
