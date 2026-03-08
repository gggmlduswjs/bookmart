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
import email as email_lib
from email.header import decode_header
from email.utils import parsedate_to_datetime

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
        return attachments

    for part in msg.walk():
        content_disposition = part.get('Content-Disposition', '')
        if 'attachment' not in content_disposition and 'inline' not in content_disposition:
            continue

        # 파일명 추출
        filename = part.get_filename()
        if filename:
            filename = _decode_str(filename)
        if not filename:
            continue

        payload = part.get_payload(decode=True)
        if not payload:
            continue

        content_type = part.get_content_type() or 'application/octet-stream'
        attachments.append({
            'filename': filename,
            'content_type': content_type,
            'data': payload,
        })

    return attachments


def fetch_naver_emails(account_id, account_pw, account_label, days=60):
    """
    네이버 메일함에서 최근 N일치 메일 목록 반환.
    Returns: list of dict {imap_key, account_label, sender, subject, content, received_at, attachments}
    """
    import datetime
    from django.utils import timezone

    results = []
    try:
        mail = imaplib.IMAP4_SSL(NAVER_IMAP_HOST, NAVER_IMAP_PORT)
        mail.login(account_id, account_pw)
        mail.select('INBOX')

        # 읽지 않은 메일만 가져오기 (UNSEEN)
        status, data = mail.uid('search', None, 'UNSEEN')
        if status != 'OK' or not data[0]:
            mail.logout()
            return results

        uid_list = data[0].split()
        for uid_bytes in uid_list:
            uid_str = uid_bytes.decode()
            imap_key = f'{account_label}:{uid_str}'

            status, msg_data = mail.uid('fetch', uid_bytes, '(RFC822)')
            if status != 'OK' or not msg_data or msg_data[0] is None:
                continue

            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)

            sender = _decode_str(msg.get('From', ''))
            subject = _decode_str(msg.get('Subject', '')) or '(제목 없음)'
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
            })

        mail.logout()
    except imaplib.IMAP4.error as e:
        logger.error('IMAP 로그인/접속 오류 (%s): %s', account_label, e)
    except Exception as e:
        logger.error('IMAP 수신 오류 (%s): %s', account_label, e)

    return results


# ── 스팸 필터링 ──────────────────────────────────────────────────────────────

ORDER_KEYWORDS = ['주문', '교재', '발주', '주문서', '도서']

SPAM_SENDERS = [
    '사람인', 'saramin', '스마트스토어', 'smartstore',
    '쿠팡', 'coupang', '네이버 전자문서', 'naver_edoc',
    '기프트서울', '잡코리아', 'jobkorea',
    'noreply', 'no-reply', 'donotreply',
    'newsletter', 'marketing',
]


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
