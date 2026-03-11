"""
Google Drive에서 통화 녹음 파일을 가져와 자동 처리하는 관리 명령어.

사용법:
  python manage.py sync_call_recordings          # 동기화만 (파싱은 별도)
  python manage.py sync_call_recordings --process # 동기화 + 자동 파싱

cron 예시:
  */5 * * * * cd /app && python manage.py sync_call_recordings --process
"""
import io
import json
import logging
import math
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from orders.models import CallRecording

logger = logging.getLogger(__name__)


def get_drive_service():
    """Google Drive API 서비스 생성 (OAuth 토큰 사용)"""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = Path(settings.BASE_DIR) / 'gdrive_token.json'
    if not token_path.exists():
        logger.warning('gdrive_token.json 없음. python manage.py gdrive_auth 실행 필요')
        return None

    token_data = json.loads(token_path.read_text())
    creds = Credentials(
        token=token_data.get('token'),
        refresh_token=token_data.get('refresh_token'),
        token_uri=token_data.get('token_uri'),
        client_id=token_data.get('client_id'),
        client_secret=token_data.get('client_secret'),
        scopes=token_data.get('scopes'),
    )

    # 토큰 만료 시 자동 갱신
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_data['token'] = creds.token
        token_path.write_text(json.dumps(token_data, indent=2))

    return build('drive', 'v3', credentials=creds)


def sync_from_drive():
    """Google Drive 폴더에서 새 녹음 파일 동기화"""
    folder_id = settings.GOOGLE_DRIVE_FOLDER_ID
    if not folder_id:
        logger.warning('GOOGLE_DRIVE_FOLDER_ID 미설정')
        return 0

    service = get_drive_service()
    if not service:
        return 0

    # 이미 동기화된 파일 ID 목록
    existing_ids = set(
        CallRecording.objects.filter(gdrive_file_id__gt='')
        .values_list('gdrive_file_id', flat=True)
    )

    # Drive에서 오디오 파일 목록 가져오기
    query = (
        f"'{folder_id}' in parents and trashed=false and "
        f"(mimeType contains 'audio/' or mimeType contains 'video/mp4')"
    )
    results = service.files().list(
        q=query,
        fields='files(id,name,mimeType,size,createdTime,modifiedTime)',
        orderBy='createdTime desc',
        pageSize=50,
    ).execute()

    new_count = 0
    for f in results.get('files', []):
        if f['id'] in existing_ids:
            continue

        # 파일 다운로드
        from googleapiclient.http import MediaIoBaseDownload
        request = service.files().get_media(fileId=f['id'])
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        buf.seek(0)
        content = ContentFile(buf.read(), name=f['name'])

        # 파일명에서 전화번호 추출 시도 (예: "통화녹음_010-1234-5678_20260311.m4a")
        caller_phone = ''
        parts = f['name'].replace('.m4a', '').replace('.mp3', '').split('_')
        for part in parts:
            cleaned = part.replace('-', '')
            if cleaned.startswith('01') and len(cleaned) >= 10:
                caller_phone = part
                break

        rec = CallRecording(
            file_name=f['name'],
            caller_phone=caller_phone,
            source='gdrive',
            gdrive_file_id=f['id'],
        )
        rec.audio_file.save(f['name'], content, save=False)

        # createdTime 파싱
        if f.get('createdTime'):
            from datetime import datetime as dt
            try:
                rec.recorded_at = dt.fromisoformat(f['createdTime'].replace('Z', '+00:00'))
            except (ValueError, TypeError):
                pass

        rec.save()
        new_count += 1
        logger.info(f'새 녹음 동기화: {f["name"]}')

    return new_count


def process_pending_recordings():
    """대기 중인 녹음을 자동 파싱"""
    from orders.call_order import transcribe_audio, parse_order_from_text
    from books.models import Book

    pending = CallRecording.objects.filter(status=CallRecording.Status.PENDING)
    processed = 0

    # 교재 목록 (한 번만 로드)
    books = Book.objects.filter(is_active=True).select_related('publisher')
    book_list = [{
        'id': b.id,
        'series': b.series or '기타',
        'name': b.name,
        'publisher': b.publisher.name,
        'unit_price': math.floor(b.list_price * float(b.publisher.supply_rate) / 100),
    } for b in books]

    for rec in pending:
        rec.status = CallRecording.Status.PROCESSING
        rec.save(update_fields=['status'])

        try:
            # 1단계: 음성 → 텍스트
            if not rec.transcript:
                audio_file = rec.audio_file
                audio_file.open('rb')
                transcript, err = transcribe_audio(audio_file)
                audio_file.close()
                if err:
                    rec.status = CallRecording.Status.FAILED
                    rec.error_msg = err[:300]
                    rec.save(update_fields=['status', 'error_msg'])
                    continue
                rec.transcript = transcript
                rec.save(update_fields=['transcript'])

            # 2단계: 텍스트 → 주문 파싱
            parsed, err = parse_order_from_text(rec.transcript, book_list)
            if err:
                rec.status = CallRecording.Status.FAILED
                rec.error_msg = err[:300]
                rec.save(update_fields=['status', 'error_msg'])
                continue

            rec.parsed_data = parsed
            rec.status = CallRecording.Status.PARSED
            rec.save(update_fields=['parsed_data', 'status'])
            processed += 1

        except Exception as e:
            logger.exception(f'녹음 처리 오류: {rec.pk}')
            rec.status = CallRecording.Status.FAILED
            rec.error_msg = str(e)[:300]
            rec.save(update_fields=['status', 'error_msg'])

    return processed


class Command(BaseCommand):
    help = 'Google Drive에서 통화 녹음을 동기화하고 자동 파싱합니다'

    def add_arguments(self, parser):
        parser.add_argument(
            '--process', action='store_true',
            help='동기화 후 대기 중인 녹음을 자동 파싱',
        )
        parser.add_argument(
            '--process-only', action='store_true',
            help='동기화 없이 대기 중인 녹음만 파싱',
        )

    def handle(self, *args, **options):
        if not options['process_only']:
            new = sync_from_drive()
            self.stdout.write(f'새 녹음 {new}건 동기화')

        if options['process'] or options['process_only']:
            processed = process_pending_recordings()
            self.stdout.write(f'녹음 {processed}건 파싱 완료')
