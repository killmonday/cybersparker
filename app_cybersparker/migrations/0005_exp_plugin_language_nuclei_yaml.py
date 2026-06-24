from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app_cybersparker', '0004_batch_exptask_engine_max_assets_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='exp',
            name='plugin_language',
            field=models.SmallIntegerField(choices=[(1, 'python3'), (2, 'nuclei_yaml')], default=1, verbose_name='plugin_language'),
        ),
    ]
