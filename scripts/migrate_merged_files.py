"""迁移 EXP_input 根目录下的 UUID 合并文件到 .merged/ 子目录。

用法：在项目根目录执行
    python manage.py shell < scripts/migrate_merged_files.py
或
    PYTHONPATH=. python scripts/migrate_merged_files.py
"""
import os
import re
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cybersparker.settings')
django.setup()

from django.conf import settings

uuid_re = re.compile(r'^[0-9a-f]{32}\.txt$')

exp_input = os.path.join(os.path.dirname(settings.THIS_DIR), 'EXP_input')
merged_dir = os.path.join(exp_input, '.merged')
os.makedirs(merged_dir, exist_ok=True)

moved = 0
for fname in os.listdir(exp_input):
    if not uuid_re.match(fname):
        continue
    src = os.path.join(exp_input, fname)
    dst = os.path.join(merged_dir, fname)
    if not os.path.isfile(src):
        continue
    os.rename(src, dst)
    moved += 1
    print(f'  MOVE: {fname}')

print(f'\n文件迁移完成：{moved} 个')

# 更新 DB 中的 target 路径
from app_cybersparker import models as m

# batch_EXPTask
batch_updated = 0
for task in m.batch_EXPTask.objects.all():
    target = str(task.target or '').strip()
    if not target:
        continue
    basename = os.path.basename(target)
    if uuid_re.match(basename) and '.merged/' not in target:
        task.target = f'EXP_input/.merged/{basename}'
        task.save(update_fields=['target'])
        batch_updated += 1

print(f'batch_EXPTask 更新：{batch_updated} 条')

# auto_scan_tasks
auto_updated = 0
for task in m.auto_scan_tasks.objects.all():
    target = str(task.target or '').strip()
    if not target:
        continue
    basename = os.path.basename(target)
    if uuid_re.match(basename) and '.merged/' not in target:
        task.target = f'EXP_input/.merged/{basename}'
        task.save(update_fields=['target'])
        auto_updated += 1

print(f'auto_scan_tasks 更新：{auto_updated} 条')
print('迁移完成。')
