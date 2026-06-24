# Generated manually — zone FK NOT NULL enforcement
# All 5 tables' zone columns must be NOT NULL after backfill.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('app_cybersparker', '0078_add_missing_asset_indexes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auto_scan_indentify_result',
            name='zone',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='app_cybersparker.assetzone'),
        ),
        migrations.AlterField(
            model_name='auto_scan_tasks',
            name='zone',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='app_cybersparker.assetzone'),
        ),
        migrations.AlterField(
            model_name='batch_EXPTask',
            name='zone',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='app_cybersparker.assetzone'),
        ),
        migrations.AlterField(
            model_name='DirScanTask',
            name='zone',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='app_cybersparker.assetzone'),
        ),
        migrations.AlterField(
            model_name='auto_scan_directory_result',
            name='zone',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='app_cybersparker.assetzone'),
        ),
    ]
