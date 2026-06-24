import os
import sys

from celery import Celery, bootsteps
from celery.signals import worker_process_init
from django.conf import settings
from django.db import close_old_connections
from kombu import Exchange, Queue
from dj_db_conn_pool.core import pool_container

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cybersparker.settings")

app = Celery("cybersparker")
app.config_from_object("django.conf:settings", namespace="CELERY")

queue_names = tuple(getattr(settings, "CELERY_QUEUE_NAMES", ("auto_scan", "batch_scan", "batch_scan_gevent", "result_writer", "maintenance", "poc_generation")))
app.conf.task_queues = tuple(
    Queue(queue_name, Exchange(queue_name, type="direct"), routing_key=queue_name)
    for queue_name in queue_names
)
app.conf.task_default_queue = "maintenance"
app.conf.task_default_exchange = "maintenance"
app.conf.task_default_exchange_type = "direct"
app.conf.task_default_routing_key = "maintenance"
app.conf.task_routes = {
    "app_cybersparker.tasks.run_auto_scan_task": {"queue": "auto_scan", "routing_key": "auto_scan"},
    "app_cybersparker.tasks.run_batch_scan_task": {"queue": "batch_scan", "routing_key": "batch_scan"},
    "app_cybersparker.tasks.batch_scan_gevent_probe": {"queue": "batch_scan_gevent", "routing_key": "batch_scan_gevent"},
    "app_cybersparker.tasks.auto_scan_probe": {"queue": "auto_scan", "routing_key": "auto_scan"},
    "app_cybersparker.tasks.batch_scan_probe": {"queue": "batch_scan", "routing_key": "batch_scan"},
    "app_cybersparker.tasks.run_result_writer_task": {"queue": "result_writer", "routing_key": "result_writer"},
    "app_cybersparker.tasks.result_writer_probe": {"queue": "result_writer", "routing_key": "result_writer"},
    "app_cybersparker.tasks.maintenance_echo": {"queue": "maintenance", "routing_key": "maintenance"},
    "app_cybersparker.tasks.run_dir_scan_task": {"queue": "dir_scan", "routing_key": "dir_scan"},
    "app_cybersparker.tasks.run_poc_generation": {"queue": "poc_generation", "routing_key": "poc_generation"},
}
app.autodiscover_tasks()


def is_worker_boot(argv=None):
    current_argv = argv or sys.argv
    return any(arg == "worker" for arg in current_argv)


def enforce_worker_connection_budget(argv=None):
    if not is_worker_boot(argv):
        return None

    from app_cybersparker.services.celery_runtime_service import assert_celery_connection_budget

    return assert_celery_connection_budget()


class ConnectionBudgetGate(bootsteps.StartStopStep):
    requires = {"celery.worker.components:Pool"}

    def __init__(self, worker, **kwargs):
        from app_cybersparker.services.celery_runtime_service import assert_celery_connection_budget

        assert_celery_connection_budget()
        super().__init__(worker, **kwargs)


@worker_process_init.connect
def reset_db_connections_for_worker_process(**kwargs):
    close_old_connections()
    pool_container.dispose()


app.steps["worker"].add(ConnectionBudgetGate)
enforce_worker_connection_budget()
