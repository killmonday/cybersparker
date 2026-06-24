from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app_cybersparker', '0044_batch_exp_filter'),
    ]

    operations = [
        migrations.AddField(
            model_name='batch_exptask',
            name='pause_requested',
            field=models.BooleanField(default=False, verbose_name='pause requested'),
        ),
        migrations.AlterField(
            model_name='batch_exptask',
            name='status',
            field=models.SmallIntegerField(choices=[(1, 'finish'), (2, 'running'), (3, 'stop'), (4, 'pause')], default=3, verbose_name='status'),
        ),
    ]
