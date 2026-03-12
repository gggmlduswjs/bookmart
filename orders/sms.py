"""
알리고 SMS 발송 헬퍼
- 발송 실패 시 예외를 밖으로 던지지 않음 (주문 처리 흐름 유지)
- settings에 ALIGO_* 값이 없으면 발송 시도 안 함
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ALIGO_URL = 'https://apis.aligo.in/send/'


def send_sms(receiver: str, message: str) -> bool:
    """
    SMS 발송. 성공이면 True, 실패/미설정이면 False 반환.
    receiver: 수신 번호 (하이픈 있어도 없어도 됨)
    message : 발송 내용 (90바이트 초과 시 자동 LMS)
    """
    api_key = getattr(settings, 'ALIGO_API_KEY', '')
    user_id = getattr(settings, 'ALIGO_USER_ID', '')
    sender  = getattr(settings, 'ALIGO_SENDER', '')

    if not (api_key and user_id and sender):
        logger.warning(f'SMS 미설정: api_key={bool(api_key)}, user_id={bool(user_id)}, sender={bool(sender)}')
        return False

    if not receiver:
        logger.warning('SMS 수신번호 없음')
        return False

    # 90바이트 초과 시 LMS (알리고가 자동으로 처리하지만 명시)
    msg_bytes = message.encode('euc-kr', errors='replace')
    msg_type = 'LMS' if len(msg_bytes) > 90 else 'SMS'

    try:
        clean_receiver = receiver.replace('-', '')
        resp = requests.post(ALIGO_URL, data={
            'key':      api_key,
            'userid':   user_id,
            'sender':   sender.replace('-', ''),
            'receiver': clean_receiver,
            'msg':      message,
            'msg_type': msg_type,
        }, timeout=10)
        result = resp.json()
        logger.info('알리고 응답: %s', result)
        success = str(result.get('result_code')) == '1'
        if not success:
            logger.warning('알리고 발송 실패: %s', result)
            # 에러 메시지를 last_error에 저장해서 뷰에서 참조 가능
            send_sms._last_error = result.get('message', str(result))
        return success
    except Exception as e:
        logger.error('SMS 발송 오류: %s', e)
        send_sms._last_error = str(e)
        return False


def send_ship_notification(order) -> bool:
    """발송처리 완료 문자 — order_ship 뷰에서 호출"""
    teacher = order.teacher
    receiver = teacher.phone or teacher.mobile  # 등록된 번호 사용

    if order.carrier == 'hanjin' and order.tracking_no:
        delivery_part = f'\n운송장: {order.tracking_no}(한진택배)'
    elif order.carrier == 'direct':
        delivery_part = '\n(직접배송)'
    else:
        delivery_part = ''
    message = (
        f'[북마트] {teacher.name} 선생님\n'
        f'{order.delivery.name} 교재 발송됐습니다.'
        f'{delivery_part}'
    )
    return send_sms(receiver, message)


def send_order_confirmation(order) -> bool:
    """주문 접수 완료 문자"""
    teacher = order.teacher
    receiver = teacher.phone
    message = (
        f'[북마트] {teacher.name} 선생님\n'
        f'{order.delivery.name} 교재 주문이 접수되었습니다.\n'
        f'주문번호: {order.order_no}'
    )
    return send_sms(receiver, message)


def send_delivery_notification(order) -> bool:
    """배송 완료 문자"""
    teacher = order.teacher
    receiver = teacher.phone
    message = (
        f'[북마트] {teacher.name} 선생님\n'
        f'{order.delivery.name} 교재가 배송 완료되었습니다.'
    )
    return send_sms(receiver, message)
