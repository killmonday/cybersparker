from django.core.management.base import BaseCommand
from django.db import connection

from app_cybersparker import models

BATCH_SIZE = 500


class Command(BaseCommand):
    help = ('补丁：为没有支持功能（cveExtensions）的 EXP 插件补齐默认值 Verify。'
            '安全：只增不删不改，多次运行无副作用。')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='只统计不写入')

    def handle(self, **options):
        dry_run = options['dry_run']

        missing_ids = (
            models.EXP.objects
            .exclude(id__in=models.cveExtensions.objects.values_list('CVE_id', flat=True).distinct())
            .values_list('id', flat=True)
        )
        total = len(missing_ids)
        self.stdout.write(f'缺少支持功能的 PoC: {total}')

        if dry_run or total == 0:
            return

        # 修复序列（防止 PK 冲突）
        with connection.cursor() as c:
            c.execute(
                "SELECT setval('app_cybersparker_cveextensions_id_seq', "
                "(SELECT GREATEST(MAX(id), 1) FROM app_cybersparker_cveextensions))"
            )

        created = 0
        for i in range(0, total, BATCH_SIZE):
            batch_ids = missing_ids[i:i + BATCH_SIZE]
            extensions = [
                models.cveExtensions(CVE_id=eid, function=1)  # Verify
                for eid in batch_ids
            ]
            models.cveExtensions.objects.bulk_create(extensions)
            created += len(extensions)
            self.stdout.write(f'  进度: {created}/{total}')

        self.stdout.write(self.style.SUCCESS(f'完成：为 {created} 个 PoC 补齐了 Verify 支持功能'))
