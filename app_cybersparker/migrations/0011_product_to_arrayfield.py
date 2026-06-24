# Replace product CharField with products ArrayField for proper multi-product storage
from collections import defaultdict
from django.db import migrations, models
import django.contrib.postgres.fields


def migrate_product_to_array(apps, schema_editor):
    """Convert existing '\n'-separated product strings to PostgreSQL arrays."""
    auto_scan_indentify_result = apps.get_model('app_cybersparker', 'auto_scan_indentify_result')
    for row in auto_scan_indentify_result.objects.all():
        old = (row.product or '').strip()
        if not old or old == 'unknow':
            row.products = []
        else:
            row.products = [p.strip() for p in old.split('\n') if p.strip()]
        row.save(update_fields=['products'])


def dedup_and_merge_products(apps, schema_editor):
    """Merge duplicate (task_id, target) rows by combining their product arrays.

    Old unique_together was (task_id, product, target) — same target could have
    multiple rows with different products. The new constraint is (task_id, target).
    For each group, keep the first row, merge all products into it, delete the rest.
    """
    auto_scan_indentify_result = apps.get_model('app_cybersparker', 'auto_scan_indentify_result')
    groups = defaultdict(list)
    for row in auto_scan_indentify_result.objects.all():
        groups[(row.task_id, row.target)].append(row)

    for (task_id, target), rows in groups.items():
        if len(rows) == 1:
            continue
        keeper = rows[0]
        merged = set(keeper.products or [])
        for dup in rows[1:]:
            for p in (dup.products or []):
                merged.add(p)
            dup.delete()
        keeper.products = sorted(merged)
        keeper.save(update_fields=['products'])


class Migration(migrations.Migration):

    dependencies = [
        ('app_cybersparker', '0010_pg_trgm_html_index'),
    ]

    operations = [
        # 1. Remove old unique constraint (includes product)
        migrations.AlterUniqueTogether(
            name='auto_scan_indentify_result',
            unique_together=set(),
        ),
        # 2. Add products ArrayField
        migrations.AddField(
            model_name='auto_scan_indentify_result',
            name='products',
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=128),
                default=list,
                blank=True,
                size=None,
            ),
        ),
        # 3. Data migration: split old product by \n into array
        migrations.RunPython(migrate_product_to_array, migrations.RunPython.noop),
        # 4. Remove old product field
        migrations.RemoveField(
            model_name='auto_scan_indentify_result',
            name='product',
        ),
        # 5. Dedup: merge duplicate (task_id, target) rows before new unique constraint
        migrations.RunPython(dedup_and_merge_products, migrations.RunPython.noop),
        # 6. Add new unique constraint (task_id + target only)
        migrations.AlterUniqueTogether(
            name='auto_scan_indentify_result',
            unique_together={('task_id', 'target')},
        ),
        # 7. GIN index for products array (supports @> contains lookups)
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_products_gin ON app_cybersparker_auto_scan_indentify_result USING GIN (products)",
            reverse_sql="DROP INDEX IF EXISTS idx_products_gin",
        ),
    ]
