from django.core.management.base import BaseCommand
from django.conf import settings as conf
from django.core.files.base import ContentFile

from orders.models import InboxMessage, InboxAttachment
from orders.email_utils import fetch_naver_emails


class Command(BaseCommand):
    help = '네이버 IMAP 메일을 가져옵니다 (cron용)'

    def handle(self, *args, **options):
        accounts = [
            (conf.NAVER_EMAIL_1_ID, conf.NAVER_EMAIL_1_PW, '007bm'),
            (conf.NAVER_EMAIL_2_ID, conf.NAVER_EMAIL_2_PW, '002bm'),
        ]

        all_existing_keys = set(
            InboxMessage.objects.values_list('imap_key', flat=True)
        )

        new_count = 0
        sync_count = 0
        for acc_id, acc_pw, label in accounts:
            if not acc_id or not acc_pw:
                continue
            emails, read_sync = fetch_naver_emails(acc_id, acc_pw, label,
                                                   existing_keys=all_existing_keys)

            if read_sync:
                for imap_key, is_seen in read_sync.items():
                    updated = InboxMessage.objects.filter(
                        imap_key=imap_key, is_read=not is_seen
                    ).update(is_read=is_seen)
                    sync_count += updated

            if not emails:
                continue

            for e in emails:
                msg_obj = InboxMessage.objects.create(
                    source=InboxMessage.Source.EMAIL,
                    account_label=e['account_label'],
                    sender=e['sender'],
                    subject=e['subject'],
                    content=e['content'],
                    received_at=e['received_at'],
                    imap_key=e['imap_key'],
                    is_processed=False,
                    is_read=e.get('is_seen', False),
                    message_id=e.get('message_id', ''),
                )
                for att in e.get('attachments', []):
                    file_obj = ContentFile(att['data'], name=att['filename'])
                    InboxAttachment.objects.create(
                        message=msg_obj,
                        file=file_obj,
                        filename=att['filename'],
                        content_type=att['content_type'],
                        size=len(att['data']),
                    )
                new_count += 1

        self.stdout.write(f'새 메일 {new_count}건, 읽음 동기화 {sync_count}건')
