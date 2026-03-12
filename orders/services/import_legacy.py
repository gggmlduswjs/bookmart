"""극동프로그램 엑셀 → bookmart 일괄 임포트"""
import math
import re
from datetime import datetime
from decimal import Decimal

import openpyxl

from accounts.models import User
from books.models import Publisher
from orders.models import (
    DeliveryAddress, Order, OrderItem, Return, ReturnItem,
)


# ── 업체명 매핑 (극동 거래처명 → bookmart 업체명) ────────────────────────────
# 거래처명 끝에 붙는 업체 식별자. 순서 중요: 긴 것 먼저 매칭.
AGENCY_KEYWORDS = [
    '참다솜교육', '참다솜',
    '더봄교육',
    '태정교육', '태정',
    '에스이',
    '에듀베스트',
    '아라',
    '마루한',
    '움터',
    '한방연',
    '포스쿨',
    '경상방과후',
    '미래교육',
    '아이샘',
    '바른방과후',
]


def detect_agency_name(school_name):
    """거래처명에서 업체명 추출. 못 찾으면 '기타'."""
    name = school_name.strip()
    # (2026) 같은 연도 표기 제거 후 매칭
    cleaned = re.sub(r'\(?\d{4}\)?$', '', name).strip()
    for kw in AGENCY_KEYWORDS:
        if kw in cleaned or kw in name:
            # 정규화: 참다솜 → 참다솜교육
            if kw == '참다솜':
                return '참다솜교육'
            if kw == '태정':
                return '태정교육'
            return kw
    return '기타'


def parse_geukdong_excel(file):
    """극동프로그램 엑셀 파일을 파싱하여 거래처별 주문 데이터 반환.

    Returns:
        list[dict]: [{
            'school': str,          # 거래처명(학교명)
            'phone': str,           # 연락처
            'agency_name': str,     # 추정 업체명
            'items': [{
                'date': date,
                'book_name': str,
                'publisher': str,
                'quantity': int,     # 음수 = 반품
                'list_price': int,
                'unit_price': int,
                'supply_rate': int,  # 50, 55, 100 등
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
            # "010-1234-5678 F:031-123-4567" → 전화번호만
            phone = phone_raw.split('F:')[0].strip()
            school_name = str(b_val or '').strip()
            current_school = {
                'school': school_name,
                'phone': phone,
                'agency_name': detect_agency_name(school_name),
                'items': [],
            }
            continue

        # 스킵할 행들
        if a_val == '전일잔액':
            continue
        if a_val == '기간누계':
            continue
        if b_val and '합계' in str(b_val):
            continue
        # 전표번호 행 (2260310002 형태) 스킵
        if a_val and isinstance(a_val, str) and re.match(r'^22\d{8}', str(a_val)):
            continue
        # 기타 요약 행 스킵
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
                    cleaned = a_val.replace('.', '-')
                    item_date = datetime.strptime(cleaned[:10], '%Y-%m-%d').date()
                else:
                    continue

                quantity = int(cells.get('D', 0))
                if quantity == 0:
                    continue  # 수금 행 등 스킵

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

    # 마지막 거래처
    if current_school and current_school['items']:
        current_school['subtotal'] = sum(
            i['amount'] for i in current_school['items']
        )
        schools.append(current_school)

    return schools


def import_all_geukdong(file, quarter_label=''):
    """극동 엑셀 전체를 bookmart에 임포트.
    업체를 자동 감지/생성하고, 모든 거래처+거래 데이터를 넣는다.

    Returns:
        dict with stats
    """
    schools = parse_geukdong_excel(file)

    stats = {
        'total_schools': len(schools),
        'agencies_created': 0,
        'orders': 0,
        'returns': 0,
        'items': 0,
        'return_items': 0,
        'skipped': 0,
    }

    # 업체별로 그룹핑
    from collections import defaultdict
    by_agency = defaultdict(list)
    for school in schools:
        by_agency[school['agency_name']].append(school)

    for agency_name, agency_schools in by_agency.items():
        # 업체 조회/생성
        agency = User.objects.filter(role='agency', name=agency_name).first()
        if not agency:
            login_id = f'ag_{agency_name[:10]}_{User.objects.count()}'
            agency = User(
                login_id=login_id,
                role=User.Role.AGENCY,
                name=agency_name,
                must_change_password=True,
            )
            agency.set_password('1234')
            agency.save()
            stats['agencies_created'] += 1

        result = import_geukdong_data(agency, agency_schools, quarter_label)
        stats['orders'] += result['orders']
        stats['returns'] += result['returns']
        stats['items'] += result['items']
        stats['return_items'] += result['return_items']

    return stats


def import_geukdong_data(agency, schools_data, quarter_label=''):
    """파싱된 데이터를 bookmart에 임포트.

    Args:
        agency: User (agency role)
        schools_data: parse_geukdong_excel()의 반환값
        quarter_label: '2025년 4분기' 등 메모용

    Returns:
        dict: {'orders': int, 'returns': int, 'items': int, 'return_items': int}
    """
    teacher = _get_or_create_import_teacher(agency)

    stats = {'orders': 0, 'returns': 0, 'items': 0, 'return_items': 0}

    for school_data in schools_data:
        delivery = _get_or_create_delivery(
            agency, school_data['school'], school_data['phone']
        )

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
            name=agency.name,
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
