def run_gevent_task_in_subprocess(data):
    from gevent import monkey

    monkey.patch_all(thread=False, subprocess=False, ssl=True)

    import urllib3.util.ssl_
    import ssl as _stdlib_ssl
    urllib3.util.ssl_.SSLContext = _stdlib_ssl.SSLContext

    from app_cybersparker.views.expload.task_manage.batch_task_executor import Task_handler

    Task_handler._gevent_patched = True
    task_handler = Task_handler(data)
    task_handler.run_mode = 2
    task_handler.run()

    pause_val = data.get("_pause_requested")
    stop_val = data.get("_stop_requested")
    if pause_val is not None:
        pause_val.value = task_handler.pause_requested
    if stop_val is not None:
        stop_val.value = task_handler.stop_requested
