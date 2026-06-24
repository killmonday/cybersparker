import os
import requests
from uuid import uuid4

from app_cybersparker import models
from app_cybersparker.services.cyberspace_engine_adapters import get_adapter, ENGINE_PAGE_SIZE
import cybersparker.settings as sett


ENGINE_ASSET_DIR = "EXP_input/engine_assets"


def _project_root():
    return os.path.dirname(os.path.abspath(sett.THIS_DIR)).replace("\\", "/")


def get_absolute_target_path(relative_path):
    relative = str(relative_path or "").strip().replace("\\", "/")
    if not relative:
        return ""
    if os.path.isabs(relative):
        result = os.path.normpath(relative)
    else:
        result = os.path.normpath(os.path.join(_project_root(), relative))
    proj_root_norm = os.path.normpath(_project_root())
    if not result.startswith(proj_root_norm + os.sep) and result != proj_root_norm:
        return ""
    return result


def get_engine_asset_root():
    return os.path.normpath(os.path.join(_project_root(), ENGINE_ASSET_DIR))


def ensure_engine_asset_root():
    root = get_engine_asset_root()
    os.makedirs(root, exist_ok=True)
    return root


def normalize_target(value):
    target = str(value or "").strip()
    if not target:
        return ""
    if target.startswith("https://") or target.startswith("http://"):
        return target
    if "://" in target:
        return target
    if target.endswith("/udp"):
        return target
    if ":" in target:
        return "http://" + target
    return target


def is_engine_asset_target(relative_path):
    relative = str(relative_path or "").replace("\\", "/").strip()
    return relative.startswith(ENGINE_ASSET_DIR + "/")


def get_engine_asset_file_path(relative_path):
    if not is_engine_asset_target(relative_path):
        return ""
    abs_path = os.path.realpath(get_absolute_target_path(relative_path))
    root = os.path.realpath(get_engine_asset_root())
    if not abs_path.startswith(root + os.sep):
        return ""
    return abs_path


def remove_engine_asset_file(relative_path):
    abs_path = get_engine_asset_file_path(relative_path)
    if os.path.isfile(abs_path):
        os.remove(abs_path)
        return True
    return False


def _build_proxy_url(proxy_obj):
    if not proxy_obj:
        return ""
    protocol = proxy_obj.get_protocol_type()
    return f"{protocol}://{proxy_obj.proxy_address}:{proxy_obj.proxy_port}"


def resolve_engine_proxy(task_obj, config_obj):
    mode = int(task_obj.engine_proxy_mode if task_obj.engine_proxy_mode is not None else 0)
    if mode == 1:
        return ""
    if mode == 2:
        if not task_obj.engine_proxy_id:
            raise ValueError("proxy mode is force proxy but task proxy is empty")
        return _build_proxy_url(task_obj.engine_proxy)
    if config_obj.use_proxy:
        if not config_obj.proxy_id:
            raise ValueError("engine config uses proxy but proxy is empty")
        return _build_proxy_url(config_obj.proxy)
    return ""


def _safe_max_assets(value):
    try:
        number = int(value)
    except Exception:
        number = 100
    if number <= 0:
        number = 100
    max_fetch = getattr(sett, "ENGINE_MAX_FETCH_ASSETS", 5000)
    if number > max_fetch:
        number = max_fetch
    return number


def _validate_task_engine_fields(task_obj):
    if int(task_obj.input_type or 1) != 4:
        raise ValueError("task input type is not cyberspace engine")
    if not str(task_obj.engine_type or "").strip():
        raise ValueError("engine_type is required")
    if not str(task_obj.engine_query or "").strip():
        raise ValueError("engine_query is required")


def fetch_and_dump_targets(task_obj):
    _validate_task_engine_fields(task_obj)

    engine_type = str(task_obj.engine_type).strip().lower()
    query = str(task_obj.engine_query).strip()
    max_assets = _safe_max_assets(task_obj.engine_max_assets)
    task_id = getattr(task_obj, "id", None)
    print(f"[engine-fetch] start task={task_id} engine={engine_type} query={query!r} max_assets={max_assets}")

    config_obj = models.CyberspaceEngineSetting.objects.filter(engine_type=engine_type).first()
    if not config_obj:
        raise ValueError("engine config does not exist")

    proxy_url = resolve_engine_proxy(task_obj, config_obj)
    adapter = get_adapter(engine_type)
    proxies = adapter.build_proxies(proxy_url)

    ensure_engine_asset_root()
    file_name = f"{engine_type}_{uuid4().hex}.txt"
    relative_path = f"{ENGINE_ASSET_DIR}/{file_name}"
    absolute_path = get_absolute_target_path(relative_path)
    open(absolute_path, "w", encoding="utf-8", errors="ignore").close()

    targets = []
    target_set = set()
    page = 1
    page_size = min(ENGINE_PAGE_SIZE, max_assets)
    consecutive_zero_add = 0

    while len(targets) < max_assets:
        print(f"[engine-fetch] request task={task_id} engine={engine_type} page={page} page_size={page_size} current_total={len(targets)}")

        response = None
        for attempt in range(2):
            try:
                response = adapter.search(
                    query=query,
                    page=page,
                    page_size=page_size,
                    config=config_obj,
                    proxies=proxies,
                )
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt == 0:
                    print(f"[engine-fetch] retry task={task_id} engine={engine_type} page={page} error={e}")
                else:
                    print(f"[engine-fetch] giveup task={task_id} engine={engine_type} page={page} error={e} keep={len(targets)}")

        if response is None:
            break

        print(f"[engine-fetch] response task={task_id} engine={engine_type} page={page} status={response.status_code}")
        if response.status_code >= 400:
            raise ValueError(f"engine api request failed: status={response.status_code}")

        batch_targets = adapter.extract_targets(response)
        print(f"[engine-fetch] extracted task={task_id} engine={engine_type} page={page} raw_count={len(batch_targets)} sample={batch_targets[:5]}")
        if not batch_targets:
            break

        is_last_page = len(batch_targets) < page_size

        added = 0
        duplicate_count = 0
        empty_count = 0
        for item in batch_targets:
            normalized = normalize_target(item)
            if not normalized:
                empty_count += 1
                continue
            if normalized in target_set:
                duplicate_count += 1
                continue
            target_set.add(normalized)
            targets.append(normalized)
            added += 1
            if len(targets) >= max_assets:
                break

        if added > 0:
            with open(absolute_path, "a", encoding="utf-8", errors="ignore") as file_obj:
                file_obj.write("\n".join(targets[-added:]) + "\n")

        print(f"[engine-fetch] normalized task={task_id} engine={engine_type} page={page} added={added} duplicates={duplicate_count} empty={empty_count} total={len(targets)}")
        if added == 0:
            consecutive_zero_add += 1
            if consecutive_zero_add >= 3:
                raise ValueError(f"engine api returning duplicate data: {consecutive_zero_add} consecutive pages with zero new targets")
            print(f"[engine-fetch] warn task={task_id} engine={engine_type} page={page} zero_add_streak={consecutive_zero_add}")
        else:
            consecutive_zero_add = 0

        if is_last_page:
            print(f"[engine-fetch] stop task={task_id} engine={engine_type} page={page} reason=last_page")
            break

        page += 1

    if not targets:
        raise ValueError("engine search no target")

    print(f"[engine-fetch] finish task={task_id} engine={engine_type} total={len(targets)} target_file={relative_path}")
    return relative_path
