from datetime import datetime
import os
import re
from django.http import JsonResponse
from django.shortcuts import render
from app_cybersparker import models
from app_cybersparker.utils.pagination import Pagination
from django.db.models import Q

from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django.http import JsonResponse
import cybersparker.settings as sett
from django.utils import timezone
from django.db.models import Sum
from django.db.models import Count
from django.db.models import Case, CharField, Value, When

from app_cybersparker.services.scheduler_runtime_service import get_runtime_diagnostics


def dashboard_api(request):
    exp_total = models.EXP.objects.count()
    finger_total = models.fingerPrint.objects.count()
    identify_total = models.auto_scan_indentify_result.objects.count()
    exp_result_total = models.auto_scan_exp_result.objects.count() + models.EXPTask_result.objects.count()

    cards = [
        {"name": "插件", "count": exp_total},
        {"name": "指纹", "count": finger_total},
        {"name": "识别结果", "count": identify_total},
        {"name": "漏洞结果", "count": exp_result_total},
    ]

    top_exp: dict = {}
    for item in models.auto_scan_exp_result.objects.values('EXP_id__title').annotate(count=Count('EXP_id')).order_by('-count')[:10]:
        top_exp[item['EXP_id__title'] or '(未命名)'] = item['count']
    for item in models.EXPTask_result.objects.values('plugin_name').annotate(count=Count('id')).order_by('-count')[:10]:
        name = item['plugin_name'] or '(未命名)'
        top_exp[name] = top_exp.get(name, 0) + item['count']
    top_exp_list = sorted(top_exp.items(), key=lambda x: x[1], reverse=True)[:15]

    type_choices = (
        (1, "Command Execute"), (2, "Code Execute"), (3, "sql inject"),
        (4, "information leakage"), (5, "File upload"), (6, "File Reading"),
        (7, "Directory Traversal"), (8, "Cross-site request forgery"),
        (9, "Identity bypass"), (10, "weak password"), (11, "Path leakage"),
        (12, "other"),
    )
    case_stmts = [When(Type=c[0], then=Value(c[1])) for c in type_choices]
    exp_types_qs = models.EXP.objects.values('Type').annotate(
        count=Count('Type'),
        type_str=Case(*case_stmts, output_field=CharField()),
    ).order_by('-count')
    exp_types = [{"name": item['type_str'] or f"Type {item['Type']}", "count": item['count']} for item in exp_types_qs]

    return JsonResponse({
        "cards": cards,
        "top_exp": top_exp_list,
        "exp_types": exp_types,
        "legacy_list_url": "/Dashboards",
    })


def runtime_diagnostics(request):
    data = get_runtime_diagnostics(request.GET.get("task_type"), request.GET.get("task_id"))
    return JsonResponse(data)


def index(request):
    exp_total_count = models.EXP.objects.count()
    fingerprint_total_count = models.fingerPrint.objects.count()
    indentify_result_total_count = models.auto_scan_indentify_result.objects.count()
    exp_result_total_count = int(models.auto_scan_exp_result.objects.count()) + int(models.EXPTask_result.objects.count())
    
    # 统计指定字段的值和数量，取排名前15个值
    indentify_country_counts = models.auto_scan_indentify_result.objects.values('country').annotate(count=Count('country')).order_by('-count')[:15]
    # 统计指定字段的值和数量，取数量排名前20个的值
    indentify_port_counts = models.auto_scan_indentify_result.objects.values('port').annotate(count=Count('port')).order_by('-count')[:20]
    # print(indentify_port_counts)  #<QuerySet [{'country': 'None', 'count': 1}]>
    
    # exp结果最多的漏洞
    top_exp_data_dict = {
        item['EXP_id__title']: item["count"]
        for item in models.auto_scan_exp_result.objects.values('EXP_id__title').annotate(count=Count('EXP_id')).order_by('-count')[:10]
    }
    # 添加第二个表的统计数据
    for item in (
        models.EXPTask_result.objects.values('plugin_name')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    ):
        if item['plugin_name'] in top_exp_data_dict:
            top_exp_data_dict[item['plugin_name']] += item['count']
        else:
            top_exp_data_dict[item['plugin_name']] = item['count']
    
    # print("@@@@",top_exp_data_dict)  #{'test': 15, 'qnap': 2}

    # exp类型分布情况
    # 定义类型选择
    type_choices = (
        (1, "Command Execute"),
        (2, "Code Execute"),
        (3, "sql inject"),
        (4, "information leakage"),
        (5, "File upload"),
        (6, "File Reading"),
        (7, "Directory Traversal"),
        (8, "Cross-site request forgery"),
        (9, "Identity bypass"),
        (10, "weak password"),
        (11, "Path leakage"),
        (12, "other"),
    )
    # 构建Case语句，将整数类型映射为可读的字符串
    case_statements = [When(Type=choice[0], then=Value(choice[1])) for choice in type_choices]

    # 执行数据库查询，并在查询中应用Case语句
    exp_type_queryset = models.EXP.objects.values('Type').annotate(
        count=Count('Type'),
        type_str=Case(
            *case_statements,
            output_field=CharField()
        )
    )
    print(exp_type_queryset)  #<QuerySet [{'Type': 1, 'count': 1, 'type_str': 'Command Execute'}, {'Type': 6, 'count': 1, 'type_str': 'File Reading'}, {'Type': 11, 'count': 1, 'type_str': 'Path leakage'}]>
    
    data = [
        {"name": "EXP", "count": exp_total_count},
        {"name": "指纹", "count": fingerprint_total_count},
        {"name": "识别结果", "count": indentify_result_total_count},
        {"name": "EXP结果", "count": exp_result_total_count}
    ]
    context = {
        "data":data,
        "country_counts":indentify_country_counts,
        "port_counts":indentify_port_counts,
        "top_exp_data_dict": top_exp_data_dict,
        "exp_type_queryset":exp_type_queryset,
    }
    return render(request, 'project/expload/Dashboards.html', context)