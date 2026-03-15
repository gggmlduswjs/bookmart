"""
주문 생성 시 관리자 이메일 알림 (근거자료 보관용)
- Order가 새로 생성될 때 post_save 시그널로 관리자 네이버 메일에 주문 내역 발송
- 이메일 발송 실패해도 주문 처리 흐름에 영향 없음
"""
import logging
import threading

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Order

logger = logging.getLogger(__name__)


def _send_admin_email(order_pk):
    """별도 스레드에서 관리자에게 주문 알림 이메일 발송"""
    try:
        from .models import Order, OrderItem
        from .email_utils import send_reply_email

        order = (
            Order.objects
            .select_related('agency', 'teacher', 'delivery')
            .prefetch_related('items', 'items__book', 'items__book__publisher')
            .get(pk=order_pk)
        )

        account_id = getattr(settings, 'NAVER_EMAIL_2_ID', '')
        account_pw = getattr(settings, 'NAVER_EMAIL_2_PW', '')
        if not account_id or not account_pw:
            logger.warning('관리자 이메일 미설정 — 주문 알림 발송 건너뜀')
            return

        admin_email = f'{account_id}@naver.com'

        # 주문 경로 한글
        source_display = dict(Order.Source.choices).get(order.source, order.source)

        # 교재 목록
        items = order.items.all()
        item_lines = []
        total = 0
        for item in items:
            name = item.book.name if item.book else item.custom_book_name
            publisher = item.book.publisher.name if item.book and item.book.publisher else ''
            price = item.list_price
            amount = price * item.quantity
            total += amount
            pub_str = f' ({publisher})' if publisher else ''
            item_lines.append(
                f'  - {name}{pub_str} × {item.quantity}권  '
                f'@{price:,}원 = {amount:,}원'
            )
        items_text = '\n'.join(item_lines) if item_lines else '  (항목 없음)'

        subject = f'[북마트 주문] {order.order_no} - {order.delivery.name} ({source_display})'

        body = (
            f'주문번호: {order.order_no}\n'
            f'주문경로: {source_display}\n'
            f'주문일시: {order.ordered_at.strftime("%Y-%m-%d %H:%M")}\n'
            f'\n'
            f'업체: {order.agency.name}\n'
            f'선생님: {order.teacher.name} ({order.teacher.phone})\n'
            f'배송지: {order.delivery.name}\n'
            f'주소: {order.delivery.address}\n'
        )
        if order.delivery.location_detail:
            body += f'위치상세: {order.delivery.location_detail}\n'
        if order.requested_delivery_date:
            body += f'요청배송일: {order.requested_delivery_date}\n'
        if order.memo:
            body += f'메모: {order.memo}\n'

        body += (
            f'\n'
            f'── 교재 목록 ──\n'
            f'{items_text}\n'
            f'──────────\n'
            f'합계: {total:,}원 (정가 기준)\n'
        )

        send_reply_email(account_id, account_pw, admin_email, subject, body)
        logger.info('관리자 주문 알림 메일 발송: %s', order.order_no)

    except Exception as e:
        logger.error('관리자 주문 알림 메일 실패 (order_pk=%s): %s', order_pk, e)


@receiver(post_save, sender=Order)
def order_created_notify_admin(sender, instance, created, **kwargs):
    """주문 신규 생성 시 관리자에게 이메일 발송 (비동기)"""
    if not created:
        return
    # 메인 스레드 블로킹 방지
    t = threading.Thread(target=_send_admin_email, args=(instance.pk,), daemon=True)
    t.start()
