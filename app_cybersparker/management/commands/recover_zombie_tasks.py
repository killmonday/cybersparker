from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from app_cybersparker import models


class Command(BaseCommand):
    help = '将无活跃执行器心跳的中间态任务（运行中/暂停中/排队中）重置为停止。'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true',
            help='跳过心跳时效检查，强制重置所有非终态任务。',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='仅检查受影响的记录，不实际修改。',
        )

    def handle(self, **options):
        force = options['force']
        dry_run = options['dry_run']

        now = timezone.now()
        heartbeat_interval = int(getattr(settings, "RESOURCE_HEARTBEAT_INTERVAL_SECONDS", 10))
        lease_ttl = int(getattr(settings, "RESOURCE_LEASE_TTL_SECONDS", 30))
        stale_before = now - timedelta(seconds=max(lease_ttl * 2, heartbeat_interval * 3))
        missing_start_time = Q(startTime__isnull=True) & Q(queued=False)

        tasks_info = [
            (
                "auto_scan_tasks",
                models.auto_scan_tasks.objects.filter(status__in=[2, 4]).filter(
                    Q(pause_requested=True)
                    | missing_start_time
                    | Q(heartbeat_at__lt=stale_before)
                    | (Q(queued=True) & Q(startTime__lt=stale_before))
                    | (Q(owner__isnull=True) & Q(queued=False) & Q(startTime__lt=stale_before))
                    | (Q(owner="") & Q(queued=False) & Q(startTime__lt=stale_before))
                    | (Q(heartbeat_at__isnull=True) & Q(startTime__lt=stale_before))
                ),
            ),
            (
                "batch_EXPTask",
                models.batch_EXPTask.objects.filter(status=2).filter(
                    missing_start_time
                    | Q(heartbeat_at__lt=stale_before)
                    | (Q(queued=True) & Q(startTime__lt=stale_before))
                    | (Q(owner__isnull=True) & Q(queued=False) & Q(startTime__lt=stale_before))
                    | (Q(owner="") & Q(queued=False) & Q(startTime__lt=stale_before))
                    | (Q(heartbeat_at__isnull=True) & Q(startTime__lt=stale_before))
                ),
            ),
            (
                "DirScanTask",
                models.DirScanTask.objects.filter(status=1).filter(
                    Q(heartbeat_at__lt=stale_before)
                    | (Q(heartbeat_at__isnull=True) & Q(start_time__lt=stale_before))
                ),
            ),
        ]

        if force:
            tasks_info = [
                ("auto_scan_tasks (force)", models.auto_scan_tasks.objects.filter(status__in=[2, 4])),
                ("batch_EXPTask (force)", models.batch_EXPTask.objects.filter(status=2)),
("DirScanTask (force)", models.DirScanTask.objects.filter(status=1)),
            ]

        total = 0
        for label, qs in tasks_info:
            ids = list(qs.values_list("id", flat=True))
            count = len(ids)
            total += count
            if count:
                self.stdout.write(f"  {label}: {count} 条 (ids={ids[:10]}{'...' if count > 10 else ''})")
                if not dry_run:
                    if label.startswith("auto_scan"):
                        qs.update(
                            status=3, queued=False, stop_requested=False,
                            pause_requested=False, failed=False,
                            last_error="recover_zombie_tasks", endTime=now,
                        )
                    elif label.startswith("batch"):
                        qs.update(
                            status=3, queued=False, stop_requested=False,
                            failed=False, last_error="recover_zombie_tasks", endTime=now,
                        )
                    elif label.startswith("DirScan"):
                        from app_cybersparker.services.dirscan_engine import cleanup_task_redis
                        qs.update(status=3, queued=False, end_time=now)
                        for tid in ids:
                            try:
                                cleanup_task_redis(tid)
                            except Exception:
                                pass

        if total == 0:
            self.stdout.write(self.style.SUCCESS("没有发现僵尸任务。"))
        elif dry_run:
            self.stdout.write(self.style.WARNING(f"\n[dry-run] 共 {total} 条，未实际修改。"))
        else:
            self.stdout.write(self.style.SUCCESS(f"\n已重置 {total} 条僵尸任务为停止状态。"))
