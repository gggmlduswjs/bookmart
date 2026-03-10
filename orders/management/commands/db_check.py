from django.core.management.base import BaseCommand
from accounts.models import User
from books.models import Publisher, Book
from orders.models import (
    DeliveryAddress, Order, OrderItem, Return,
    InboxMessage, InboxAttachment, Payment,
)


class Command(BaseCommand):
    help = 'DB 현황 확인'

    def handle(self, *args, **options):
        self.stdout.write('=== DB 현황 ===')
        admin_cnt = User.objects.filter(role='admin').count()
        agency_cnt = User.objects.filter(role='agency').count()
        teacher_cnt = User.objects.filter(role='teacher').count()
        self.stdout.write(f'사용자: {User.objects.count()}건 (admin:{admin_cnt}, agency:{agency_cnt}, teacher:{teacher_cnt})')
        self.stdout.write(f'출판사: {Publisher.objects.count()}건')
        self.stdout.write(f'교재: {Book.objects.count()}건')
        self.stdout.write(f'배송지: {DeliveryAddress.objects.count()}건')
        self.stdout.write(f'주문: {Order.objects.count()}건')
        self.stdout.write(f'주문상세: {OrderItem.objects.count()}건')
        self.stdout.write(f'반품: {Return.objects.count()}건')
        self.stdout.write(f'수신메일: {InboxMessage.objects.filter(source="email").count()}건')
        self.stdout.write(f'수신문자: {InboxMessage.objects.filter(source="sms").count()}건')
        self.stdout.write(f'첨부파일: {InboxAttachment.objects.count()}건')
        self.stdout.write(f'입금내역: {Payment.objects.count()}건')
        self.stdout.write('')

        self.stdout.write('=== 업체 목록 ===')
        for a in User.objects.filter(role='agency', is_active=True):
            t_cnt = User.objects.filter(agency=a, role='teacher').count()
            d_cnt = DeliveryAddress.objects.filter(agency=a).count()
            self.stdout.write(f'  {a.name} | 선생님:{t_cnt}명 | 배송지:{d_cnt}곳')

        self.stdout.write('')
        self.stdout.write('=== 최근 주문 10건 ===')
        for o in Order.objects.select_related('agency', 'teacher', 'delivery')[:10]:
            items = o.items.count()
            self.stdout.write(
                f'  {o.order_no} | {o.agency.name} | {o.teacher.name} | '
                f'{o.delivery.name} | {o.status} | {items}품목 | {o.ordered_at:%m/%d %H:%M}'
            )

        self.stdout.write('')
        self.stdout.write('=== 최근 주문 상세 ===')
        for o in Order.objects.all()[:3]:
            self.stdout.write(f'  [{o.order_no}]')
            for item in o.items.select_related('book', 'book__publisher').all():
                book_info = f'book_id={item.book_id}' if item.book_id else f'custom="{item.custom_book_name}"'
                self.stdout.write(
                    f'    {item.display_name} | {item.display_publisher} | '
                    f'단가:{item.unit_price} | 수량:{item.quantity} | 금액:{item.amount} | {book_info}'
                )
