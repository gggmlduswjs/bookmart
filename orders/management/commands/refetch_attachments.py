import imaplib
import email as email_lib
import re

from django.core.management.base import BaseCommand
from django.conf import settings as conf
from django.core.files.base import ContentFile

from orders.models import InboxMessage, InboxAttachment
from orders.email_utils import _get_attachments, NAVER_IMAP_HOST, NAVER_IMAP_PORT


class Command(BaseCommand):
    help = '첨부파일이 누락된 기존 메일의 첨부파일을 IMAP에서 다시 가져옵니다'

    def handle(self, *args, **options):
        # 첨부파일이 0건인 메일 중 imap_key가 있는 것만 대상
        msgs = InboxMessage.objects.filter(
            source='email',
            imap_key__isnull=False,
        ).exclude(imap_key='').annotate(
            att_count=__import__('django.db.models', fromlist=['Count']).Count('attachments')
        ).filter(att_count=0)

        if not msgs.exists():
            self.stdout.write('첨부파일 누락 메일 없음')
            return

        self.stdout.write(f'대상 메일: {msgs.count()}건')

        # imap_key별로 계정 분류
        account_map = {}
        if getattr(conf, 'NAVER_EMAIL_1_ID', None):
            account_map['007bm'] = (conf.NAVER_EMAIL_1_ID, conf.NAVER_EMAIL_1_PW)
        if getattr(conf, 'NAVER_EMAIL_2_ID', None):
            account_map['002bm'] = (conf.NAVER_EMAIL_2_ID, conf.NAVER_EMAIL_2_PW)

        # 계정별로 그룹핑
        by_account = {}
        for msg in msgs:
            parts = msg.imap_key.split(':', 1)
            if len(parts) != 2:
                continue
            label, uid_str = parts
            if label not in account_map:
                continue
            by_account.setdefault(label, []).append((msg, uid_str))

        total_fixed = 0
        for label, items in by_account.items():
            acc_id, acc_pw = account_map[label]
            try:
                mail = imaplib.IMAP4_SSL(NAVER_IMAP_HOST, NAVER_IMAP_PORT)
                mail.login(acc_id, acc_pw)
                mail.select('INBOX', readonly=True)

                for msg_obj, uid_str in items:
                    try:
                        status, msg_data = mail.uid('fetch', uid_str.encode(), '(RFC822)')
                        if status != 'OK' or not msg_data or msg_data[0] is None:
                            continue

                        raw = msg_data[0][1]
                        email_msg = email_lib.message_from_bytes(raw)
                        attachments = _get_attachments(email_msg)

                        if not attachments:
                            continue

                        for att in attachments:
                            file_obj = ContentFile(att['data'], name=att['filename'])
                            InboxAttachment.objects.create(
                                message=msg_obj,
                                file=file_obj,
                                filename=att['filename'],
                                content_type=att['content_type'],
                                size=len(att['data']),
                            )

                        total_fixed += 1
                        self.stdout.write(f'  복구: {msg_obj.subject} ({len(attachments)}건)')

                    except Exception as e:
                        self.stdout.write(f'  실패: {msg_obj.imap_key} - {e}')

                mail.logout()
            except Exception as e:
                self.stdout.write(f'IMAP 연결 실패 ({label}): {e}')

        self.stdout.write(f'완료: {total_fixed}건 첨부파일 복구')
