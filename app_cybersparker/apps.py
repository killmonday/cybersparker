from datetime import timedelta
import logging

from django.apps import AppConfig
from django.conf import settings


logger = logging.getLogger(__name__)


class AppCybersparkerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app_cybersparker'

    def ready(self):
        # 确保公网系统区域始终存在——迁移创建后，TransactionTestCase
        # truncate 会导致该行丢失。post_migrate 信号在每次 migrate 后
        # 重新创建，覆盖此场景。
        try:
            from django.db.models.signals import post_migrate
            from django.db import connection

            def _ensure_system_zone(sender, **kwargs):
                with connection.cursor() as c:
                    c.execute("""
                        INSERT INTO app_cybersparker_assetzone (id, code, name, description, is_system, created_at)
                        VALUES (1, 'public', '公网', '', true, now())
                        ON CONFLICT (id) DO NOTHING
                    """)

            post_migrate.connect(_ensure_system_zone, weak=False)
        except Exception:
            pass
        try:
            from django.utils import autoreload

            _original_iter_all = autoreload.iter_all_python_module_files

            def _iter_all_python_module_files():
                return frozenset(
                    p for p in _original_iter_all()
                    if '/EXP_plugin/' not in str(p)
                )

            autoreload.iter_all_python_module_files = _iter_all_python_module_files
        except Exception:
            pass

        try:
            from app_cybersparker.services.request_runtime_config_service import bootstrap_request_runtime
            bootstrap_request_runtime()
        except Exception:
            pass

        try:
            from django.contrib.auth.models import User
            from django.db.models.signals import post_save
            from app_cybersparker.models import UserProfile

            def _create_user_profile(sender, instance, created, **kwargs):
                if created:
                    UserProfile.objects.get_or_create(user=instance)

            post_save.connect(_create_user_profile, sender=User, weak=False)
        except Exception:
            logger.warning("UserProfile signal registration failed", exc_info=True)

        try:
            self._recover_zombie_tasks()
        except Exception:
            logger.warning("Zombie task recovery failed", exc_info=True)

    def _recover_zombie_tasks(self):
        """启动时回收无活执行器证据的中间态任务，避免重启后卡在 running / pausing。"""
        from django.db import connection
        from django.db.models import Q
        from django.utils import timezone

        from app_cybersparker import models

        now = timezone.now()
        heartbeat_interval = int(getattr(settings, "RESOURCE_HEARTBEAT_INTERVAL_SECONDS", 10))
        stale_before = now - timedelta(seconds=heartbeat_interval * 3)
        missing_start_time = Q(startTime__isnull=True) & Q(queued=False)
        # 本进程启动时间。Celery worker 和 Django server 是独立进程，
        # Django 重启时 Celery 可能还在跑。不能用一个很短的窗口（如 5s）
        # 就判定心跳是"上一进程残留"——心跳更新间隔是 heartbeat_interval 秒，
        # 间隔内更新的心跳是正常的，只有超过 3 倍间隔没更新的才是真僵尸。
        startup_time = now - timedelta(seconds=heartbeat_interval * 3)

        # 自动扫描僵尸回收
        auto_running_zombie = models.auto_scan_tasks.objects.filter(status=2).filter(
            Q(pause_requested=True)
            | Q(stop_requested=True)
            | missing_start_time
            | Q(heartbeat_at__lt=startup_time)
            | Q(heartbeat_at__lt=stale_before)
            | (Q(queued=True) & Q(startTime__lt=stale_before))
            | (Q(owner__isnull=True) & Q(queued=False) & Q(startTime__lt=stale_before))
            | (Q(owner="") & Q(queued=False) & Q(startTime__lt=stale_before))
            | (Q(heartbeat_at__isnull=True) & Q(startTime__lt=stale_before))
        )
        # 已暂停但 pause_requested 仍为 True（信号未送达 executor），清理标志
        auto_paused_zombie = models.auto_scan_tasks.objects.filter(
            status=4, pause_requested=True,
        )

        auto_pause_zombies = auto_running_zombie.filter(pause_requested=True)
        count_auto_paused = auto_pause_zombies.update(
            status=4,
            queued=False,
            stop_requested=False,
            pause_requested=False,
            failed=False,
            last_error="server restarted (paused)",
            endTime=now,
        )
        if count_auto_paused:
            logger.info("[recovery] Reset %d zombie auto scan task(s) to paused.", count_auto_paused)

        # 已暂停的任务只需清理标志
        count_auto_paused_cleanup = auto_paused_zombie.update(
            pause_requested=False,
            last_error="server restarted (cleanup)",
        )
        if count_auto_paused_cleanup:
            logger.info("[recovery] Cleaned up %d paused auto scan task(s).", count_auto_paused_cleanup)

        auto_stop_zombies = auto_running_zombie.filter(pause_requested=False)
        auto_stop_ids = list(auto_stop_zombies.values_list("id", flat=True))
        if auto_stop_ids:
            from app_cybersparker.services.task_runtime_signal_service import set_stop_signal
            auto_stop_zombies.update(
                status=3,
                queued=False,
                stop_requested=False,
                pause_requested=False,
                failed=False,
                last_error="server restarted",
                endTime=now,
            )
            for tid in auto_stop_ids:
                try:
                    set_stop_signal("auto_scan", tid)
                except Exception:
                    pass
            logger.info("[recovery] Reset %d zombie auto scan task(s) to stopped.", len(auto_stop_ids))

        # 批量任务僵尸回收
        batch_running_zombie = models.batch_EXPTask.objects.filter(status=2).filter(
            Q(pause_requested=True)
            | Q(stop_requested=True)
            | missing_start_time
            | Q(heartbeat_at__lt=startup_time)
            | Q(heartbeat_at__lt=stale_before)
            | (Q(queued=True) & Q(startTime__lt=stale_before))
            | (Q(owner__isnull=True) & Q(queued=False) & Q(startTime__lt=stale_before))
            | (Q(owner="") & Q(queued=False) & Q(startTime__lt=stale_before))
            | (Q(heartbeat_at__isnull=True) & Q(startTime__lt=stale_before))
        )
        batch_pause_zombies = batch_running_zombie.filter(pause_requested=True)
        count_batch_paused = batch_pause_zombies.update(
            status=4,
            queued=False,
            stop_requested=False,
            pause_requested=False,
            failed=False,
            last_error="server restarted (paused)",
            endTime=now,
        )
        if count_batch_paused:
            logger.info("[recovery] Reset %d zombie batch task(s) to paused.", count_batch_paused)

        # 已暂停的任务只需清理残留标志
        batch_paused_zombie = models.batch_EXPTask.objects.filter(
            status=4, pause_requested=True,
        )
        count_batch_paused_cleanup = batch_paused_zombie.update(
            pause_requested=False,
            last_error="server restarted (cleanup)",
        )
        if count_batch_paused_cleanup:
            logger.info("[recovery] Cleaned up %d paused batch task(s).", count_batch_paused_cleanup)

        batch_stop_zombies = batch_running_zombie.filter(pause_requested=False)
        batch_stop_ids = list(batch_stop_zombies.values_list("id", flat=True))
        if batch_stop_ids:
            from app_cybersparker.services.task_runtime_signal_service import set_stop_signal
            batch_stop_zombies.update(
                status=3,
                queued=False,
                stop_requested=False,
                failed=False,
                last_error="server restarted",
                endTime=now,
            )
            for tid in batch_stop_ids:
                try:
                    set_stop_signal("batch_scan", tid)
                except Exception:
                    pass
            logger.info("[recovery] Reset %d zombie batch task(s) to stopped.", len(batch_stop_ids))

        # DirScanTask 僵尸回收
        dirscan_zombie_base = models.DirScanTask.objects.filter(status=1).filter(
            Q(pause_requested=True)
            | Q(heartbeat_at__lt=startup_time)
            | Q(heartbeat_at__lt=stale_before)
            | (Q(heartbeat_at__isnull=True) & Q(start_time__lt=stale_before))
        )
        # 暂停中的僵尸 → status=2（保留进度，可续跑）
        dirscan_pause_zombies = dirscan_zombie_base.filter(pause_requested=True)
        count_ds_paused = dirscan_pause_zombies.update(
            status=2,
            queued=False,
            pause_requested=False,
            stop_requested=False,
            end_time=now,
        )
        if count_ds_paused:
            logger.info("[recovery] Reset %d zombie dirscan task(s) to paused.", count_ds_paused)

        # 运行中失联的僵尸 → status=3（停止，清理 Redis）
        dirscan_stop_zombies = dirscan_zombie_base.filter(pause_requested=False)
        dirscan_ids = list(dirscan_stop_zombies.values_list("id", flat=True))
        if dirscan_ids:
            from app_cybersparker.services.dirscan_engine import cleanup_task_redis
            from app_cybersparker.services.task_runtime_signal_service import set_stop_signal
            dirscan_stop_zombies.update(
                status=3,
                queued=False,
                end_time=now,
            )
            for tid in dirscan_ids:
                try:
                    set_stop_signal("dir_scan", tid)
                    cleanup_task_redis(tid)
                except Exception:
                    pass
            logger.info("[recovery] Reset %d zombie dirscan task(s) to stopped.", len(dirscan_ids))

        # PoC生成任务僵尸回收
        poc_zombie_pending = models.PoCGenerationTask.objects.filter(status="pending")
        count_poc_pending = poc_zombie_pending.update(status="ready")
        if count_poc_pending:
            logger.info("[recovery] Reset %d pending PoC task(s) to ready.", count_poc_pending)

        poc_zombie_crawling = models.PoCGenerationTask.objects.filter(status="crawling")
        count_poc_crawling = poc_zombie_crawling.update(status="pending")
        if count_poc_crawling:
            logger.info("[recovery] Reset %d crawling PoC task(s) to pending.", count_poc_crawling)

        poc_zombie_generating = models.PoCGenerationTask.objects.filter(status="generating")
        count_poc_generating = poc_zombie_generating.update(status="ready")
        if count_poc_generating:
            logger.info("[recovery] Reset %d generating PoC task(s) to ready.", count_poc_generating)

        connection.close()
