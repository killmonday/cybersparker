import os
from django.conf import settings
from django.http import HttpResponse
from django.urls import path, re_path
from django.views.generic import RedirectView
from django.conf.urls.static import static
from app_cybersparker.views import Dashboards, login


def _serve_react_shell(request, subpath=None):
    """开发/直连 Django 时兜底：直接返回 Vite 构建产出的 index.html"""
    index_path = os.path.join(os.path.dirname(__file__), '..', 'app_cybersparker', 'static', 'react-shell', 'index.html')
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            return HttpResponse(f.read(), content_type='text/html; charset=utf-8')
    except FileNotFoundError:
        return HttpResponse(
            '<html><body><p>React 壳页未构建，请先运行 <code>cd frontend && npm run build</code></p></body></html>',
            content_type='text/html; charset=utf-8',
            status=404,
        )
from app_cybersparker.views.expload.task_manage.auto_scan_task_api import task_batch_delete_api, task_choices_api, task_create_api, task_delete_api, task_detail_api, task_history_engine_results_api, task_history_files_api, task_list_api, task_operate_api, task_status_api, task_status_batch_api, task_update_api
from app_cybersparker.views.expload.task_manage.batch_exp_task import history_engine_results as batch_task_history_engine_results
from app_cybersparker.views.expload.task_manage.batch_exp_task_api import batch_task_batch_delete_api, batch_task_choices_api, batch_task_create_api, batch_task_delete_api, batch_task_detail_api, batch_task_exp_detail_api, batch_task_history_files_api, batch_task_list_api, batch_task_operate_api, batch_task_plugins_api, batch_task_status_api, batch_task_status_batch_api, batch_task_update_api
from app_cybersparker.views.expload.dirscan_task_api import dirscan_batch_delete_api, dirscan_create_api, dirscan_delete_api, dirscan_detail_api, dirscan_list_api, dirscan_operate_api, dirscan_status_api, dirscan_status_batch_api, dirscan_update_api
from app_cybersparker.views.expload import exp_debug, fingerprint, plugin_manage, proxy_setting, fingerPrint_debug, cyberspace_engine_setting, ceye_config, dict_manage
from app_cybersparker.views.expload.dict_manage import dict_batch_delete_api, dict_create_api, dict_delete_api, dict_detail_api, dict_group_batch_delete_api, dict_group_create_api, dict_group_delete_api, dict_group_detail_api, dict_group_list_api, dict_group_update_api, dict_update_api
from app_cybersparker.views.expload.export_task import export_task_batch_delete_api, export_task_download, export_task_list_api
from app_cybersparker.views.expload.target_file_manage import target_file_batch_delete_api, target_file_batch_delete_confirm_api, target_file_delete_api, target_file_delete_confirm_api, target_file_download_api, target_file_list_api, target_file_upload_api
from app_cybersparker.views.expload.hosted_file_manage import hosted_file_list_api, hosted_file_upload_api, hosted_file_delete_api, hosted_file_rename_api, hosted_file_access_api, hosted_file_note_api, hosted_file_download
from app_cybersparker.views import user_manage
from app_cybersparker.views.ai_poc.ai_model_config import api_configs as ai_model_config_api, api_config_detail as ai_model_config_detail_api
from app_cybersparker.views.ai_poc.poc_gen_task import api_tasks as poc_gen_task_api, api_task_detail as poc_gen_task_detail_api, api_generate as poc_gen_task_generate_api, api_save_to_exp as poc_gen_task_save_to_exp_api, api_preview_prompt as poc_gen_task_preview_prompt_api, api_retry as poc_gen_task_retry_api
from app_cybersparker.views.expload.result__manage import all_auto_exp_result, expResult
from app_cybersparker.views.expload.task_manage import auto_scan_result
from app_cybersparker.views.expload import fscanx_views
from app_cybersparker.views.expload import zone_manage

urlpatterns = [
    # ======================== 登录认证 ========================
    path("login", login.login),
    path("logout", login.logout, name="logout"),
    path("api/v1/auth/session", login.session_status, name="api_session_status"),

    # ======================== 用户管理 API ========================
    path("api/v1/users", user_manage.user_list_api, name="api_user_list"),
    path("api/v1/users/create", user_manage.user_create_api, name="api_user_create"),
    path("api/v1/users/me/password", user_manage.user_me_password_api, name="api_user_me_password"),
    path("api/v1/users/<int:user_id>/role", user_manage.user_role_api, name="api_user_role"),
    path("api/v1/users/<int:user_id>/password", user_manage.user_password_api, name="api_user_password"),
    path("api/v1/users/<int:user_id>", user_manage.user_delete_api, name="api_user_delete"),

    # ======================== 仪表盘 & 运行时 ========================
    path('runtime/diagnostics', Dashboards.runtime_diagnostics, name="runtime_diagnostics"),
    path('api/v1/dashboard', Dashboards.dashboard_api, name="api_dashboard"),

    # ======================== 插件管理 API ========================
    path('api/v1/plugins', plugin_manage.expload_list_api, name="api_plugins_list"),
    path('api/v1/plugins/batch-delete', plugin_manage.api_plugin_batch_delete, name="api_plugins_batch_delete"),
    path('api/v1/plugins/<int:uid>', plugin_manage.expload_detail_api, name="api_plugins_detail"),

    # ======================== 字典管理 API ========================
    path('api/v1/dicts', dict_manage.dict_list_api, name="api_dicts_list"),
    path('api/v1/dicts/batch-delete', dict_batch_delete_api, name="api_dicts_batch_delete"),
    path('api/v1/dicts/create', dict_create_api, name="api_dicts_create"),
    path('api/v1/dicts/<int:uid>', dict_detail_api, name="api_dicts_detail"),
    path('api/v1/dicts/<int:uid>/update', dict_update_api, name="api_dicts_update"),
    path('api/v1/dicts/<int:uid>/delete', dict_delete_api, name="api_dicts_delete"),

    # ======================== 代理管理 API ========================
    path('api/v1/proxies', proxy_setting.list_api, name="api_proxies_list"),
    path('api/v1/proxies/batch-delete', proxy_setting.proxy_batch_delete_api, name="api_proxies_batch_delete"),
    path('api/v1/proxies/create', proxy_setting.create_api, name="api_proxies_create"),
    path('api/v1/proxies/<int:uid>', proxy_setting.detail_api, name="api_proxies_detail"),
    path('api/v1/proxies/<int:uid>/update', proxy_setting.update_api, name="api_proxies_update"),

    # ======================== 测绘引擎 API ========================
    path('api/v1/cyberspace-engines', cyberspace_engine_setting.list_api, name="api_cyberspace_engines_list"),
    path('api/v1/cyberspace-engines/batch-delete', cyberspace_engine_setting.engine_batch_delete_api, name="api_cyberspace_engines_batch_delete"),
    path('api/v1/cyberspace-engines/create', cyberspace_engine_setting.create_api, name="api_cyberspace_engines_create"),
    path('api/v1/cyberspace-engines/<int:uid>', cyberspace_engine_setting.detail_api, name="api_cyberspace_engines_detail"),
    path('api/v1/cyberspace-engines/<int:uid>/update', cyberspace_engine_setting.update_api, name="api_cyberspace_engines_update"),

    # ======================== 扫描区域 API ========================
    path('api/v1/zones', zone_manage.zone_list_api, name="api_zones_list"),
    path('api/v1/zones/create', zone_manage.zone_create_api, name="api_zones_create"),
    path('api/v1/zones/<int:zone_id>/update', zone_manage.zone_update_api, name="api_zones_update"),
    path('api/v1/zones/<int:zone_id>/delete', zone_manage.zone_delete_api, name="api_zones_delete"),

    # ======================== 指纹管理 API ========================
    path('api/v1/fingerprints', fingerprint.list_api, name="api_fingerprints_list"),
    path('api/v1/fingerprints/batch-delete', fingerprint.fingerprint_batch_delete_api, name="api_fingerprints_batch_delete"),
    path('api/v1/fingerprints/create', fingerprint.create_api, name="api_fingerprints_create"),
    path('api/v1/fingerprints/<int:uid>', fingerprint.detail_api, name="api_fingerprints_detail"),
    path('api/v1/fingerprints/<int:uid>/update', fingerprint.update_api, name="api_fingerprints_update"),
    path('api/v1/fingerprints/<int:uid>/plugins', fingerprint.fingerprint_plugins_api, name="api_fingerprint_plugins"),
    path('api/v1/fingerprints/<int:uid>/plugins/<int:exp_id>', fingerprint.fingerprint_delete_plugin_api, name="api_fingerprint_delete_plugin"),

    # ======================== 插件调试 API ========================
    path("api/v1/exp-debug/plugins", exp_debug.api_plugin_list, name="api_exp_debug_plugins"),
    path("api/v1/exp-debug/info", exp_debug.api_exp_info, name="api_exp_debug_info"),
    path("api/v1/exp-debug/execute", exp_debug.api_exp_execute, name="api_exp_debug_execute"),
    path("api/v1/exp-debug/save", exp_debug.api_exp_save, name="api_exp_debug_save"),

    # ======================== 共享历史文件 API ========================
    path("api/v1/history-files", task_history_files_api, name="api_history_files"),

    # ======================== 漏洞利用结果 API ========================
    path("api/v1/exp-results/clear", expResult.exp_result_clear_api, name="api_exp_results_clear"),
    path("api/v1/exp-results", expResult.exp_result_list_api, name="api_exp_results_list"),
    path("api/v1/exp-results/plugins", expResult.exp_result_plugins_api, name="api_exp_results_plugins"),
    path("api/v1/exp-results/batch-delete", expResult.exp_result_batch_delete_api, name="api_exp_results_batch_delete"),
    path("api/v1/exp-results/download", expResult.exp_result_download_api, name="api_exp_results_download"),
    path("api/v1/exp-results/plugin-info", expResult.getPluginInfo, name="api_exp_results_plugin_info"),
    path("api/v1/exp-results/verify", expResult.targetRunVerify, name="api_exp_results_verify"),

    # ======================== 自动扫描利用结果 API ========================
    path("api/v1/auto-exp-results/clear", all_auto_exp_result.auto_exp_result_clear_api, name="api_auto_exp_results_clear"),
    path("api/v1/auto-exp-results", all_auto_exp_result.auto_exp_result_list_api, name="api_auto_exp_results_list"),
    path("api/v1/auto-exp-results/batch-delete", all_auto_exp_result.auto_exp_result_batch_delete_api, name="api_auto_exp_results_batch_delete"),
    path("api/v1/auto-exp-results/download", all_auto_exp_result.auto_exp_result_download_api, name="api_auto_exp_results_download"),

    # ======================== 指纹调试 API ========================
    path("api/v1/fingerprint-debug/fingerprints", fingerPrint_debug.api_fingerprint_list, name="api_fingerprint_debug_list"),
    path("api/v1/fingerprint-debug/mate", fingerPrint_debug.api_fingerprint_mate, name="api_fingerprint_debug_mate"),

    # ======================== fscanx 导入任务 API ========================
    path('api/v1/fscanx-tasks', fscanx_views.fscanx_task_list_api, name="api_fscanx_task_list"),
    path('api/v1/fscanx-tasks/<int:task_id>/details', fscanx_views.fscanx_task_detail_api, name="api_fscanx_task_detail"),
    path('api/v1/fscanx-tasks/<int:task_id>/delete', fscanx_views.fscanx_task_delete_api, name="api_fscanx_task_delete"),
    path('api/v1/fscanx-tasks/details/<int:detail_id>/delete', fscanx_views.fscanx_detail_delete_api, name="api_fscanx_detail_delete"),

    # ======================== 自动扫描任务 API ========================
    path('api/v1/identify-tasks', task_list_api, name="api_task_list"),
    path('api/v1/identify-tasks/create', task_create_api, name="api_task_create"),
    path('api/v1/identify-tasks/batch-delete', task_batch_delete_api, name="api_task_batch_delete"),
    path('api/v1/identify-tasks/choices', task_choices_api, name="api_task_choices"),
    path('api/v1/identify-tasks/history-files', task_history_files_api, name="api_task_history_files"),
    path('api/v1/identify-tasks/history-engine-results', task_history_engine_results_api, name="api_task_history_engine_results"),
    path('api/v1/identify-tasks/status-batch', task_status_batch_api, name="api_task_status_batch"),
    path('api/v1/identify-tasks/<int:uid>', task_detail_api, name="api_task_detail"),
    path('api/v1/identify-tasks/<int:uid>/status', task_status_api, name="api_task_status"),
    path('api/v1/identify-tasks/<int:uid>/update', task_update_api, name="api_task_update"),
    path('api/v1/identify-tasks/<int:uid>/operate', task_operate_api, name="api_task_operate"),
    path('api/v1/identify-tasks/<int:uid>/delete', task_delete_api, name="api_task_delete"),
    path('api/v1/identify-tasks/<int:uid>/facets', auto_scan_result.task_facet_api, name="api_task_facet"),
    path('api/v1/identify-tasks/<int:uid>/results', auto_scan_result.task_result_api, name="api_task_results"),
    path('api/v1/identify-tasks/result/download', auto_scan_result.TaskResult_download, name="api_identify_result_download"),

    # ======================== 批量任务 API ========================
    path('api/v1/batch-tasks', batch_task_list_api, name="api_batch_task_list"),
    path('api/v1/batch-tasks/batch-delete', batch_task_batch_delete_api, name="api_batch_task_batch_delete"),
    path('api/v1/batch-tasks/choices', batch_task_choices_api, name="api_batch_task_choices"),
    path('api/v1/batch-tasks/plugins', batch_task_plugins_api, name="api_batch_task_plugins"),
    path('api/v1/batch-tasks/history-files', batch_task_history_files_api, name="api_batch_task_history_files"),
    path('api/v1/batch-tasks/history-engine-results', batch_task_history_engine_results, name="api_batch_task_history_engine_results"),
    path('api/v1/batch-tasks/status-batch', batch_task_status_batch_api, name="api_batch_task_status_batch"),
    path('api/v1/batch-tasks/create', batch_task_create_api, name="api_batch_task_create"),
    path('api/v1/batch-tasks/<int:uid>', batch_task_detail_api, name="api_batch_task_detail"),
    path('api/v1/batch-tasks/<int:uid>/status', batch_task_status_api, name="api_batch_task_status"),
    path('api/v1/batch-tasks/<int:uid>/update', batch_task_update_api, name="api_batch_task_update"),
    path('api/v1/batch-tasks/<int:uid>/operate', batch_task_operate_api, name="api_batch_task_operate"),
    path('api/v1/batch-tasks/<int:uid>/delete', batch_task_delete_api, name="api_batch_task_delete"),
    path('api/v1/batch-tasks/<int:uid>/exp-detail', batch_task_exp_detail_api, name="api_batch_task_exp_detail"),

    # ======================== 目录扫描任务 API ========================
    path('api/v1/dirscan-tasks', dirscan_list_api, name="api_dirscan_list"),
    path('api/v1/dirscan-tasks/batch-delete', dirscan_batch_delete_api, name="api_dirscan_batch_delete"),
    path('api/v1/dirscan-tasks/create', dirscan_create_api, name="api_dirscan_create"),
    path('api/v1/dirscan-tasks/status-batch', dirscan_status_batch_api, name="api_dirscan_status_batch"),
    path('api/v1/dirscan-tasks/<int:uid>', dirscan_detail_api, name="api_dirscan_detail"),
    path('api/v1/dirscan-tasks/<int:uid>/status', dirscan_status_api, name="api_dirscan_status"),
    path('api/v1/dirscan-tasks/<int:uid>/update', dirscan_update_api, name="api_dirscan_update"),
    path('api/v1/dirscan-tasks/<int:uid>/operate', dirscan_operate_api, name="api_dirscan_operate"),
    path('api/v1/dirscan-tasks/<int:uid>/delete', dirscan_delete_api, name="api_dirscan_delete"),

    # ======================== 字典组管理 API ========================
    path('api/v1/dict-groups', dict_group_list_api, name="api_dict_groups_list"),
    path('api/v1/dict-groups/batch-delete', dict_group_batch_delete_api, name="api_dict_groups_batch_delete"),
    path('api/v1/dict-groups/create', dict_group_create_api, name="api_dict_groups_create"),
    path('api/v1/dict-groups/<int:uid>', dict_group_detail_api, name="api_dict_groups_detail"),
    path('api/v1/dict-groups/<int:uid>/update', dict_group_update_api, name="api_dict_groups_update"),
    path('api/v1/dict-groups/<int:uid>/delete', dict_group_delete_api, name="api_dict_groups_delete"),

    # ======================== 资产检索 API ========================
    path("api/v1/assets/search", auto_scan_result.global_asset_search_api, name="api_global_asset_search"),
    path("api/v1/assets/facets", auto_scan_result.global_facet_api, name="api_global_facet"),
    path("api/v1/assets/port-overview", auto_scan_result.port_overview_more, name="api_port_overview"),
    path("api/v1/assets/export", auto_scan_result.asset_export, name="api_asset_export"),
    path("api/v1/ip-detail", auto_scan_result.ip_detail_api, name="api_ip_detail"),
    path("api/v1/assets/dirscan-results", auto_scan_result.dirscan_results_api, name="api_dirscan_results"),
    path("api/v1/assets/dirscan-results/filters", auto_scan_result.dirscan_results_filters_api, name="api_dirscan_results_filters"),
    path("api/v1/identify-results/<int:result_id>/html", auto_scan_result.task_result_html, name="api_identify_result_html"),
    path("api/v1/identify-results/<int:result_id>/vuln-result", auto_scan_result.vuln_result_text, name="api_identify_result_vuln"),

    # ======================== CEYE 配置 API ========================
    path('api/v1/ceye-config', ceye_config.ceye_config_api, name="api_ceye_config"),

    # ======================== AI模型配置 API ========================
    path('api/v1/ai-model-configs', ai_model_config_api, name="api_ai_model_configs"),
    path('api/v1/ai-model-configs/<int:uid>', ai_model_config_detail_api, name="api_ai_model_configs_detail"),

    # ======================== PoC生成任务 API ========================
    path('api/v1/poc-gen-tasks', poc_gen_task_api, name="api_poc_gen_tasks"),
    path('api/v1/poc-gen-tasks/<int:uid>', poc_gen_task_detail_api, name="api_poc_gen_tasks_detail"),
    path('api/v1/poc-gen-tasks/<int:uid>/generate', poc_gen_task_generate_api, name="api_poc_gen_tasks_generate"),
    path('api/v1/poc-gen-tasks/<int:uid>/save-to-exp', poc_gen_task_save_to_exp_api, name="api_poc_gen_tasks_save_to_exp"),
    path('api/v1/poc-gen-tasks/<int:uid>/preview-prompt', poc_gen_task_preview_prompt_api, name="api_poc_gen_tasks_preview_prompt"),
    path('api/v1/poc-gen-tasks/<int:uid>/retry', poc_gen_task_retry_api, name="api_poc_gen_tasks_retry"),

    # ======================== 导出任务 API ========================
    path("api/v1/export-tasks", export_task_list_api, name="api_export_tasks_list"),
    path("api/v1/export-tasks/batch-delete", export_task_batch_delete_api, name="api_export_tasks_batch_delete"),
    path("api/v1/export-tasks/<int:task_id>/download", export_task_download, name="api_export_task_download"),

    # ======================== 目标文件管理 API ========================
    path("api/v1/target-files", target_file_list_api, name="api_target_file_list"),
    path("api/v1/target-files/upload", target_file_upload_api, name="api_target_file_upload"),
    path("api/v1/target-files/batch-delete", target_file_batch_delete_api, name="api_target_file_batch_delete"),
    path("api/v1/target-files/batch-delete-confirm", target_file_batch_delete_confirm_api, name="api_target_file_batch_delete_confirm"),
    path("api/v1/target-files/<path:filename>/download", target_file_download_api, name="api_target_file_download"),
    path("api/v1/target-files/<path:filename>/delete-confirm", target_file_delete_confirm_api, name="api_target_file_delete_confirm"),
    path("api/v1/target-files/<path:filename>", target_file_delete_api, name="api_target_file_delete"),

    # ======================== 文件托管 API ========================
    path("api/v1/hosted-files", hosted_file_list_api, name="api_hosted_file_list"),
    path("api/v1/hosted-files/upload", hosted_file_upload_api, name="api_hosted_file_upload"),
    path("api/v1/hosted-files/<int:file_id>/rename", hosted_file_rename_api, name="api_hosted_file_rename"),
    path("api/v1/hosted-files/<int:file_id>/access", hosted_file_access_api, name="api_hosted_file_access"),
    path("api/v1/hosted-files/<int:file_id>/note", hosted_file_note_api, name="api_hosted_file_note"),
    path("api/v1/hosted-files/<int:file_id>", hosted_file_delete_api, name="api_hosted_file_delete"),

    # ======================== 文件托管公开下载 ========================
    path("files/<int:file_id>/<path:filename>", hosted_file_download, name="hosted_file_download"),

    # ======================== React 壳页（直连 Django 兜底） ========================
    path('react-shell', _serve_react_shell),
    path('react-shell/<path:subpath>', _serve_react_shell),

    # ======================== 路由兜底 ========================
    path('', RedirectView.as_view(url='/login', permanent=False)),
    # 未匹配的 URL 统一跳到 /react-shell/dashboard
    re_path(r'^(?!api/|static/|login|logout|react-shell/).*$', RedirectView.as_view(url='/react-shell/dashboard', permanent=False)),
]

# DEBUG=True 时由 Django 直接提供 STATIC_ROOT 下的静态文件（如运行时写入的 favicon 图标）
# DEBUG=False 时 static() 返回空列表，不影响生产环境（Nginx 接管 /static/）
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
