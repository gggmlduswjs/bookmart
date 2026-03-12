"""
통화녹음 → 주문 자동 파싱
1. 오디오 파일 → OpenAI Whisper API → 텍스트
2. 텍스트 → Anthropic Claude API → 구조화된 주문 정보
"""
import json
import logging
import mimetypes
import os
import subprocess
import tempfile

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _convert_to_mp3(audio_file):
    """오디오 파일을 항상 ffmpeg로 mp3 변환. (파일객체, 파일명) 반환.
    확장자가 지원 포맷이라도 실제 코덱이 다를 수 있으므로 무조건 변환."""
    filename = os.path.basename(audio_file.name)
    ext = os.path.splitext(filename)[1].lower() or '.bin'
    logger.info(f'[convert] 파일: {filename}, 확장자: "{ext}", ffmpeg mp3 변환 시작')

    # 임시 파일에 원본 저장 후 ffmpeg 변환
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as src:
        if hasattr(audio_file, 'chunks'):
            for chunk in audio_file.chunks():
                src.write(chunk)
        else:
            src.write(audio_file.read())
        src_path = src.name

    dst_path = src_path.rsplit('.', 1)[0] + '.mp3'
    try:
        result = subprocess.run(
            ['ffmpeg', '-y', '-i', src_path, '-vn', '-acodec', 'libmp3lame', '-q:a', '4', dst_path],
            capture_output=True, timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', errors='replace')[:500]
            logger.error(f'[convert] ffmpeg 실패: {stderr}')
            raise RuntimeError(f'ffmpeg 변환 실패 (code {result.returncode}): {stderr}')

        if not os.path.exists(dst_path) or os.path.getsize(dst_path) == 0:
            raise RuntimeError('ffmpeg 변환 결과 파일이 비어 있습니다.')

        logger.info(f'[convert] 변환 성공: {os.path.getsize(dst_path)} bytes')
        converted = open(dst_path, 'rb')
        new_filename = os.path.splitext(filename)[0] + '.mp3'
        return converted, new_filename
    except RuntimeError:
        raise
    except FileNotFoundError:
        raise RuntimeError('ffmpeg가 설치되지 않았습니다. sudo apt-get install -y ffmpeg')
    finally:
        if os.path.exists(src_path):
            os.unlink(src_path)


def transcribe_audio(audio_file):
    """오디오 파일을 텍스트로 변환 (OpenAI Whisper API)"""
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        return None, 'OPENAI_API_KEY가 설정되지 않았습니다.'

    converted_file = None
    try:
        file_obj, filename = _convert_to_mp3(audio_file)
        converted_file = file_obj if file_obj is not audio_file else None

        resp = requests.post(
            'https://api.openai.com/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {api_key}'},
            files={'file': (
                filename,
                file_obj,
                mimetypes.guess_type(filename)[0] or 'audio/mpeg',
            )},
            data={
                'model': 'whisper-1',
                'language': 'ko',
                'response_format': 'text',
            },
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.text.strip(), None
        else:
            error_msg = resp.json().get('error', {}).get('message', resp.text[:200])
            return None, f'Whisper API 오류: {error_msg}'
    except requests.Timeout:
        return None, '음성 변환 시간 초과 (2분). 파일이 너무 길 수 있습니다.'
    except RuntimeError as e:
        return None, str(e)
    except Exception as e:
        logger.exception('Whisper API error')
        return None, f'음성 변환 오류: {str(e)}'
    finally:
        if converted_file:
            path = converted_file.name
            converted_file.close()
            if os.path.exists(path):
                os.unlink(path)


def summarize_transcript(transcript):
    """통화 내용 요약 + 주문 여부 판별 (OpenAI GPT-4o)"""
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        return None, None, 'OPENAI_API_KEY가 설정되지 않았습니다.'

    prompt = f"""아래는 전화 통화를 텍스트로 변환한 내용입니다.

## 통화 내용
{transcript}

## 요청사항
1. 이 통화 내용을 1~2문장으로 간결하게 요약해주세요.
2. 이 통화가 도서/교재 주문과 관련된 통화인지 판별해주세요.

## 반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{"summary": "통화 요약 (1~2문장)", "is_order": true 또는 false}}"""

    result, err = _call_openai_chat(prompt)
    if err:
        return None, None, err
    return result.get('summary', ''), result.get('is_order', False), None


def _call_openai_chat(prompt, model='gpt-4o-mini'):
    """OpenAI Chat API 호출 (rate limit 자동 재시도)"""
    import time

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        return None, 'OPENAI_API_KEY가 설정되지 않았습니다.'

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': 2000,
                    'temperature': 0.1,
                },
                timeout=60,
            )

            # rate limit → 대기 후 재시도
            if resp.status_code == 429:
                wait = min(30, 2 ** attempt * 10)
                logger.warning(f'OpenAI rate limit, {wait}초 대기 (시도 {attempt + 1}/{max_retries})')
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                error_msg = resp.json().get('error', {}).get('message', resp.text[:200])
                return None, f'OpenAI API 오류: {error_msg}'

            content = resp.json()['choices'][0]['message']['content'].strip()

            # JSON 추출 (마크다운 코드블록 제거)
            if content.startswith('```'):
                content = content.split('\n', 1)[1]
                content = content.rsplit('```', 1)[0]
            content = content.strip()

            parsed = json.loads(content)
            return parsed, None

        except json.JSONDecodeError:
            return None, '파싱 결과를 해석할 수 없습니다.'
        except requests.Timeout:
            return None, '파싱 시간 초과.'
        except Exception as e:
            logger.exception('OpenAI API error')
            return None, f'파싱 오류: {str(e)}'

    return None, 'OpenAI API rate limit 초과 (재시도 실패)'


def parse_order_from_text(transcript, book_list):
    """텍스트에서 주문 정보 추출 (OpenAI GPT-4o)"""
    books_summary = '\n'.join(
        f'- [{b["id"]}] {b["publisher"]} / {b["series"]} / {b["name"]} (단가 {b["unit_price"]}원)'
        for b in book_list[:500]
    )

    prompt = f"""아래는 도서 주문 전화 통화를 텍스트로 변환한 내용입니다.
이 통화에서 주문 정보를 추출해주세요.

## 통화 내용
{transcript}

## 등록된 교재 목록
{books_summary}

## 추출 규칙
1. 선생님 이름, 학교명, 연락처를 찾아주세요
2. 주문한 교재와 수량을 매칭해주세요
3. 교재명이 정확하지 않아도 가장 유사한 교재를 매칭해주세요
4. 통화에서 언급된 메모/특이사항도 추출해주세요
5. 확신도가 낮은 항목은 confidence를 "low"로 표시해주세요

## 반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "teacher_name": "선생님 이름 또는 빈문자열",
  "school_name": "학교명 또는 빈문자열",
  "phone": "연락처 또는 빈문자열",
  "memo": "특이사항/메모",
  "items": [
    {{"book_id": 교재ID(숫자), "name": "교재명", "qty": 수량(숫자), "confidence": "high|low"}}
  ],
  "raw_mentions": ["통화에서 언급된 교재명 원문 목록"]
}}"""

    return _call_openai_chat(prompt)


def parse_order_from_email(sender, subject, body, book_list, agencies, teachers):
    """이메일 내용에서 주문 정보 추출 (OpenAI GPT-4o)"""
    books_summary = '\n'.join(
        f'- [{b["id"]}] {b["publisher"]} / {b["series"]} / {b["name"]} (단가 {b["unit_price"]}원)'
        for b in book_list[:500]
    )

    agencies_summary = '\n'.join(
        f'- [{a["id"]}] {a["name"]}' for a in agencies
    )

    teachers_summary = '\n'.join(
        f'- [{t["id"]}] {t["name"]} (업체: {t["agency_name"]}, 학교: {t["delivery_name"]})'
        for t in teachers[:500]
    )

    prompt = f"""아래는 도서 주문 이메일입니다. 이메일에서 주문 정보를 추출해주세요.

## 이메일 정보
- 발신자: {sender}
- 제목: {subject}

## 이메일 본문
{body}

## 등록된 업체 목록
{agencies_summary}

## 등록된 선생님 목록
{teachers_summary}

## 등록된 교재 목록
{books_summary}

## 추출 규칙
1. 발신자 이메일/이름에서 업체를 매칭해주세요. 업체 목록에서 가장 유사한 업체의 id를 찾아주세요.
2. 선생님 이름을 찾고, 선생님 목록에서 매칭되는 id를 찾아주세요.
3. 학교명, 배송지 주소, 연락처를 찾아주세요.
4. 주문한 교재와 수량을 교재 목록에서 매칭해주세요. 교재명이 정확하지 않아도 가장 유사한 교재를 매칭해주세요.
5. 확신도가 낮은 항목은 confidence를 "low"로 표시해주세요.
6. 정보가 없는 필드는 빈 문자열로 남겨주세요.

## 반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "agency_id": 업체ID(숫자) 또는 null,
  "agency_name": "매칭된 업체명 또는 빈문자열",
  "teacher_id": 선생님ID(숫자) 또는 null,
  "teacher_name": "선생님 이름 또는 빈문자열",
  "school_name": "학교명 또는 빈문자열",
  "phone": "연락처 또는 빈문자열",
  "address": "배송지 주소 또는 빈문자열",
  "memo": "특이사항/메모",
  "items": [
    {{"book_id": 교재ID(숫자), "name": "교재명", "qty": 수량(숫자), "confidence": "high|low"}}
  ],
  "raw_mentions": ["이메일에서 언급된 교재명 원문 목록"]
}}"""

    return _call_openai_chat(prompt)
