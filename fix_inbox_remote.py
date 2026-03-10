import paramiko, sys
sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('158.247.242.167', username='root', password='[gF6mK.Wg8bjiqY2')

script = r'''
import os, django, sys
sys.stdout.reconfigure(encoding="utf-8")
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
django.setup()
from orders.models import InboxMessage, InboxAttachment
from orders.email_utils import is_order_related, fetch_naver_emails
from django.conf import settings as conf
from django.core.files.base import ContentFile

# 1) 기존 미처리 스팸 정리
for m in InboxMessage.objects.filter(is_processed=False):
    if not is_order_related(m.sender, m.subject, m.content):
        m.is_processed = True
        m.save(update_fields=["is_processed"])
        print(f"spam: {m.sender[:30]} | {m.subject[:30]}")

print(f"\nafter cleanup: unprocessed={InboxMessage.objects.filter(is_processed=False).count()}")

# 2) 새로 메일 가져오기
emails = fetch_naver_emails(conf.NAVER_EMAIL_1_ID, conf.NAVER_EMAIL_1_PW, "007bm")
print(f"\nfetched {len(emails)} emails from 007bm")

existing_keys = set(InboxMessage.objects.values_list("imap_key", flat=True))
new_count = order_count = 0
for e in emails:
    if e["imap_key"] in existing_keys:
        continue
    auto_skip = not is_order_related(e["sender"], e["subject"], e["content"])
    msg_obj = InboxMessage.objects.create(
        source=InboxMessage.Source.EMAIL,
        account_label=e["account_label"],
        sender=e["sender"],
        subject=e["subject"],
        content=e["content"],
        received_at=e["received_at"],
        imap_key=e["imap_key"],
        is_processed=auto_skip,
    )
    for att in e.get("attachments", []):
        file_obj = ContentFile(att["data"], name=att["filename"])
        InboxAttachment.objects.create(
            message=msg_obj, file=file_obj,
            filename=att["filename"],
            content_type=att["content_type"],
            size=len(att["data"]),
        )
    new_count += 1
    if not auto_skip:
        order_count += 1
        print(f"ORDER: {e['sender'][:30]} | {e['subject'][:40]}")

print(f"\nnew={new_count} (orders={order_count}, spam={new_count - order_count})")
print(f"total unprocessed={InboxMessage.objects.filter(is_processed=False).count()}")
'''

sftp = ssh.open_sftp()
with sftp.open('/tmp/fix_inbox.py', 'w') as f:
    f.write(script)
sftp.close()

stdin, stdout, stderr = ssh.exec_command(
    'cd /home/bookmart/bookmart && PYTHONPATH=/home/bookmart/bookmart '
    '/home/bookmart/bookmart/venv/bin/python /tmp/fix_inbox.py'
)
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    lines = err.strip().split('\n')
    for l in lines[-5:]:
        print('ERR:', l)
ssh.close()
