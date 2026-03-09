import json
import math
from functools import wraps

from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404

from accounts.models import User
from books.models import Book
from .models import Order, OrderItem, DeliveryAddress, LinkAccessLog
from .sms import send_order_confirmation


def _get_agency_or_404(slug):
    """slug 또는 code로 업체 조회, 없거나 비활성이면 404"""
    try:
        # 짧은 코드 먼저 시도
        agency = User.objects.get(agency_code=slug, role='agency', is_active=True)
    except User.DoesNotExist:
        try:
            # 기존 UUID 호환
            agency = User.objects.get(agency_slug=slug, role='agency', is_active=True)
        except (User.DoesNotExist, ValueError):
            raise Http404
    return agency


def _get_session_teacher(request, agency):
    """세션에서 teacher 조회. 없거나 불일치 시 None"""
    teacher_id = request.session.get('simple_teacher_id')
    session_code = request.session.get('simple_agency_code') or request.session.get('simple_agency_slug')
    if not teacher_id or (str(session_code) != str(agency.agency_code) and str(session_code) != str(agency.agency_slug)):
        return None
    try:
        return User.objects.get(pk=teacher_id, role='teacher', agency=agency, is_active=True)
    except User.DoesNotExist:
        return None


def simple_session_required(view_func):
    """세션에 teacher 정보가 없으면 landing으로 리다이렉트"""
    @wraps(view_func)
    def wrapper(request, slug, *args, **kwargs):
        agency = _get_agency_or_404(slug)
        teacher = _get_session_teacher(request, agency)
        if not teacher:
            return redirect('simple_landing', slug=slug)
        request.simple_agency = agency
        request.simple_teacher = teacher
        return view_func(request, slug, *args, **kwargs)
    return wrapper


# ── Landing: 가입/인증 ──────────────────────────────────────────────────────────

def simple_landing(request, slug):
    agency = _get_agency_or_404(slug)

    # 접속 이력 기록 (GET only)
    if request.method == 'GET':
        LinkAccessLog.objects.create(
            agency=agency,
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0].strip(),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            action='visit',
        )

    # 이미 세션 있으면 주문 페이지로
    teacher = _get_session_teacher(request, agency)
    if teacher:
        return redirect('simple_order', slug=slug)

    error = None
    active_tab = 'new'

    if request.method == 'POST':
        mode = request.POST.get('mode', 'new')

        if mode == 'lookup':
            # ── 주문내역 확인 모드: 이름+전화번호만으로 세션 복구 ──
            active_tab = 'lookup'
            lookup_name = request.POST.get('lookup_name', '').strip()
            lookup_phone = request.POST.get('lookup_phone', '').strip()

            if not lookup_name or not lookup_phone:
                error = '이름과 전화번호를 모두 입력해주세요.'
            else:
                teacher = User.objects.filter(
                    phone=lookup_phone, name=lookup_name,
                    role='teacher', agency=agency, is_active=True
                ).first()

                if not teacher:
                    error = '일치하는 주문 정보를 찾을 수 없습니다. 이름과 전화번호를 확인해주세요.'
                else:
                    request.session['simple_teacher_id'] = teacher.pk
                    request.session['simple_agency_code'] = str(agency.agency_code)
                    return redirect('simple_order_list', slug=slug)

        else:
            # ── 신규 주문 모드 ──
            name = request.POST.get('name', '').strip()
            phone = request.POST.get('phone', '').strip()
            school = request.POST.get('school', '').strip()
            address_main = request.POST.get('address', '').strip()
            address_detail = request.POST.get('address_detail', '').strip()
            address = f'{address_main} {address_detail}'.strip() if address_main else ''

            if not phone:
                error = '전화번호를 입력해주세요.'
            elif not name:
                error = '이름을 입력해주세요.'
            elif not school:
                error = '학교명을 입력해주세요.'
            elif not address:
                error = '배송주소를 입력해주세요.'
            else:
                # 전화번호로 기존 유저 검색 (같은 업체 소속)
                existing = User.objects.filter(
                    phone=phone, role='teacher', agency=agency, is_active=True
                ).first()

                if existing:
                    teacher = existing
                else:
                    # 신규 유저 생성
                    login_id = f's_{phone}_{agency.pk}'
                    # login_id 중복 방지
                    if User.objects.filter(login_id=login_id).exists():
                        # 이미 존재하면 해당 유저 사용
                        teacher = User.objects.get(login_id=login_id)
                    else:
                        teacher = User(
                            login_id=login_id,
                            role='teacher',
                            name=name,
                            phone=phone,
                            agency=agency,
                            must_change_password=False,
                        )
                        teacher.set_unusable_password()
                        teacher.save()
                        LinkAccessLog.objects.create(
                            agency=agency, teacher=teacher,
                            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0].strip(),
                            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                            action='register',
                        )

                    # 배송지(학교) 생성 또는 매칭
                    delivery, _ = DeliveryAddress.objects.get_or_create(
                        agency=agency,
                        name=school,
                        defaults={'address': address, 'phone': phone},
                    )
                    teacher.delivery_address = delivery
                    teacher.save(update_fields=['delivery_address'])

                # 세션에 저장
                request.session['simple_teacher_id'] = teacher.pk
                request.session['simple_agency_code'] = str(agency.agency_code)
                return redirect('simple_order', slug=slug)

    return render(request, 'simple/landing.html', {
        'agency': agency,
        'error': error,
        'slug': slug,
        'active_tab': active_tab,
    })


# ── 주문 ────────────────────────────────────────────────────────────────────────

@simple_session_required
def simple_order(request, slug):
    agency = request.simple_agency
    teacher = request.simple_teacher
    delivery = teacher.delivery_address

    if not delivery:
        return redirect('simple_landing', slug=slug)

    books = Book.objects.filter(is_active=True).select_related('publisher')
    series_list = sorted(set(b.series for b in books if b.series))
    books_json = json.dumps([{
        'id': b.id,
        'series': b.series or '기타',
        'name': b.name,
        'publisher': b.publisher.name,
        'unit_price': math.floor(b.list_price * float(b.publisher.supply_rate) / 100),
    } for b in books], ensure_ascii=False)

    error = None

    if request.method == 'POST':
        items = []
        i = 0
        while f'book_{i}' in request.POST:
            book_id = request.POST.get(f'book_{i}', '').strip()
            qty_str = request.POST.get(f'qty_{i}', '').strip()
            if book_id and qty_str:
                try:
                    qty = int(qty_str)
                    if qty > 0:
                        items.append((int(book_id), qty))
                except (ValueError, TypeError):
                    pass
            i += 1

        if not items:
            error = '주문할 교재를 1권 이상 선택하세요.'
        else:
            order = Order.objects.create(
                order_no=Order.generate_order_no(),
                agency=agency,
                teacher=teacher,
                delivery=delivery,
                memo=request.POST.get('memo', ''),
            )
            for book_id, qty in items:
                try:
                    book = Book.objects.get(id=book_id, is_active=True)
                    OrderItem(order=order, book=book, quantity=qty).save()
                except Book.DoesNotExist:
                    pass

            LinkAccessLog.objects.create(
                agency=agency, teacher=teacher,
                ip_address=request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', '')).split(',')[0].strip(),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                action='order',
            )
            send_order_confirmation(order)
            return redirect('simple_confirm', slug=slug, order_id=order.pk)

    return render(request, 'simple/order.html', {
        'agency': agency,
        'teacher': teacher,
        'delivery': delivery,
        'series_list': series_list,
        'books_json': books_json,
        'slug': slug,
        'error': error,
    })


# ── 주문 확인 ───────────────────────────────────────────────────────────────────

@simple_session_required
def simple_confirm(request, slug, order_id):
    teacher = request.simple_teacher
    order = get_object_or_404(Order, pk=order_id, teacher=teacher)
    items = order.items.select_related('book', 'book__publisher')

    return render(request, 'simple/confirm.html', {
        'agency': request.simple_agency,
        'order': order,
        'items': items,
        'slug': slug,
    })


# ── 주문 내역 ───────────────────────────────────────────────────────────────────

@simple_session_required
def simple_order_list(request, slug):
    teacher = request.simple_teacher
    orders = Order.objects.filter(teacher=teacher).order_by('-ordered_at')

    return render(request, 'simple/order_list.html', {
        'agency': request.simple_agency,
        'orders': orders,
        'slug': slug,
    })
