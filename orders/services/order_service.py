"""주문 생성 공통 로직"""
from accounts.models import User
from orders.models import Order, OrderItem, DeliveryAddress
from books.models import Book


def parse_post_items(post_data):
    """POST 데이터에서 교재 항목 파싱.
    Returns list of dicts: [{'book_id': int, 'qty': int} | {'custom_name': str, 'custom_price': int, 'qty': int}]
    """
    items = []
    i = 0
    while f'book_{i}' in post_data or f'custom_name_{i}' in post_data:
        book_id = post_data.get(f'book_{i}', '').strip()
        custom_name = post_data.get(f'custom_name_{i}', '').strip()
        custom_price = post_data.get(f'custom_price_{i}', '').strip()
        qty_str = post_data.get(f'qty_{i}', '').strip()
        if book_id and qty_str:
            try:
                qty = int(qty_str)
                if qty > 0:
                    items.append({'book_id': int(book_id), 'qty': qty})
            except (ValueError, TypeError):
                pass
        elif custom_name and qty_str:
            try:
                qty = int(qty_str)
                price = int(custom_price) if custom_price else 0
                if qty > 0:
                    items.append({'custom_name': custom_name, 'custom_price': price, 'qty': qty})
            except (ValueError, TypeError):
                pass
        i += 1
    return items


def resolve_teacher(teacher_id, new_name, new_phone, agency):
    """선생님 조회 또는 신규 생성.
    Returns (teacher, error_message). error_message is None on success.
    """
    if teacher_id:
        try:
            teacher = User.objects.select_related('delivery_address').get(
                pk=teacher_id, role='teacher', is_active=True
            )
            return teacher, None
        except (User.DoesNotExist, ValueError):
            return None, '선생님을 선택해 주세요.'
    elif new_name:
        login_id = f'a_{new_phone or "nophone"}_{agency.pk}'
        if User.objects.filter(login_id=login_id).exists():
            return User.objects.get(login_id=login_id), None
        teacher = User(
            login_id=login_id, role='teacher',
            name=new_name, phone=new_phone,
            agency=agency, must_change_password=False,
        )
        teacher.set_unusable_password()
        teacher.save()
        return teacher, None
    return None, '선생님을 선택하거나 새로 입력해 주세요.'


def resolve_delivery(delivery_school, address, phone, agency, teacher, location_detail=''):
    """배송지 조회/생성 후 teacher에 할당.
    Returns (delivery, error_message). error_message is None on success.
    """
    if delivery_school:
        defaults = {'address': address, 'phone': phone}
        if location_detail:
            defaults['location_detail'] = location_detail
        delivery, created = DeliveryAddress.objects.get_or_create(
            agency=agency, name=delivery_school,
            defaults=defaults,
        )
        if not created and address:
            delivery.address = address
            delivery.phone = phone
            if location_detail:
                delivery.location_detail = location_detail
            delivery.save(update_fields=['address', 'phone', 'location_detail'])
        teacher.delivery_address = delivery
        teacher.save(update_fields=['delivery_address'])
        return delivery, None
    elif teacher.delivery_address:
        return teacher.delivery_address, None
    return None, '배송지를 입력해 주세요.'


def create_order_items(order, items):
    """주문 항목 생성 (book_id 또는 custom_name)"""
    for item in items:
        if 'book_id' in item:
            try:
                book = Book.objects.get(id=item['book_id'], is_active=True)
                OrderItem(order=order, book=book, quantity=item['qty']).save()
            except Book.DoesNotExist:
                pass
        else:
            OrderItem(
                order=order, custom_book_name=item['custom_name'],
                unit_price=item['custom_price'], quantity=item['qty'],
            ).save()
