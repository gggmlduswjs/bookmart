"""극동프로그램 엑셀 → bookmart 일괄 임포트"""
import math
from datetime import datetime
from decimal import Decimal

import openpyxl

from accounts.models import User
from books.models import Publisher
from orders.models import (
    DeliveryAddress, Order, OrderItem, Return, ReturnItem,
)


def parse_geukdong_excel(file):
    """극동프로그램 엑셀 파일을 파싱하여 학교별 주문 데이터 반환.

    Returns:
        list[dict]: [{
            'school': str,          # 학교명
            'phone': str,           # 연락처
            'items': [{
                'date': date,
                'book_name': str,
                'publisher': str,
                'quantity': int,     # 음수 = 반품
                'list_price': int,
                'unit_price': int,
                'supply_rate': int,  # 50, 55 등
                'amount': int,       # unit_price * quantity
            }],
            'subtotal': int,
        }]
    """
    wb = openpyxl.load_workbook(file, data_only=True)
    ws = wb.active

    schools = []
    current_school = None

    for row in ws.iter_rows(min_row=1, values_only=False):
        cells = {c.column_letter: c.value for c in row}
        a_val = cells.get('A')
        b_val = cells.get('B')

        # 헤더 행 스킵
        if a_val == '처리일자':
            continue

        # 거래처 구분 행
        if a_val and str(a_val).startswith('거래처명'):
            if current_school and current_school['items']:
                current_school['subtotal'] = sum(
                    i['amount'] for i in current_school['items']
                )
                schools.append(current_school)
            phone_raw = str(cells.get('C', '') or '')
            phone = phone_raw.replace('F:', '').strip()
            current_school = {
                'school': str(b_val or '').strip(),
                'phone': phone,
                'items': [],
            }
            continue

        # 합계 행 스킵
        if b_val and '합계' in str(b_val):
            continue
        # 기타 요약 행 스킵 (마루한, 입금 등)
        if not a_val and b_val and not cells.get('D'):
            continue
        if a_val and isinstance(a_val, str) and '.' in a_val and not cells.get('D'):
            continue

        # 데이터 행
        if current_school and a_val and cells.get('D') is not None:
            try:
                if isinstance(a_val, datetime):
                    item_date = a_val.date()
                elif isinstance(a_val, str):
                    # "2025.12-30" 같은 포맷 처리
                    cleaned = a_val.replace('.', '-')
                    item_date = datetime.strptime(cleaned[:10], '%Y-%m-%d').date()
                else:
                    continue

                quantity = int(cells.get('D', 0))
                list_price = int(cells.get('E', 0) or 0)
                unit_price = int(float(cells.get('F', 0) or 0))
                supply_rate = int(cells.get('G', 0) or 0)
                amount = int(float(cells.get('H', 0) or 0))

                current_school['items'].append({
                    'date': item_date,
                    'book_name': str(b_val or '').strip(),
                    'publisher': str(cells.get('C', '') or '').strip(),
                    'quantity': quantity,
                    'list_price': list_price,
                    'unit_price': unit_price,
                    'supply_rate': supply_rate,
                    'amount': amount,
                })
            except (ValueError, TypeError):
                continue

    # 마지막 학교
    if current_school and current_school['items']:
        current_school['subtotal'] = sum(
            i['amount'] for i in current_school['items']
        )
        schools.append(current_school)

    return schools


def import_geukdong_data(agency, schools_data, quarter_label=''):
    """파싱된 데이터를 bookmart에 임포트.

    Args:
        agency: User (agency role)
        schools_data: parse_geukdong_excel()의 반환값
        quarter_label: '2025년 4분기' 등 메모용

    Returns:
        dict: {'orders': int, 'returns': int, 'items': int, 'return_items': int}
    """
    # 임포트용 placeholder teacher
    teacher = _get_or_create_import_teacher(agency)

    stats = {'orders': 0, 'returns': 0, 'items': 0, 'return_items': 0}

    for school_data in schools_data:
        # 배송지(학교) 생성/조회
        delivery = _get_or_create_delivery(
            agency, school_data['school'], school_data['phone']
        )

        # 주문 항목과 반품 항목 분리
        order_items_by_date = {}
        return_items_by_date = {}

        for item in school_data['items']:
            d = item['date']
            if item['quantity'] > 0:
                order_items_by_date.setdefault(d, []).append(item)
            elif item['quantity'] < 0:
                return_items_by_date.setdefault(d, []).append(item)

        # 주문 생성 (날짜별)
        for order_date, items in order_items_by_date.items():
            order = Order(
                order_no=Order.generate_order_no(),
                agency=agency,
                teacher=teacher,
                delivery=delivery,
                status=Order.Status.DELIVERED,
                source=Order.Source.IMPORT,
                memo=f'극동임포트{": " + quarter_label if quarter_label else ""}',
                ordered_at=datetime.combine(order_date, datetime.min.time()),
            )
            order.save()
            stats['orders'] += 1

            bulk_items = []
            for item in items:
                bulk_items.append(OrderItem(
                    order=order,
                    book=None,
                    custom_book_name=item['book_name'],
                    quantity=item['quantity'],
                    list_price=item['list_price'],
                    supply_rate=Decimal(str(item['supply_rate'])),
                    unit_price=item['unit_price'],
                    amount=item['amount'],
                ))
            OrderItem.objects.bulk_create(bulk_items)
            stats['items'] += len(bulk_items)

        # 반품 생성 (날짜별)
        for return_date, items in return_items_by_date.items():
            ret = Return(
                return_no=Return.generate_return_no(),
                agency=agency,
                teacher=teacher,
                delivery=delivery,
                status=Return.Status.CONFIRMED,
                reason=Return.Reason.ETC,
                memo=f'극동임포트{": " + quarter_label if quarter_label else ""}',
                requested_at=datetime.combine(return_date, datetime.min.time()),
                confirmed_at=datetime.combine(return_date, datetime.min.time()),
            )
            ret.save()
            stats['returns'] += 1

            bulk_items = []
            for item in items:
                qty = abs(item['quantity'])
                unit_price = item['unit_price']
                amount = abs(item['amount'])
                bulk_items.append(ReturnItem(
                    ret=ret,
                    book=None,
                    custom_book_name=item['book_name'],
                    requested_qty=qty,
                    confirmed_qty=qty,
                    list_price=item['list_price'],
                    supply_rate=Decimal(str(item['supply_rate'])),
                    unit_price=unit_price,
                    requested_amount=amount,
                    confirmed_amount=amount,
                ))
            ReturnItem.objects.bulk_create(bulk_items)
            stats['return_items'] += len(bulk_items)

    return stats


def _get_or_create_import_teacher(agency):
    """임포트용 placeholder teacher."""
    login_id = f'_imp_{agency.pk}'
    teacher = User.objects.filter(login_id=login_id, role='teacher').first()
    if not teacher:
        teacher = User(
            login_id=login_id,
            role=User.Role.TEACHER,
            name=f'{agency.name} (임포트)',
            phone='',
            agency=agency,
            must_change_password=False,
        )
        teacher.set_unusable_password()
        teacher.save()
    return teacher


def _get_or_create_delivery(agency, school_name, phone=''):
    """학교명으로 배송지 조회/생성."""
    delivery = DeliveryAddress.objects.filter(
        agency=agency, name=school_name,
    ).first()
    if not delivery:
        delivery = DeliveryAddress.objects.create(
            agency=agency,
            name=school_name,
            mobile=phone,
        )
    return delivery
