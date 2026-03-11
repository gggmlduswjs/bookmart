"""
통화녹음 → 주문 자동 파싱
1. 오디오 파일 → OpenAI Whisper API → 텍스트
2. 텍스트 → Anthropic Claude API → 구조화된 주문 정보
"""
import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def transcribe_audio(audio_file):
    """오디오 파일을 텍스트로 변환 (OpenAI Whisper API)"""
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        return None, 'OPENAI_API_KEY가 설정되지 않았습니다.'

    try:
        resp = requests.post(
            'https://api.openai.com/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {api_key}'},
            files={'file': (audio_file.name, audio_file, audio_file.content_type or 'audio/mpeg')},
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
    except Exception as e:
        logger.exception('Whisper API error')
        return None, f'음성 변환 오류: {str(e)}'


def parse_order_from_text(transcript, book_list):
    """텍스트에서 주문 정보 추출 (Anthropic Claude API)"""
    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        return None, 'ANTHROPIC_API_KEY가 설정되지 않았습니다.'

    # 교재 목록을 간결하게 전달
    books_summary = '\n'.join(
        f'- [{b["id"]}] {b["publisher"]} / {b["series"]} / {b["name"]} (단가 {b["unit_price"]}원)'
        for b in book_list[:500]  # 너무 많으면 자르기
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

    try:
        resp = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json={
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 2000,
                'messages': [{'role': 'user', 'content': prompt}],
            },
            timeout=60,
        )

        if resp.status_code != 200:
            error_msg = resp.json().get('error', {}).get('message', resp.text[:200])
            return None, f'Claude API 오류: {error_msg}'

        content = resp.json()['content'][0]['text'].strip()

        # JSON 추출 (마크다운 코드블록 제거)
        if content.startswith('```'):
            content = content.split('\n', 1)[1]
            content = content.rsplit('```', 1)[0]
        content = content.strip()

        parsed = json.loads(content)
        return parsed, None

    except json.JSONDecodeError:
        return None, f'주문 파싱 결과를 해석할 수 없습니다.'
    except requests.Timeout:
        return None, '주문 파싱 시간 초과.'
    except Exception as e:
        logger.exception('Claude API error')
        return None, f'주문 파싱 오류: {str(e)}'
