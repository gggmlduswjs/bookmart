"""
Google Drive OAuth 인증 (최초 1회만 실행).

사용법:
  python manage.py gdrive_auth

브라우저에서 URL을 열고 → 구글 로그인 → 코드 복사 → 터미널에 붙여넣기
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Google Drive OAuth 인증 (최초 1회)'

    def handle(self, *args, **options):
        from google_auth_oauthlib.flow import Flow

        client_secret = settings.GOOGLE_OAUTH_CLIENT_JSON
        if not client_secret or not Path(client_secret).exists():
            self.stderr.write(f'OAuth 클라이언트 JSON 파일을 찾을 수 없습니다: {client_secret}')
            return

        # 웹 클라이언트를 로컬 리디렉트로 사용
        flow = Flow.from_client_secrets_file(
            client_secret,
            scopes=['https://www.googleapis.com/auth/drive.readonly'],
            redirect_uri='http://localhost:8090',
        )

        auth_url, _ = flow.authorization_url(
            access_type='offline',
            prompt='consent',
        )

        self.stdout.write('')
        self.stdout.write('=' * 60)
        self.stdout.write('Google Drive 인증')
        self.stdout.write('=' * 60)
        self.stdout.write('')
        self.stdout.write('1. 아래 URL을 브라우저에 복사해서 열기:')
        self.stdout.write('')
        self.stdout.write(f'  {auth_url}')
        self.stdout.write('')
        self.stdout.write('2. Google 로그인 후 권한 허용')
        self.stdout.write('3. "이 사이트에 연결할 수 없습니다" 페이지가 뜨면 정상!')
        self.stdout.write('4. 브라우저 주소창에서 URL 전체를 복사해서 아래에 붙여넣기')
        self.stdout.write('')

        redirect_response = input('리디렉트된 URL 전체를 붙여넣기: ').strip()

        try:
            flow.fetch_token(authorization_response=redirect_response)
        except Exception as e:
            self.stderr.write(f'인증 실패: {e}')
            self.stderr.write('')
            self.stderr.write('Google Cloud Console에서 아래 리디렉트 URI를 추가했는지 확인하세요:')
            self.stderr.write('  http://localhost:8090')
            return

        creds = flow.credentials
        token_path = Path(settings.BASE_DIR) / 'gdrive_token.json'
        token_data = {
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
            'scopes': list(creds.scopes) if creds.scopes else [],
        }
        token_path.write_text(json.dumps(token_data, indent=2))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'인증 완료! 토큰 저장: {token_path}'))
        self.stdout.write('이제 sync_call_recordings 명령어를 사용할 수 있습니다.')
