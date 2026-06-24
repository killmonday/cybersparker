import re
import sys
from django.core.management.base import BaseCommand
from django.db import transaction
from app_cybersparker import models

SKIP_PATTERN = re.compile(
    r'(?:^|&&\s*|\|\|\s*|\()\s*'
    r'(?:Protocol|Port|Hash|Response|SPASS)'
    r'\s*(?:=|~=|!=)'
)

TRANSFORM_STEPS = [
    ("Bodyr=", "body="),
    ("Body!=", "body!="),
    ("Body=", "body="),
    ("Header~=", "header~="),
    ("Header!=", "header!="),
    ("Header=", "header="),
    ("Title!=", "title!="),
    ("Title=", "title="),
    ("Cert!=", "cert!="),
    ("Cert=", "cert="),
    ("Icon==", "favicon_mmh3="),
    ("Icon=", "favicon_mmh3="),
]


def transform_condition(condition):
    for old, new in TRANSFORM_STEPS:
        condition = condition.replace(old, new)
    # 标准化 ~= 正则内容：源数据用 \\ 表示 \，Python re 需要 \
    condition = condition.replace('\\\\', '\\')
    return condition


def has_skip_key(condition):
    return bool(SKIP_PATTERN.search(condition))


class Command(BaseCommand):
    help = '从 fingerprint.txt 导入指纹规则，按映射规则转换键名。'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='仅分析和报告，不写入数据库。',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='限制导入前 N 条（0=不限制）。',
        )
        parser.add_argument(
            '--input', type=str, default='fingerprint.txt',
            help='输入文件路径（默认 fingerprint.txt）。',
        )
        parser.add_argument(
            '--sample', type=int, default=0,
            help='打印前 N 条转换结果用于验证。',
        )

    def handle(self, **options):
        input_path = options['input']
        dry_run = options['dry_run']
        limit = options['limit']
        sample = options['sample']

        total = 0
        skipped = 0
        transformed = 0
        failed = 0
        batch = []
        batch_size = 500

        try:
            with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    total += 1
                    line = line.strip()
                    if not line:
                        skipped += 1
                        continue

                    parts = line.split('\t', 1)
                    if len(parts) != 2:
                        skipped += 1
                        continue

                    product, condition = parts
                    product = product.strip()
                    condition = condition.strip()

                    if not product or not condition:
                        skipped += 1
                        continue

                    if has_skip_key(condition):
                        skipped += 1
                        continue

                    transformed_condition = transform_condition(condition)
                    transformed += 1

                    if sample and transformed <= sample:
                        self.stdout.write(f'  [{product}] {condition}')
                        if transformed_condition != condition:
                            self.stdout.write(f'   -> {transformed_condition}')

                    if dry_run:
                        continue

                    batch.append(models.fingerPrint(
                        product=product,
                        condition=transformed_condition,
                    ))

                    if len(batch) >= batch_size:
                        failed += self._flush_batch(batch)
                        batch = []

                    if limit and transformed >= limit:
                        break

                if batch:
                    failed += self._flush_batch(batch)

        except FileNotFoundError:
            self.stderr.write(self.style.ERROR(f'文件不存在: {input_path}'))
            sys.exit(1)

        imported = transformed - failed

        self.stdout.write(self.style.SUCCESS(
            f'导入完成: 总行数={total}, 转换={transformed}, '
            f'导入成功={imported}, 导入失败(重复/错误)={failed}, '
            f'跳过={skipped}'
        ))

    def _flush_batch(self, batch):
        try:
            with transaction.atomic():
                models.fingerPrint.objects.bulk_create(
                    batch,
                    ignore_conflicts=True,
                )
            return 0
        except Exception as e:
            self.stderr.write(f'批量写入失败: {e}')
            failed = 0
            for obj in batch:
                try:
                    with transaction.atomic():
                        models.fingerPrint.objects.get_or_create(
                            product=obj.product,
                            condition=obj.condition,
                        )
                except Exception:
                    failed += 1
            return failed
