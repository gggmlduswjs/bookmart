import json
import math

from django.contrib.contenttypes.models import ContentType

from accounts.models import User
from books.models import Book
from orders.models import AuditLog, SiteConfig


def _audit(request, action, target=None, detail=''):
    AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action,
        target_type=ContentType.objects.get_for_model(target) if target else None,
        target_id=target.pk if target else None,
        detail=detail,
        ip_address=request.META.get('REMOTE_ADDR'),
    )


def get_books_json(books=None, price_mode='supply'):
    """교재 목록을 JSON 문자열로 변환.
    price_mode: 'supply' (공급가), 'list' (정가)
    """
    if books is None:
        books = Book.objects.filter(is_active=True).select_related('publisher')
    data = []
    for b in books:
        item = {
            'id': b.id,
            'series': b.series or '기타',
            'name': b.name,
            'publisher': b.publisher.name,
        }
        if price_mode == 'supply':
            item['unit_price'] = math.floor(b.list_price * float(b.publisher.supply_rate) / 100)
        else:
            item['unit_price'] = b.list_price
        data.append(item)
    return json.dumps(data, ensure_ascii=False)


def get_agencies_json():
    """업체 목록 + JSON"""
    agencies = User.objects.filter(role='agency', is_active=True).order_by('name')
    agencies_json = json.dumps([{
        'id': a.pk, 'name': a.name,
    } for a in agencies], ensure_ascii=False)
    return agencies, agencies_json


def get_teachers_json():
    """선생님 목록 + JSON"""
    teachers = (
        User.objects.filter(role='teacher', is_active=True)
        .select_related('agency', 'delivery_address')
        .order_by('agency__name', 'name')
    )
    teachers_json = json.dumps([{
        'id': t.pk,
        'name': t.name,
        'phone': t.phone or '',
        'agency_id': t.agency_id,
        'delivery_id': t.delivery_address_id,
        'delivery_name': t.delivery_address.name if t.delivery_address else '',
        'delivery_address': t.delivery_address.address if t.delivery_address else '',
        'delivery_phone': t.delivery_address.phone if t.delivery_address else '',
        'has_delivery': bool(t.delivery_address),
    } for t in teachers], ensure_ascii=False)
    return teachers, teachers_json


def get_series_list(books=None):
    """시리즈 목록 (정렬됨)"""
    if books is None:
        books = Book.objects.filter(is_active=True)
    series = sorted(set(b.series for b in books if b.series))
    if any(not b.series for b in books):
        series.append('기타')
    return series


def get_deadlines(now):
    """마감시간 반환: (deadline_city, deadline_region, past_city, past_region)"""
    config = SiteConfig.get()
    deadline_city = now.replace(
        hour=config.deadline_city.hour, minute=config.deadline_city.minute,
        second=0, microsecond=0
    )
    deadline_region = now.replace(
        hour=config.deadline_region.hour, minute=config.deadline_region.minute,
        second=0, microsecond=0
    )
    return deadline_city, deadline_region, now > deadline_city, now > deadline_region
