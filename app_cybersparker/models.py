from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.utils import timezone


class AssetZone(models.Model):
    """扫描区域 — 公网/内网1/客户A办公网 等"""
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=256, blank=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name


class fingerPrint(models.Model):
    product = models.CharField(verbose_name="product",max_length=128)
    condition = models.TextField(unique=True,verbose_name="condition")
    create_time = models.DateTimeField(verbose_name="create time",default=timezone.now)

    def __str__(self):
        return self.product

class cveExtensions(models.Model):
    CVE = models.ForeignKey(verbose_name="plugin", to="EXP", to_field="id", on_delete=models.CASCADE)
    type_choices = (
        (1, "Verify"),
        (2, "Command Execute"),
        (3, "Code Execute"),
        (4, "File Reading"),
        (5, "Attact"),
    )
    function = models.SmallIntegerField(verbose_name="Type",choices=type_choices, default=1)

class Tag(models.Model):
    name = models.CharField(max_length=128, unique=True, db_index=True)

    def __str__(self):
        return self.name

class EXP(models.Model):
    title = models.CharField(unique=True,verbose_name="plugin name",max_length=128)
    CVE = models.CharField(verbose_name="CVE",max_length=128, blank=True, default="")
    severity_choices = (
        ("critical", "严重"),
        ("high", "高危"),
        ("medium", "中危"),
        ("low", "低危"),
        ("info", "信息"),
    )
    severity = models.CharField(max_length=10, choices=severity_choices, blank=True, default="", db_index=True)
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
    Type = models.SmallIntegerField(verbose_name="Type",choices=type_choices, default=1)
    time = models.DateField(verbose_name="Exposure time",null=True,blank=True)
    creat_time = models.DateTimeField(verbose_name="create time",default=timezone.now)
    update_time = models.DateTimeField(verbose_name="update time",null=True, blank=True)
    pluginLanguage_choices =(
        (1,"python3"),
        (2,"nuclei_yaml"),
        # (2,"python2"),
        # (3,"yaml"),
        # (4,"php"),
    )
    plugin_language = models.SmallIntegerField(verbose_name="plugin_language",choices=pluginLanguage_choices,default=1)
    use_status = (
        (1, "True"),
        (2, "false"),
    )
    use = models.SmallIntegerField(verbose_name="join use",choices=use_status,default=1)
    poc_type_choices =(
        (1,"File upload"),
        (2,"Custom Add"),
    )
    poc_type = models.SmallIntegerField(verbose_name="poc_type",choices=poc_type_choices,default=1)
    poc = models.FileField(verbose_name="poc", max_length=128, upload_to='EXP_plugin/')
    poc_content = models.TextField(verbose_name="poc_content",null=True,blank=True)
    tags = models.ManyToManyField("Tag", blank=True, related_name="exps")

    def __str__(self):
        return "【" + self.CVE + "】" + self.title

class EXPTask(models.Model):
    task_name = models.CharField(unique=True,verbose_name="task_name",max_length=128)
    EXP = models.ForeignKey(verbose_name="plugin", to="EXP", to_field="id", on_delete=models.CASCADE)

    type_choices = (
        (1, "Verify"),
        (2, "Attact"),
    )
    taskType = models.SmallIntegerField(verbose_name="task_type", choices=type_choices, default=1)
    cmd_input = models.CharField(verbose_name="cmd_input",max_length=128,null=True, blank=True)

    thread_num = models.SmallIntegerField(verbose_name="thread_num",default=100)
    sleep_time = models.SmallIntegerField(verbose_name="sleep_time",default=0)
    current_line = models.IntegerField(verbose_name="current_line",default=1)

    inputType_choices = (
        (1, "from file"),
        (2, "history result"),
    )
    input_type = models.SmallIntegerField(verbose_name="input_type", choices=inputType_choices, default=1)
    target = models.FileField(verbose_name="target", max_length=128, upload_to='EXP_input/',null=True, blank=True)
    creat_time = models.DateTimeField(verbose_name="creat_time",auto_now_add=True)
    update_time = models.DateTimeField(verbose_name="update time",null=True, blank=True)
    status_choices = (
        (1, "finish"),
        (2, "running"),
        (3, "stop"),
    )
    status = models.SmallIntegerField(verbose_name="status", choices=status_choices, default=3)
    process = models.CharField(verbose_name="process",max_length=128,default="0%")
    startTime = models.DateTimeField(verbose_name="start time",null=True, blank=True)
    endTime = models.DateTimeField(verbose_name="end time",null=True, blank=True)
    remark = models.CharField(verbose_name="remark",max_length=128, null=True, blank=True)

class EXPTask_result(models.Model):
    task_type_choices = (
        (1, "Single exp"),
        (2, "Batch exp"),
    )
    task_type = models.SmallIntegerField(verbose_name="task_type", choices=task_type_choices, default=1)
    task_id = models.IntegerField(verbose_name="task_id", db_index=True)
    plugin_name = models.CharField(verbose_name="plugin_name",max_length=128,default="")
    target = models.CharField(verbose_name="target",max_length=128)
    result = models.TextField(verbose_name="task result")
    creatime = models.DateTimeField(verbose_name="crea time",default=timezone.now)
    update_time = models.DateTimeField(verbose_name="update time",null=True, blank=True)

class batch_EXPTask(models.Model):
    task_name = models.CharField(unique=True,verbose_name="task_name",max_length=128)
    zone = models.ForeignKey("AssetZone", on_delete=models.PROTECT)
    EXP = models.CharField(verbose_name="plugin",max_length=128)
    run_mode_choices = (
        (1, "线程"),
        (2, "协程"),
    )
    run_mode = models.SmallIntegerField(verbose_name="运行方式", choices=run_mode_choices, default=1)
    thread_num = models.SmallIntegerField(verbose_name="thread_num",default=100)
    sleep_time = models.SmallIntegerField(verbose_name="sleep_time",default=0)
    http_timeout = models.SmallIntegerField(verbose_name="HTTP超时(秒)", default=10, blank=True)
    inputType_choices = (
        (1, "from file"),
        (2, "history vuln assets"),
        (3, "history upload files"),
        (4, "cyberspace engine"),
        (5, "history cyberspace results"),
        (6, "从检索语句导入"),
    )
    input_type = models.SmallIntegerField(verbose_name="input_type", choices=inputType_choices, default=1)
    search_query = models.TextField(verbose_name="检索语句", null=True, blank=True)
    parsed_query = models.JSONField(verbose_name="冻结的解析树", null=True, blank=True)
    frozen_max_id = models.IntegerField(verbose_name="冻结时资产max_id", default=0)
    last_id = models.IntegerField(verbose_name="keyset游标", default=0)
    history_files = models.CharField(verbose_name="history_files", max_length=1000, null=True, blank=True)
    target = models.FileField(verbose_name="target", max_length=128, upload_to='EXP_input/', null=True, blank=True)
    engine_type_choices = (
        ("fofa", "fofa"),
        ("zoomeye", "zoomeye"),
        ("quake", "quake"),
        ("hunter", "hunter"),
        ("shodan", "shodan"),
    )
    engine_type = models.CharField(verbose_name="engine_type", max_length=20, choices=engine_type_choices, null=True, blank=True)
    engine_query = models.TextField(verbose_name="engine_query", null=True, blank=True)
    engine_max_assets = models.IntegerField(verbose_name="engine_max_assets", default=100, null=True, blank=True)
    engine_proxy_mode_choices = (
        (0, "follow engine config"),
        (1, "no proxy"),
        (2, "force proxy"),
    )
    engine_proxy_mode = models.SmallIntegerField(verbose_name="engine_proxy_mode", choices=engine_proxy_mode_choices, default=0, null=True, blank=True)
    engine_proxy = models.ForeignKey(verbose_name="engine_proxy", to="ProxySetting", to_field="id", on_delete=models.SET_NULL, null=True, blank=True)
    proxy = models.ForeignKey(verbose_name="插件代理", to="ProxySetting", to_field="id", on_delete=models.SET_NULL, null=True, blank=True, related_name="batch_plugin_proxy")
    reuse_engine_data = models.BooleanField(verbose_name="reuse_engine_data", default=False)
    task_type_choices = (
        (1, "Verify"),
        (2, "Attact"),
    )
    task_type = models.SmallIntegerField(verbose_name="task_type", choices=task_type_choices, default=1)
    cmd_input = models.CharField(verbose_name="cmd_input", max_length=128, null=True, blank=True)
    exp_select_mode_choices = (
        (1, "手动选择"),
        (2, "按条件筛选"),
    )
    exp_select_mode = models.SmallIntegerField(verbose_name="选EXP方式", choices=exp_select_mode_choices, default=1)
    severity_filter = models.JSONField(verbose_name="危害等级筛选", null=True, blank=True)
    tag_filter = models.JSONField(verbose_name="标签筛选", null=True, blank=True)
    filter_logic_choices = (
        ("AND", "AND"),
        ("OR", "OR"),
    )
    filter_logic = models.CharField(verbose_name="筛选逻辑", max_length=3, choices=filter_logic_choices, default="AND")
    task_args = models.TextField(verbose_name="自定义参数(JSON)", null=True, blank=True)
    remark = models.CharField(verbose_name="remark",max_length=128, null=True, blank=True)
    creat_time = models.DateTimeField(verbose_name="creat_time",auto_now_add=True)
    update_time = models.DateTimeField(verbose_name="update time",null=True, blank=True)
    status_choices = (
        (1, "finish"),
        (2, "running"),
        (3, "stop"),
        (4, "pause"),
    )
    status = models.SmallIntegerField(verbose_name="status", choices=status_choices, default=3, db_index=True)
    process = models.CharField(verbose_name="process",max_length=128,default="0%")
    queued = models.BooleanField(verbose_name="queued", default=False)
    failed = models.BooleanField(verbose_name="failed", default=False)
    dispatch_token = models.CharField(verbose_name="dispatch token", max_length=64, null=True, blank=True)
    owner = models.CharField(verbose_name="owner", max_length=128, null=True, blank=True)
    stop_requested = models.BooleanField(verbose_name="stop requested", default=False)
    pause_requested = models.BooleanField(verbose_name="pause requested", default=False)
    heartbeat_at = models.DateTimeField(verbose_name="heartbeat at", null=True, blank=True)
    last_error = models.TextField(verbose_name="last error", null=True, blank=True)
    startTime = models.DateTimeField(verbose_name="start time",null=True, blank=True)
    endTime = models.DateTimeField(verbose_name="end time",null=True, blank=True)

    def save(self, *args, **kwargs):
        if getattr(self, "input_type", None) in (4, 5):
            self.zone_id = 1  # 引擎输入源固定公网（id=1）
        if self.zone_id is None:
            # 公网区域由迁移 0075 创建，id 固定为 1。
            # 兜底时直接赋值 zone_id。
            self.zone_id = 1
        super().save(*args, **kwargs)

class exp_relate_fingerprint(models.Model):
    EXP_id = models.ForeignKey(verbose_name="plugin", to="EXP", to_field="id", on_delete=models.CASCADE)
    fingerprint_id = models.ForeignKey(verbose_name="plugin", to="fingerPrint", to_field="id", on_delete=models.CASCADE)

    class Meta:
        unique_together = ('EXP_id', 'fingerprint_id')

class auto_scan_tasks(models.Model):
    task_name = models.CharField(unique=True,verbose_name="task_name",max_length=128)
    zone = models.ForeignKey("AssetZone", on_delete=models.PROTECT)
    thread_num = models.SmallIntegerField(verbose_name="thread_num",default=100)
    vulnerability_thread_num = models.SmallIntegerField(verbose_name="漏洞扫描线程数", default=40)
    # async_num = models.SmallIntegerField(verbose_name="async_num",default=10)
    sleep_time = models.SmallIntegerField(verbose_name="sleep_time",default=0)
    http_timeout = models.SmallIntegerField(verbose_name="HTTP超时(秒)",default=10)
    current_line = models.IntegerField(verbose_name="current_line",default=1)
    target = models.FileField(verbose_name="target", max_length=128, upload_to='EXP_input/', null=True, blank=True)
    inputType_choices = (
        (1, "from file"),
        (2, "fscanx输出文件"),
        (3, "history upload files"),
        (4, "cyberspace engine"),
        (5, "history cyberspace results"),
        (6, "从检索语句导入"),
    )
    input_type = models.SmallIntegerField(verbose_name="input_type", choices=inputType_choices, default=1)
    search_query = models.TextField(verbose_name="检索语句", null=True, blank=True)
    parsed_query = models.JSONField(verbose_name="冻结的解析树", null=True, blank=True)
    frozen_max_id = models.IntegerField(verbose_name="冻结时资产max_id", default=0)
    last_id = models.IntegerField(verbose_name="keyset游标", default=0)
    history_files = models.CharField(verbose_name="history_files", max_length=1000, null=True, blank=True)
    engine_type_choices = (
        ("fofa", "fofa"),
        ("zoomeye", "zoomeye"),
        ("quake", "quake"),
        ("hunter", "hunter"),
        ("shodan", "shodan"),
    )
    engine_type = models.CharField(verbose_name="engine_type", max_length=20, choices=engine_type_choices, null=True, blank=True)
    engine_query = models.TextField(verbose_name="engine_query", null=True, blank=True)
    engine_max_assets = models.IntegerField(verbose_name="engine_max_assets", default=100, null=True, blank=True)
    engine_proxy_mode_choices = (
        (0, "follow engine config"),
        (1, "no proxy"),
        (2, "force proxy"),
    )
    engine_proxy_mode = models.SmallIntegerField(verbose_name="engine_proxy_mode", choices=engine_proxy_mode_choices, default=0, null=True, blank=True)
    engine_proxy = models.ForeignKey(verbose_name="engine_proxy", to="ProxySetting", to_field="id", on_delete=models.SET_NULL, null=True, blank=True, related_name="auto_scan_engine_proxy")
    reuse_engine_data = models.BooleanField(verbose_name="reuse_engine_data", default=False)
    expScan_start = (
        (0, "不进行漏洞扫描"),
        (1, "Web扫描后漏洞扫描"),
        (2, "仅漏洞扫描（跳过Web探测）"),
    )
    Vulnerability_scanning = models.SmallIntegerField(verbose_name="漏洞扫描模式",choices=expScan_start, default=0)
    task_args = models.TextField(verbose_name="自定义参数(JSON)", null=True, blank=True)
    proxy = models.ForeignKey(verbose_name="proxy", to="ProxySetting", to_field="id", on_delete=models.SET_NULL, null=True, blank=True, related_name="auto_scan_http_proxy")
    remark = models.CharField(verbose_name="remark",max_length=128, null=True, blank=True)
    fscanx_file = models.FileField(verbose_name="fscanx输出文件", max_length=256, upload_to='EXP_input/', null=True, blank=True)
    conflict_strategy_choices = (
        (1, "覆盖"),
        (2, "跳过"),
    )
    conflict_strategy = models.SmallIntegerField(verbose_name="冲突策略", choices=conflict_strategy_choices, default=1, blank=True)
    creat_time = models.DateTimeField(verbose_name="creat_time",auto_now_add=True)
    update_time = models.DateTimeField(verbose_name="update time",null=True, blank=True)
    status_choices = (
        (1, "finish"),
        (2, "running"),
        (3, "stop"),
        (4, "pause"),
    )
    status = models.SmallIntegerField(verbose_name="status", choices=status_choices, default=3, db_index=True)
    phase_choices = (
        (1, "正在Web扫描"),
        (2, "正在漏洞扫描"),
        (3, "全部完成"),
    )
    phase = models.SmallIntegerField(verbose_name="phase", choices=phase_choices, default=3)
    pause_requested = models.BooleanField(verbose_name="pause requested", default=False)
    process = models.CharField(verbose_name="process", max_length=128, default="0%")
    queued = models.BooleanField(verbose_name="queued", default=False)
    failed = models.BooleanField(verbose_name="failed", default=False)
    dispatch_token = models.CharField(verbose_name="dispatch token", max_length=64, null=True, blank=True)
    owner = models.CharField(verbose_name="owner", max_length=128, null=True, blank=True)
    stop_requested = models.BooleanField(verbose_name="stop requested", default=False)
    heartbeat_at = models.DateTimeField(verbose_name="heartbeat at", null=True, blank=True)
    last_error = models.TextField(verbose_name="last error", null=True, blank=True)
    startTime = models.DateTimeField(verbose_name="start time",null=True, blank=True)
    endTime = models.DateTimeField(verbose_name="end time",null=True, blank=True)

    def save(self, *args, **kwargs):
        if getattr(self, "input_type", None) in (4, 5):
            self.zone_id = 1  # 引擎输入源固定公网（id=1）
        # 非引擎输入源且 zone 为空时，默认公网（ModelForm 未填或前端旧版本漏传）
        if self.zone_id is None:
            # 公网区域由迁移 0075 创建，id 固定为 1。
            # 兜底时直接赋值 zone_id。
            self.zone_id = 1
        super().save(*args, **kwargs)

class auto_scan_exp_result(models.Model):
    task_id = models.IntegerField(verbose_name="task_id")
    task_type = models.SmallIntegerField(verbose_name="任务类型: 1=自动扫描 2=目录扫描 3=批量任务", default=1)
    identify_result_id = models.IntegerField(verbose_name="关联根资产ID", null=True, blank=True, db_index=True)
    EXP_id = models.ForeignKey(verbose_name="EXP_id", to="EXP", to_field="id", on_delete=models.CASCADE)
    product = models.CharField(verbose_name="product",max_length=128,default="")
    target = models.CharField(verbose_name="target",max_length=128)
    result = models.TextField(verbose_name="task result")
    creatime = models.DateTimeField(verbose_name="crea time",default=timezone.now)
    update_time = models.DateTimeField(verbose_name="update time",null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['task_type', 'target', 'task_id']),
        ]

class fscanx_service_detail(models.Model):
    """fscanx 导入的服务详情（弱口令/FTP清单/SMB清单/OS信息/RDP信息/漏洞资产等）"""
    RESULT_TYPE_CHOICES = (
        (1, "弱口令"),
        (2, "ftp文件清单"),
        (3, "smb文件清单"),
        (4, "os系统信息"),
        (5, "rdp信息"),
        (6, "漏洞资产信息"),
        (7, "网卡信息"),
        (8, "NetBios主机名"),
        (9, "MS17-010漏洞"),
        (10, "未授权访问"),
    )
    task = models.ForeignKey("auto_scan_tasks", on_delete=models.CASCADE, verbose_name="任务")
    protocol = models.CharField(verbose_name="协议", max_length=20)
    host = models.CharField(verbose_name="主机", max_length=255)
    port = models.IntegerField(verbose_name="端口")
    result_type = models.SmallIntegerField(verbose_name="成果类型", choices=RESULT_TYPE_CHOICES)
    result = models.TextField(verbose_name="结果内容")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        indexes = [
            models.Index(fields=["task_id", "host", "port"]),
        ]


class AssetTaskRelation(models.Model):
    """资产表与任务的关联关系"""
    task_id = models.IntegerField(verbose_name="任务ID")
    identify_result = models.ForeignKey(
        "auto_scan_indentify_result",
        on_delete=models.CASCADE,
        related_name="task_relations",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="关联时间")

    class Meta:
        unique_together = [("task_id", "identify_result_id")]


class auto_scan_indentify_result(models.Model):
    zone = models.ForeignKey("AssetZone", on_delete=models.PROTECT)
    products = ArrayField(models.CharField(max_length=128), default=list, blank=True)
    target = models.CharField(verbose_name="target",max_length=128)
    ip = models.CharField(verbose_name='ip', max_length=45)
    protocol = models.CharField(verbose_name='protocol', max_length=20)
    port = models.IntegerField(verbose_name="port")
    host = models.CharField(verbose_name="host", max_length=255, null=True, blank=True)
    uri_path = models.CharField(verbose_name="uri_path", max_length=512, default="", blank=True)
    country = models.CharField(verbose_name='country', max_length=64, null=True, blank=True)
    creatime = models.DateTimeField(verbose_name="crea time",default=timezone.now)
    update_time = models.DateTimeField(verbose_name="update time",null=True, blank=True)

    status_code = models.IntegerField(verbose_name="status_code",null=True, blank=True)
    header = models.TextField(verbose_name="header",null=True, blank=True)
    title = models.CharField(verbose_name="title",max_length=255,null=True, blank=True)
    html = models.TextField(verbose_name="html",null=True, blank=True)
    favicon = models.CharField(verbose_name="favicon", max_length=256, null=True, blank=True)
    favicon_md5 = models.CharField(verbose_name="favicon_md5", max_length=32, null=True, blank=True, db_index=True)
    cert_org = models.CharField(verbose_name="cert_org", max_length=255, null=True, blank=True)
    cert_org_unit = models.CharField(verbose_name="cert_org_unit", max_length=255, null=True, blank=True)
    cert_common_name = models.TextField(verbose_name="cert_common_name", null=True, blank=True)
    cert_serial = models.CharField(verbose_name="cert_serial", max_length=128, null=True, blank=True)
    province = models.CharField(verbose_name="province", max_length=64, null=True, blank=True)
    city = models.CharField(verbose_name="city", max_length=128, null=True, blank=True)
    isp = models.CharField(verbose_name="isp", max_length=64, null=True, blank=True)
    dir_products = ArrayField(models.CharField(max_length=128), verbose_name="目录产品", default=list, blank=True)
    source_type_choices = (
        (1, "auto_scan"),
        (2, "fscanx"),
    )
    source_type = models.SmallIntegerField(verbose_name="数据来源", choices=source_type_choices, default=1, null=True, blank=True)
    copyright = models.CharField(verbose_name="copyright", max_length=512, null=True, blank=True)
    icp = models.CharField(verbose_name="icp", max_length=128, null=True, blank=True)

    def clean(self):
        p = (self.uri_path or "").strip()
        if p == "/":
            p = ""
        self.uri_path = p[:512]

    def save(self, *args, **kwargs):
        # 写入路径硬约束：zone 不得为空。若上游漏传 zone，兜底为公网并记录异常。
        if self.zone_id is None:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(
                "auto_scan_indentify_result.save() zone_id is None, "
                "falling back to public zone. target=%s host=%s port=%s uri_path=%s",
                self.target, self.host, self.port, self.uri_path,
            )
            try:
                self.zone = AssetZone.objects.get(code="public")
            except AssetZone.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('zone', 'protocol', 'host', 'port', 'uri_path')
        indexes = [
            models.Index(fields=['ip', 'port']),
            models.Index(fields=['host']),
        ]


# Cascade-delete favicon file when last reference is removed
import os as _os
from django.db.models.signals import post_delete
from django.dispatch import receiver


@receiver(post_delete, sender='app_cybersparker.auto_scan_indentify_result')
def _cleanup_favicon_file(sender, instance, **kwargs):
    fav = (instance.favicon or '').strip()
    if not fav.startswith('/static/favicons/'):
        return
    md5 = (instance.favicon_md5 or '').strip()
    if md5 and not sender.objects.filter(favicon_md5=md5).exists():
        filepath = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
            'app_cybersparker', fav.lstrip('/'),
        )
        if _os.path.isfile(filepath):
            _os.remove(filepath)


class DirScanDictGroup(models.Model):
    name = models.CharField(verbose_name="组名", max_length=64, unique=True)
    description = models.CharField(verbose_name="描述", max_length=255, blank=True)
    creatime = models.DateTimeField(verbose_name="创建时间", default=timezone.now)

    def __str__(self):
        return self.name

class DirScanDict(models.Model):
    name = models.CharField(verbose_name="字典名", max_length=64, unique=True)
    paths = ArrayField(models.CharField(max_length=512), verbose_name="路径列表", default=list)
    groups = models.ManyToManyField(DirScanDictGroup, verbose_name="所属组", related_name='dicts')
    creatime = models.DateTimeField(verbose_name="创建时间", default=timezone.now)

    def __str__(self):
        return self.name


class AssetRootBinding(models.Model):
    """根资产绑定 — 固定某个 zone 下某个 protocol+host+port 对应的根资产"""
    zone = models.ForeignKey("AssetZone", on_delete=models.PROTECT)
    protocol = models.CharField(max_length=20)
    host = models.CharField(max_length=255)
    port = models.IntegerField()
    identify_result = models.ForeignKey(
        "auto_scan_indentify_result", on_delete=models.PROTECT,
        related_name="root_bindings",
    )

    class Meta:
        unique_together = ('zone', 'protocol', 'host', 'port')


class auto_scan_directory_result(models.Model):
    task_id = models.IntegerField(verbose_name="task_id")
    zone = models.ForeignKey("AssetZone", on_delete=models.PROTECT)
    root_identify_result = models.ForeignKey(
        "auto_scan_indentify_result", on_delete=models.PROTECT,
        null=True, blank=True, related_name="directory_results",
    )
    protocol = models.CharField(verbose_name="protocol", max_length=20)
    host = models.CharField(verbose_name="host", max_length=255)
    port = models.IntegerField(verbose_name="port")
    uri_path = models.CharField(verbose_name="uri_path", max_length=512)
    ip = models.CharField(verbose_name="ip", max_length=45, blank=True, default="")
    target = models.CharField(verbose_name="target", max_length=512, blank=True, default="")
    status_code = models.IntegerField(verbose_name="status_code", null=True, blank=True)
    header = models.TextField(verbose_name="header", null=True, blank=True)
    title = models.CharField(verbose_name="title", max_length=255, null=True, blank=True)
    html = models.TextField(verbose_name="html", null=True, blank=True)
    products = ArrayField(models.CharField(max_length=128), verbose_name="产品", default=list, blank=True)
    favicon = models.CharField(verbose_name="favicon", max_length=256, null=True, blank=True)
    favicon_md5 = models.CharField(verbose_name="favicon_md5", max_length=32, null=True, blank=True, db_index=True)
    cert_org = models.CharField(verbose_name="cert_org", max_length=255, null=True, blank=True)
    cert_org_unit = models.CharField(verbose_name="cert_org_unit", max_length=255, null=True, blank=True)
    cert_common_name = models.TextField(verbose_name="cert_common_name", null=True, blank=True)
    cert_serial = models.CharField(verbose_name="cert_serial", max_length=128, null=True, blank=True)
    content_length = models.IntegerField(verbose_name="响应体大小(字节)", null=True, blank=True)
    creatime = models.DateTimeField(verbose_name="创建时间", default=timezone.now)

    def save(self, *args, **kwargs):
        # 写入路径硬约束：zone 不得为空。若上游漏传 zone，兜底为公网并记录异常。
        if self.zone_id is None:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(
                "auto_scan_directory_result.save() zone_id is None, "
                "falling back to public zone. host=%s port=%s uri_path=%s",
                self.host, self.port, self.uri_path,
            )
            try:
                self.zone = AssetZone.objects.get(code="public")
            except AssetZone.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('zone', 'protocol', 'host', 'port', 'uri_path')
        indexes = [
            models.Index(fields=['task_id']),
            models.Index(fields=['host', 'port', 'protocol']),
        ]


class DirScanTask(models.Model):
    task_name = models.CharField(verbose_name="任务名", max_length=128, unique=True)
    zone = models.ForeignKey("AssetZone", on_delete=models.PROTECT)
    description = models.CharField(verbose_name="描述", max_length=512, blank=True)

    # 输入源
    source_tasks = ArrayField(models.IntegerField(), verbose_name="源任务ID列表", default=list, blank=True)
    INPUT_MODE_CHOICES = (
        (0, "手动选择任务"),
        (1, "全选所有任务"),
        (2, "从检索语句导入"),
    )
    input_mode = models.SmallIntegerField(verbose_name="输入模式", choices=INPUT_MODE_CHOICES, default=0)
    search_query = models.TextField(verbose_name="检索语句", null=True, blank=True)
    parsed_query = models.JSONField(verbose_name="冻结的解析树", null=True, blank=True)
    frozen_max_id = models.IntegerField(verbose_name="冻结时资产max_id", default=0)

    # 字典选择
    dicts = models.ManyToManyField(DirScanDict, verbose_name="字典", related_name='tasks')

    # 扫描配置
    pool_size = models.IntegerField(verbose_name="活跃池大小", default=200)
    concurrency = models.IntegerField(verbose_name="并发数", default=100)
    max_body_size = models.IntegerField(verbose_name="最大body大小(字节)", default=3145728)
    max_truncate_size = models.IntegerField(verbose_name="流式截断上限(字节)", default=1048576)

    # 代理
    proxy = models.ForeignKey("ProxySetting", verbose_name="代理", null=True, blank=True, on_delete=models.SET_NULL)

    # 漏洞扫描
    enable_vuln_scan = models.BooleanField(verbose_name="启用漏洞扫描", default=True)
    task_args = models.TextField(verbose_name="自定义参数(JSON)", null=True, blank=True)
    vuln_thread_num = models.SmallIntegerField(verbose_name="漏洞扫描线程数", default=60)
    sleep_time = models.SmallIntegerField(verbose_name="休眠时间(秒)", default=0)
    http_timeout = models.SmallIntegerField(verbose_name="HTTP超时(秒)", default=10, blank=True)

    # 状态管理
    status = models.SmallIntegerField(verbose_name="状态", default=0, choices=[
        (0, "待执行"), (1, "运行中"), (2, "暂停中"), (3, "已停止"), (4, "已完成"),
    ])
    phase = models.SmallIntegerField(verbose_name="阶段", default=0, choices=[
        (0, "未初始化"), (1, "Web扫描"), (2, "漏洞扫描"), (3, "回写清理"),
    ])
    progress_total = models.IntegerField(verbose_name="总进度", default=0)
    progress_done = models.IntegerField(verbose_name="已完成进度", default=0)
    shuffle_file = models.CharField(verbose_name="快照文件", max_length=512, blank=True)
    file_pos = models.IntegerField(verbose_name="文件读取位置", default=0)
    heartbeat_at = models.DateTimeField(verbose_name="心跳时间", null=True, blank=True)
    start_time = models.DateTimeField(verbose_name="开始时间", null=True, blank=True)
    end_time = models.DateTimeField(verbose_name="结束时间", null=True, blank=True)

    # Celery 调度
    dispatch_token = models.CharField(verbose_name="调度令牌", max_length=64, null=True, blank=True)
    owner = models.CharField(verbose_name="所有者", max_length=64, null=True, blank=True)
    queued = models.BooleanField(verbose_name="已入队", default=False)
    pause_requested = models.BooleanField(verbose_name="暂停请求", default=False)
    stop_requested = models.BooleanField(verbose_name="停止请求", default=False)

    creatime = models.DateTimeField(verbose_name="创建时间", default=timezone.now)
    update_time = models.DateTimeField(verbose_name="更新时间", auto_now=True)

    def save(self, *args, **kwargs):
        if self.zone_id is None:
            # 公网区域由迁移 0075 创建，id 固定为 1。
            # 兜底时直接赋值 zone_id。
            self.zone_id = 1
        super().save(*args, **kwargs)

    def clean(self):
        if self.input_mode == 0 and not self.source_tasks:
            from django.core.exceptions import ValidationError
            raise ValidationError("手动选择任务模式必须选择至少一个源任务")
        if self.input_mode == 2 and not self.search_query:
            from django.core.exceptions import ValidationError
            raise ValidationError("检索语句导入模式必须填写检索语句")

    def __str__(self):
        return self.task_name

class CyberspaceEngineSetting(models.Model):
    engine_type_choices = (
        ("fofa", "fofa"),
        ("zoomeye", "zoomeye"),
        ("quake", "quake"),
        ("hunter", "hunter"),
        ("shodan", "shodan"),
    )
    engine_type = models.CharField(verbose_name="engine_type", max_length=20, choices=engine_type_choices, unique=True)
    api_base_url = models.CharField(verbose_name="api_base_url", max_length=255)
    account_email = models.CharField(verbose_name="account_email", max_length=128, null=True, blank=True)
    api_key = models.CharField(verbose_name="api_key", max_length=255)
    use_proxy = models.BooleanField(verbose_name="use_proxy", default=False)
    proxy = models.ForeignKey(verbose_name="proxy", to="ProxySetting", to_field="id", on_delete=models.SET_NULL, null=True, blank=True)
    remark = models.CharField(verbose_name="remark", max_length=128, null=True, blank=True)
    update_time = models.DateTimeField(verbose_name="update_time", null=True, blank=True)

class ProxySetting(models.Model):
    protocol_choices = (
        (1, "http"),
        # (2, "https"),
        # (3, "socks4"),
        (4, "socks5"),
    )
    proxy_type  = models.SmallIntegerField(verbose_name="proxy_type ", choices=protocol_choices, default=1)
    proxy_address = models.CharField(verbose_name="proxy_address",max_length=128)
    proxy_port  = models.IntegerField(verbose_name="proxy_port")
    creatime = models.DateTimeField(verbose_name="crea time",default=timezone.now)
    remark = models.CharField(verbose_name="remark",max_length=128, null=True, blank=True)

    class Meta:
        unique_together = ('proxy_type','proxy_address', 'proxy_port')

    def get_protocol_type(self):
        for protocol_value, protocol_str in self.protocol_choices:
            if protocol_value == self.proxy_type:
                return protocol_str
        return "Unknown"

    def __str__(self):
        protocol_str = self.get_protocol_type()
        return f"{protocol_str}://{self.proxy_address}:{self.proxy_port}"


class CeyeConfig(models.Model):
    api_token = models.CharField(verbose_name="API Token", max_length=255)
    identifier = models.CharField(verbose_name="Identifier", max_length=255)
    update_time = models.DateTimeField(verbose_name="更新时间", auto_now=True)

    class Meta:
        verbose_name = "ceye 配置"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"ceye: {self.identifier}"


class ExportTask(models.Model):
    task_type_choices = (("global", "全局检索"), ("task", "任务检索"))
    status_choices = (("processing", "处理中"), ("completed", "已完成"), ("failed", "失败"))

    task_type = models.CharField(verbose_name="任务类型", max_length=16, choices=task_type_choices)
    task_id = models.IntegerField(verbose_name="自动扫描任务ID", null=True, blank=True)
    task_name = models.CharField(verbose_name="任务名", max_length=256, blank=True)
    search_string = models.TextField(verbose_name="检索条件", blank=True)
    fields = ArrayField(models.CharField(max_length=32), verbose_name="导出字段")
    include_vuln_result = models.BooleanField(verbose_name="包含漏洞验证结果", default=False)
    export_limit = models.IntegerField(verbose_name="导出条数上限", null=True, blank=True)
    zone_id = models.IntegerField(verbose_name="扫描区域ID", null=True, blank=True)
    status = models.CharField(verbose_name="状态", max_length=16, choices=status_choices, default="processing")
    csv_file = models.CharField(verbose_name="CSV文件路径", max_length=512, blank=True)
    total_rows = models.IntegerField(verbose_name="导出总行数", null=True, blank=True)
    error_message = models.TextField(verbose_name="错误信息", blank=True)
    creatime = models.DateTimeField(verbose_name="创建时间", default=timezone.now)


# ======================== AI生成PoC ========================

class AIModelConfig(models.Model):
    """AI 模型配置（思考模型 / 识图模型）"""
    MODEL_TYPE_CHOICES = (
        ("thinking", "思考模型"),
        ("vision", "识图模型"),
    )
    name = models.CharField(verbose_name="配置名称", max_length=128)
    model_id = models.CharField(verbose_name="模型 ID", max_length=128)
    api_url = models.URLField(verbose_name="API 地址", max_length=512)
    api_key = models.CharField(verbose_name="API Key", max_length=512)
    model_type = models.CharField(verbose_name="模型类型", max_length=16, choices=MODEL_TYPE_CHOICES)
    created_at = models.DateTimeField(verbose_name="创建时间", default=timezone.now)

    class Meta:
        db_table = "ai_model_config"
        verbose_name = "AI 模型配置"

    def __str__(self):
        return f"{self.name} ({self.get_model_type_display()})"


class PoCGenerationTask(models.Model):
    """PoC 生成任务 — 完整生命周期"""
    TASK_TYPE_CHOICES = (
        ("url_crawl", "URL爬取"),
        ("file_upload", "上传文件"),
        ("text_input", "直接输入文本"),
    )
    PLUGIN_LANG_CHOICES = (
        (1, "Python"),
        (2, "Nuclei YAML"),
    )
    CRAWL_STATUS_CHOICES = (
        ("pending", "等待中"),
        ("processing", "处理中"),
        ("success", "提取成功"),
        ("failed", "提取失败"),
    )
    STATUS_CHOICES = (
        ("pending", "等待中"),
        ("crawling", "资料提取中"),
        ("ready", "待生成"),
        ("generating", "生成中"),
        ("generated", "生成完成"),
        ("failed", "失败"),
    )

    title = models.CharField(verbose_name="任务标题", max_length=256)
    task_type = models.CharField(verbose_name="任务类型", max_length=16, choices=TASK_TYPE_CHOICES)
    plugin_language = models.SmallIntegerField(verbose_name="插件类型", choices=PLUGIN_LANG_CHOICES, null=True, blank=True)
    thinking_model = models.ForeignKey(AIModelConfig, on_delete=models.PROTECT, related_name="poc_gen_tasks")
    vision_model = models.ForeignKey(AIModelConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name="poc_gen_vision_tasks")
    urls = models.TextField(verbose_name="URL列表（JSON数组）", blank=True)
    proxy = models.ForeignKey("ProxySetting", on_delete=models.SET_NULL, null=True, blank=True, related_name="poc_crawl_proxy", verbose_name="URL爬取代理")
    api_proxy = models.ForeignKey("ProxySetting", on_delete=models.SET_NULL, null=True, blank=True, related_name="poc_api_proxy", verbose_name="AI API代理")
    uploaded_file = models.CharField(verbose_name="上传文件路径", max_length=512, blank=True)
    material_dir = models.CharField(verbose_name="资料目录", max_length=512, blank=True)
    crawl_status = models.CharField(verbose_name="资料提取状态", max_length=16, choices=CRAWL_STATUS_CHOICES, default="pending")
    crawl_detail = models.TextField(verbose_name="爬取详情（JSON）", blank=True)
    task_description_prompt = models.TextField(verbose_name="任务说明提示词", blank=True)
    plugin_spec_prompt = models.TextField(verbose_name="插件规范提示词", blank=True)
    reference_material_prompt = models.TextField(verbose_name="参考资料提示词", blank=True)
    custom_prompt = models.TextField(verbose_name="用户自定义提示词", blank=True)
    generated_poc_content = models.TextField(verbose_name="生成的PoC代码", blank=True)
    generated_metadata = models.TextField(verbose_name="生成的元数据（JSON）", blank=True)
    generated_extra_info = models.TextField(verbose_name="生成的额外信息", blank=True)
    saved_to_exp = models.BooleanField(verbose_name="已保存到EXP库", default=False)
    saved_exp_id = models.IntegerField(verbose_name="保存的EXP ID", null=True, blank=True)
    status = models.CharField(verbose_name="任务状态", max_length=16, choices=STATUS_CHOICES, default="pending")
    celery_task_id = models.CharField(verbose_name="Celery Task ID", max_length=128, blank=True)
    created_at = models.DateTimeField(verbose_name="创建时间", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="更新时间", auto_now=True)

    class Meta:
        db_table = "poc_generation_task"
        verbose_name = "PoC 生成任务"

    def __str__(self):
        return f"PoCGen #{self.id}: {self.title}"


class HostedFile(models.Model):
    """文件托管：用户上传的任意文件，可设置公开下载或需登录鉴权"""
    original_name = models.CharField(verbose_name="原始文件名", max_length=512)
    stored_name = models.CharField(verbose_name="磁盘文件名", max_length=512, unique=True)
    file_size = models.BigIntegerField(verbose_name="文件大小（字节）")
    is_public = models.BooleanField(verbose_name="公开访问", default=True)
    note = models.TextField(verbose_name="备注", blank=True, default='')
    created_at = models.DateTimeField(verbose_name="上传时间", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="更新时间", auto_now=True)

    class Meta:
        db_table = "hosted_file"
        verbose_name = "托管文件"

    def __str__(self):
        return f"{self.original_name} ({'公开' if self.is_public else '需登录'})"


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('super_admin', '超级管理员'),
        ('admin', '普通管理员'),
        ('user', '普通用户'),
    ]
    user = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default='user')

    class Meta:
        db_table = "user_profile"
        verbose_name = "用户角色"

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"
