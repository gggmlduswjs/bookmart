"""
네이버 IMAP 이메일 수신 유틸
- imaplib (Python 내장) 사용 — 외부 패키지 불필요
- 한글 인코딩(EUC-KR, UTF-8) 모두 처리
- 중복 방지: imap_key = account_label:uid
"""
import html
import imaplib
import logging
import re
import smtplib
import email as email_lib
from email.header import decode_header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from email.utils import formataddr, formatdate, parsedate_to_datetime

logger = logging.getLogger(__name__)

NAVER_IMAP_HOST = 'imap.naver.com'
NAVER_IMAP_PORT = 993


def _decode_str(s):
    """이메일 헤더 인코딩 디코딩 (=?UTF-8?B?...?= 등)"""
    if not s:
        return ''
    parts = decode_header(s)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            for enc in [charset, 'utf-8', 'euc-kr', 'cp949']:
                try:
                    result.append(part.decode(enc or 'utf-8', errors='replace'))
                    break
                except (LookupError, UnicodeDecodeError):
                    continue
        else:
            result.append(str(part))
    return ''.join(result)


def _get_body(msg):
    """이메일 본문 추출 — text/plain 우선, 없으면 text/html 태그 제거"""
    plain = ''
    html_body = ''

    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ct = part.get_content_type()
        charset = part.get_content_charset() or 'utf-8'
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        for enc in [charset, 'utf-8', 'euc-kr', 'cp949']:
            try:
                text = payload.decode(enc, errors='replace')
                break
            except LookupError:
                continue
        else:
            text = payload.decode('utf-8', errors='replace')

        if ct == 'text/plain' and not plain:
            plain = text
        elif ct == 'text/html' and not html_body:
            html_body = text

    if plain:
        return plain.strip()
    if html_body:
        # 태그 제거 후 반환
        text = re.sub(r'<style[^>]*>.*?</style>', '', html_body, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = html.unescape(text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
    return ''


def _get_attachments(msg):
    """이메일 첨부파일 추출 — (filename, content_type, data) 리스트 반환"""
    attachments = []
    if not msg.is_multipart():
        # 단일 파트 메일이라도 첨부일 수 있음
        content_disposition = msg.get('Content-Disposition', '')
        filename = msg.get_filename()
        if filename:
            filename = _decode_str(filename)
        if not filename:
            # Content-Type의 name 파라미터에서 파일명 추출
            name_param = msg.get_param('name')
            if name_param:
                filename = _decode_str(str(name_param))
        if filename:
            payload = msg.get_payload(decode=True)
            if payload:
                content_type = msg.get_content_type() or 'application/octet-stream'
                attachments.append({
                    'filename': filename,
                    'content_type': content_type,
                    'data': payload,
                })
        return attachments

    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue

        content_disposition = part.get('Content-Disposition', '')
        content_type = part.get_content_type() or 'application/octet-stream'

        # 파일명 추출: Content-Disposition 또는 Content-Type name 파라미터
        filename = part.get_filename()
        if filename:
            filename = _decode_str(filename)
        if not filename:
            name_param = part.get_param('name')
            if name_param:
                filename = _decode_str(str(name_param))

        # 첨부 판별: Content-Disposition에 attachment/inline이 있거나, 파일명이 있는 비텍스트 파트
        is_attachment = 'attachment' in content_disposition or 'inline' in content_disposition
        has_file = bool(filename) and content_type not in ('text/plain', 'text/html')

        if not is_attachment and not has_file:
            continue
        if not filename:
            continue

        payload = part.get_payload(decode=True)
        if not payload:
            continue

        attachments.append({
            'filename': filename,
            'content_type': content_type,
            'data': payload,
        })

    return attachments


def fetch_naver_emails(account_id, account_pw, account_label, days=60,
                       existing_keys=None):
    """
    네이버 메일함에서 최근 N일치 메일 목록 반환.
    existing_keys: set of imap_key — 이미 DB에 있는 키 (전달하면 해당 메일은 건너뜀)
    Returns: list of dict {imap_key, account_label, sender, subject, content, received_at, attachments}
    """
    import datetime
    from django.utils import timezone

    if existing_keys is None:
        existing_keys = set()

    results = []
    results_sync = {}
    try:
        mail = imaplib.IMAP4_SSL(NAVER_IMAP_HOST, NAVER_IMAP_PORT)
        mail.login(account_id, account_pw)
        mail.select('INBOX', readonly=True)

        # 최근 N일간 전체 메일 가져오기
        since_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%d-%b-%Y')
        status, data = mail.uid('search', None, f'SINCE {since_date}')
        if status != 'OK' or not data[0]:
            mail.logout()
            return results, results_sync

        uid_list = data[0].split()

        # 기존/신규 UID 분리
        new_uids = []
        existing_uids = []
        for uid_bytes in uid_list:
            uid_str = uid_bytes.decode()
            imap_key = f'{account_label}:{uid_str}'
            if imap_key in existing_keys:
                existing_uids.append((uid_bytes, uid_str, imap_key))
            else:
                new_uids.append((uid_bytes, uid_str, imap_key))

        # 기존 메일 읽음 상태 동기화 (일괄 FLAGS 조회)
        if existing_uids:
            sync_read = {}
            # UID 목록을 쉼표로 묶어 한 번에 조회
            uid_map = {uid_bytes: (uid_str, imap_key) for uid_bytes, uid_str, imap_key in existing_uids}
            uid_set = b','.join(ub for ub, _, _ in existing_uids)
            try:
                status2, flag_data = mail.uid('fetch', uid_set, '(FLAGS)')
                if status2 == 'OK' and flag_data:
                    for item in flag_data:
                        if item is None:
                            continue
                        raw = item[0] if isinstance(item, tuple) else item
                        if not isinstance(raw, bytes):
                            continue
                        # UID 추출: ... UID 123 ...
                        uid_match = re.search(rb'UID\s+(\d+)', raw)
                        if not uid_match:
                            continue
                        uid_found = uid_match.group(1)
                        imap_key_found = f'{account_label}:{uid_found.decode()}'
                        sync_read[imap_key_found] = b'\\Seen' in raw
            except Exception as e:
                logger.warning('IMAP 일괄 FLAGS 조회 실패 (%s): %s', account_label, e)
            results_sync = sync_read
        else:
            results_sync = {}

        if not new_uids:
            mail.logout()
            return results, results_sync

        logger.info('IMAP %s: %d건 중 %d건 새 메일 다운로드',
                    account_label, len(uid_list), len(new_uids))

        for uid_bytes, uid_str, imap_key in new_uids:
            status, msg_data = mail.uid('fetch', uid_bytes, '(RFC822 FLAGS)')
            if status != 'OK' or not msg_data or msg_data[0] is None:
                continue

            # FLAGS 파싱 — 응답의 첫 번째 요소에서 추출
            flags_raw = msg_data[0][0] if isinstance(msg_data[0], tuple) else b''
            is_seen = b'\\Seen' in flags_raw

            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)

            sender = _decode_str(msg.get('From', ''))
            subject = _decode_str(msg.get('Subject', '')) or '(제목 없음)'
            message_id = msg.get('Message-ID', '') or ''
            date_str = msg.get('Date', '')
            try:
                received_at = parsedate_to_datetime(date_str)
                if received_at.tzinfo is None:
                    received_at = timezone.make_aware(received_at)
            except Exception:
                received_at = timezone.now()

            content = _get_body(msg)
            attachments = _get_attachments(msg)

            results.append({
                'imap_key':      imap_key,
                'account_label': account_label,
                'sender':        sender,
                'subject':       subject,
                'content':       content,
                'received_at':   received_at,
                'attachments':   attachments,
                'message_id':    message_id,
                'is_seen':       is_seen,
            })

        mail.logout()
    except imaplib.IMAP4.error as e:
        logger.error('IMAP 로그인/접속 오류 (%s): %s', account_label, e)
    except Exception as e:
        logger.error('IMAP 수신 오류 (%s): %s', account_label, e)

    return results, results_sync


# ── 스팸 필터링 ──────────────────────────────────────────────────────────────

ORDER_KEYWORDS = ['주문', '교재', '발주', '주문서', '도서', '초등학교', '중학교', '학교', '학원']

SPAM_SENDERS = [
    '사람인', 'saramin', '스마트스토어', 'smartstore',
    '쿠팡', 'coupang', '네이버 전자문서', 'naver_edoc',
    '기프트서울', '잡코리아', 'jobkorea',
    'newsletter', 'marketing',
    'kb손해보험', 'kbinsure', '국민건강보험',
    '서울보증', 'sgic', '유니포스트', 'unipost',
    '국세청', 'hometax', 'kosa biz',
    '크라운출판사', '메이킹북스',
]


def mark_as_read_imap(account_id, account_pw, uid_str):
    """IMAP에서 해당 메일을 읽음(\\Seen)으로 표시"""
    try:
        mail = imaplib.IMAP4_SSL(NAVER_IMAP_HOST, NAVER_IMAP_PORT)
        mail.login(account_id, account_pw)
        mail.select('INBOX', readonly=False)
        mail.uid('store', uid_str.encode(), '+FLAGS', '(\\Seen)')
        mail.logout()
        logger.info('IMAP %s: UID %s 읽음 표시 완료', account_id, uid_str)
        return True
    except Exception as e:
        logger.error('IMAP 읽음 표시 오류 (%s, UID %s): %s', account_id, uid_str, e)
        return False


def delete_email_imap(account_id, account_pw, uid_str):
    """IMAP에서 해당 메일을 삭제"""
    try:
        mail = imaplib.IMAP4_SSL(NAVER_IMAP_HOST, NAVER_IMAP_PORT)
        mail.login(account_id, account_pw)
        mail.select('INBOX', readonly=False)
        mail.uid('store', uid_str.encode(), '+FLAGS', '(\\Deleted)')
        mail.expunge()
        mail.logout()
        logger.info('IMAP %s: UID %s 삭제 완료', account_id, uid_str)
        return True
    except Exception as e:
        logger.error('IMAP 삭제 오류 (%s, UID %s): %s', account_id, uid_str, e)
        return False


def delete_emails_imap(account_id, account_pw, uid_list):
    """IMAP에서 여러 메일을 한 번에 삭제"""
    if not uid_list:
        return
    try:
        mail = imaplib.IMAP4_SSL(NAVER_IMAP_HOST, NAVER_IMAP_PORT)
        mail.login(account_id, account_pw)
        mail.select('INBOX', readonly=False)
        for uid_str in uid_list:
            mail.uid('store', uid_str.encode(), '+FLAGS', '(\\Deleted)')
        mail.expunge()
        mail.logout()
        logger.info('IMAP %s: %d건 삭제 완료', account_id, len(uid_list))
    except Exception as e:
        logger.error('IMAP 일괄 삭제 오류 (%s): %s', account_id, e)


NAVER_SMTP_HOST = 'smtp.naver.com'
NAVER_SMTP_PORT = 587


def send_reply_email(account_id, account_pw, to_email, subject, body,
                     in_reply_to=None, references=None):
    """
    네이버 SMTP로 답장 메일 발송.
    in_reply_to / references 헤더를 설정하면 메일 스레드로 묶임.
    """
    from_email = f'{account_id}@naver.com'

    msg = MIMEText(body, 'plain', 'utf-8')
    msg['From'] = formataddr(('북마트', from_email))
    msg['To'] = to_email
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)

    if in_reply_to:
        msg['In-Reply-To'] = in_reply_to
    if references:
        msg['References'] = references

    try:
        server = smtplib.SMTP(NAVER_SMTP_HOST, NAVER_SMTP_PORT)
        server.starttls()
        server.login(account_id, account_pw)
        server.sendmail(from_email, [to_email], msg.as_string())
        server.quit()
        logger.info('답장 메일 발송 완료: %s → %s', from_email, to_email)
        return True
    except Exception as e:
        logger.error('답장 메일 발송 실패 (%s → %s): %s', from_email, to_email, e)
        return False


def send_email_with_attachments(account_id, account_pw, to_email, subject, body,
                                attachments=None):
    """
    네이버 SMTP로 첨부파일 포함 이메일 발송.
    attachments: [{'filename': str, 'data': bytes, 'content_type': str}, ...]
    """
    from_email = f'{account_id}@naver.com'

    msg = MIMEMultipart()
    msg['From'] = formataddr(('북마트', from_email))
    msg['To'] = to_email
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)

    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    for att in (attachments or []):
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(att['data'])
        encoders.encode_base64(part)
        # RFC2231 한글 파일명 지원
        part.add_header(
            'Content-Disposition', 'attachment',
            filename=('utf-8', '', att['filename']),
        )
        msg.attach(part)

    try:
        server = smtplib.SMTP(NAVER_SMTP_HOST, NAVER_SMTP_PORT)
        server.starttls()
        server.login(account_id, account_pw)
        server.sendmail(from_email, [to_email], msg.as_string())
        server.quit()
        logger.info('첨부 메일 발송 완료: %s → %s (첨부 %d건)', from_email, to_email, len(attachments or []))
        return True
    except Exception as e:
        logger.error('첨부 메일 발송 실패 (%s → %s): %s', from_email, to_email, e)
        return False


def is_order_related(sender, subject, content):
    """
    이메일이 주문 관련인지 판별.
    - 스팸 발신자 → False
    - 제목/내용에 주문 키워드 포함 → True
    - 그 외 → False (스팸으로 간주)
    """
    sender_lower = (sender or '').lower()
    for spam in SPAM_SENDERS:
        if spam.lower() in sender_lower:
            return False

    text = f'{subject or ""} {content or ""}'
    for kw in ORDER_KEYWORDS:
        if kw in text:
            return True

    return False
