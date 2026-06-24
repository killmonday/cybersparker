import codecs
import csv
from datetime import datetime
import io
import os
from threading import Thread
import traceback
from django.shortcuts import render
import requests
from app_cybersparker import models
from app_cybersparker.utils.pagination import Pagination
from django.db.models import Q

from app_cybersparker.utils.bootstrap import BootStrapModelForm
from django.http import HttpResponse, JsonResponse
import cybersparker.settings as sett


pwd = sett.THIS_DIR
def error_log(e_info,tips,time):
    now_time = datetime.now().strftime("%Y-%m-%d")
    error_log_path = pwd + "/../error_log/" + now_time + "_error-log.txt"
    try:
        with open (error_log_path,"a+") as f:
            f.write(f"[expload {tips}] {time} : " +  e_info + "\n")
            f.close()
    except:
        pass

class ModelForm(BootStrapModelForm):
    bootstrap_exclude_fields = ['target']
    class Meta:
        model = models.auto_scan_exp_result
        exclude = []
  
def list(request,uid):
    task_name = models.auto_scan_tasks.objects.filter(id=uid).values("task_name").first()
    Task_name = task_name["task_name"]
    search_data = request.GET.get('q', "")
    if search_data:
        queryset = models.auto_scan_exp_result.objects.filter(Q(target__contains=search_data)| Q(result__contains=search_data),task_id=uid, task_type=1)
    else:
        queryset = models.auto_scan_exp_result.objects.filter(task_id=uid, task_type=1).order_by("-id")
    page_object = Pagination(request, queryset)
    context = {
        "task_name": str(Task_name),
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        "search_data": search_data,
        "task_id": uid
    }
    return render(request, 'project/expload/task_manage/auto_scan_exp_result.html', context)

def delete(request):
    uid = request.GET.get("uid")
    queryset = models.auto_scan_exp_result.objects.filter(id=uid).exists()
    if queryset:
        models.auto_scan_exp_result.objects.filter(id=uid).delete()
        return JsonResponse({"status":True}) 
    return JsonResponse({"status":False,"error":"Data does not exist"})

def download(request):
    try:
        task_id = request.GET.get("id")
        queryset = models.auto_scan_exp_result.objects.filter(task_id=task_id, task_type=1).select_related('EXP_id')
        task_queryset = models.auto_scan_tasks.objects.filter(id=task_id).values("task_name").first()
        task_name = task_queryset["task_name"]

        response = HttpResponse(content_type="text/csv")
        response['Content-Disposition'] = 'attachment; filename=EXPreuslt.csv'

        csv_data = io.StringIO()
        writer = csv.writer(csv_data, delimiter=',', quotechar='"', quoting=csv.QUOTE_ALL, lineterminator='\n')

        headers = ["id",'task_name','target','product', 'exp','result','creatime',]
        writer.writerow(headers)

        for item in queryset:
            creatime = item.creatime
            createtime_str = creatime.strftime("%Y-%m-%d %H:%M:%S") 
            row = [str(item.id),str(task_name),item.target,item.product,str(item.EXP_id.title),item.result, createtime_str]  
            writer.writerow(row) 

        response.write(codecs.BOM_UTF8)
        response.write(csv_data.getvalue().encode('utf-8'))
        csv_data.close()
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response
    except Exception as e:
        traceback.print_exc()
        e_info = f"exception, {e.__traceback__.tb_frame.f_globals['__file__']}, line: {e.__traceback__.tb_lineno}\n{str(e)}\n"
        tips = "TaskResult_download error"
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        error_log(e_info,tips,time_str)
        response = HttpResponse(content_type="text/csv")
        response['Content-Disposition'] = 'attachment; filename=EXPreuslt.csv' 
        return response
    
def operate(request):
    operate  = request.POST.get("operate")
    uid_list = request.POST.getlist("contents[]")
    if len(uid_list) == 0:
        return JsonResponse({"status":False,"error":"no object selected"})
    if operate =="delete":
        for uid in uid_list:
            data_exists = models.auto_scan_exp_result.objects.filter(id=uid).exists()
            if not data_exists:
                return JsonResponse({"status":False,"error":"Data does not exist"})
            data_exists = models.auto_scan_exp_result.objects.filter(id=uid).delete()
        return JsonResponse({"status":True})
    