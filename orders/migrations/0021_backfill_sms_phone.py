"""
데이터 마이그레이션:
1. phone 필드가 비어있는 SMS에 sender에서 전화번호 추출하여 채움
2. sender에서 ({number}), {number} 제거 + 불필요한 괄호 정리
"""
import re
from django.db import migrations


def backfill_and_clean(apps, schema_editor):
    InboxMessage = apps.get_model('orders', 'InboxMessage')

    # 1) phone 백필
    sms_no_phone = InboxMessage.objects.filter(source='sms', phone='')
    phone_updated = 0
    for msg in sms_no_phone:
        m = re.search(r'(\d[\d\-]{8,})', msg.sender or '')
        if m:
            msg.phone = m.group(1).replace('-', '')
            msg.save(update_fields=['phone'])
            phone_updated += 1
    print(f'  phone 백필: {phone_updated}건 업데이트')

    # 2) sender에서 ({number}), {number} 제거
    dirty = InboxMessage.objects.filter(source='sms', sender__contains='{number}')
    sender_updated = 0
    for msg in dirty:
        cleaned = msg.sender
        cleaned = re.sub(r'\(\{number\}\)', '', cleaned)
        cleaned = re.sub(r'\{number\}', '', cleaned)
        cleaned = cleaned.strip()
        if cleaned != msg.sender:
            msg.sender = cleaned
            msg.save(update_fields=['sender'])
            sender_updated += 1
    print(f'  sender 정리: {sender_updated}건 업데이트')


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0020_add_fields_phase1'),
    ]

    operations = [
        migrations.RunPython(backfill_and_clean, migrations.RunPython.noop),
    ]
