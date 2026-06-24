from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app_cybersparker", "0011_product_to_arrayfield"),
    ]

    operations = [
        migrations.AddField(
            model_name="auto_scan_tasks",
            name="dispatch_token",
            field=models.CharField(blank=True, max_length=64, null=True, verbose_name="dispatch token"),
        ),
        migrations.AddField(
            model_name="auto_scan_tasks",
            name="failed",
            field=models.BooleanField(default=False, verbose_name="failed"),
        ),
        migrations.AddField(
            model_name="auto_scan_tasks",
            name="heartbeat_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="heartbeat at"),
        ),
        migrations.AddField(
            model_name="auto_scan_tasks",
            name="last_error",
            field=models.TextField(blank=True, null=True, verbose_name="last error"),
        ),
        migrations.AddField(
            model_name="auto_scan_tasks",
            name="owner",
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name="owner"),
        ),
        migrations.AddField(
            model_name="auto_scan_tasks",
            name="queued",
            field=models.BooleanField(default=False, verbose_name="queued"),
        ),
        migrations.AddField(
            model_name="auto_scan_tasks",
            name="stop_requested",
            field=models.BooleanField(default=False, verbose_name="stop requested"),
        ),
        migrations.AddField(
            model_name="batch_exptask",
            name="dispatch_token",
            field=models.CharField(blank=True, max_length=64, null=True, verbose_name="dispatch token"),
        ),
        migrations.AddField(
            model_name="batch_exptask",
            name="failed",
            field=models.BooleanField(default=False, verbose_name="failed"),
        ),
        migrations.AddField(
            model_name="batch_exptask",
            name="heartbeat_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="heartbeat at"),
        ),
        migrations.AddField(
            model_name="batch_exptask",
            name="last_error",
            field=models.TextField(blank=True, null=True, verbose_name="last error"),
        ),
        migrations.AddField(
            model_name="batch_exptask",
            name="owner",
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name="owner"),
        ),
        migrations.AddField(
            model_name="batch_exptask",
            name="queued",
            field=models.BooleanField(default=False, verbose_name="queued"),
        ),
        migrations.AddField(
            model_name="batch_exptask",
            name="stop_requested",
            field=models.BooleanField(default=False, verbose_name="stop requested"),
        ),
    ]
