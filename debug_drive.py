"""1회성 Drive 진단 스크립트 - 배포 후 자동 삭제됨"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.conf import settings
from orders.management.commands.sync_call_recordings import get_drive_service
from orders.models import CallRecording

service = get_drive_service()
if not service:
    print('ERROR: Drive service failed')
    exit(1)

fid = settings.GOOGLE_DRIVE_FOLDER_ID
print(f'Folder ID: {fid}')

# 모든 파일 (MIME 필터 없이)
r = service.files().list(
    q=f"'{fid}' in parents and trashed=false",
    fields='files(id,name,mimeType,size)',
    pageSize=10,
).execute()
files = r.get('files', [])
print(f'Total files in folder: {len(files)}')
for f in files[:10]:
    print(f'  {f["name"]} | {f.get("mimeType", "?")} | {f.get("size", "?")} bytes')

# audio/video 필터
r2 = service.files().list(
    q=f"'{fid}' in parents and trashed=false and (mimeType contains 'audio/' or mimeType contains 'video/')",
    fields='files(id,name,mimeType)',
    pageSize=10,
).execute()
files2 = r2.get('files', [])
print(f'Audio/Video files: {len(files2)}')
for f in files2[:10]:
    print(f'  {f["name"]} | {f.get("mimeType", "?")}')

# 이미 동기화된 건수
existing = CallRecording.objects.filter(gdrive_file_id__gt='').count()
print(f'Already synced: {existing}')
