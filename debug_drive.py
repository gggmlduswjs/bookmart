#!/usr/bin/env python
"""1회성 Drive 디버깅 스크립트 - 배포 후 자동 삭제"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from orders.management.commands.sync_call_recordings import get_drive_service
from django.conf import settings

print('FOLDER_ID:', repr(settings.GOOGLE_DRIVE_FOLDER_ID))

svc = get_drive_service()
if not svc:
    print('No drive service (token missing)')
    exit()

try:
    about = svc.about().get(fields='user').execute()
    print('Authenticated as:', about['user']['emailAddress'])
except Exception as e:
    print('About error:', e)

try:
    folder_id = settings.GOOGLE_DRIVE_FOLDER_ID
    q = f"'{folder_id}' in parents and trashed=false"
    r = svc.files().list(q=q, fields='files(id,name,mimeType)', pageSize=5).execute()
    files = r.get('files', [])
    print(f'Files found: {len(files)}')
    for f in files[:3]:
        print(f'  - {f["name"]} ({f["mimeType"]})')
except Exception as e:
    print(f'List error: {e}')
