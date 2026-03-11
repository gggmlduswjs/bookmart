import json
import math

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.core.paginator import Paginator

from accounts.decorators import role_required
from accounts.models import User
from books.models import Book
from orders.models import Order, OrderItem, DeliveryAddress, AuditLog, OrderStatusLog
from orders.services import get_order_queryset, get_delivery_queryset
from orders.services.order_service import parse_post_items, resolve_teacher, resolve_delivery, create_order_items
from ._helpers import _audit, get_books_json, get_agencies_json, get_teachers_json, get_series_list


@login_required
def order_list(request):
    qs = get_order_queryset(request.user)
    qs = qs.filter(is_deleted=False)

    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    delivery_id = request.GET.get('delivery', '')
    source = request.GET.get('source', '')
    q = request.GET.get('q', '').strip()

    if status:
        qs = qs.filter(status=status)
    if date_from:
        qs = qs.filter(ordered_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(ordered_at__date__lte=date_to)
    if delivery_id:
        qs = qs.filter(delivery_id=delivery_id)
    if source:
        qs = qs.filter(source=source)
    if q:
        qs = qs.filter(
            Q(order_no__icontains=q) |
            Q(teacher__name__icontains=q) |
            Q(delivery__name__icontains=q) |
            Q(agency__name__icontains=q) |
            Q(tracking_no__icontains=q)
        )

    now = timezone.localtime()
    deadline_city = now.replace(hour=11, minute=20, second=0, microsecond=0)
    deadline_region = now.replace(hour=13, minute=50, second=0, microsecond=0)
    past_city = now > deadline_city
    past_region = now > deadline_region

    deliveries = get_delivery_queryset(request.user)

    page_number = request.GET.get('page', 1)
    paginator = Paginator(qs.order_by('-ordered_at'), 50)
    page_obj = paginator.get_page(page_number)

    return render(request, 'orders/order_list.html', {
        'orders': page_obj, 'page_obj': page_obj,
        'deliveries': deliveries,
        'status_choices': Order.Status.choices,
        'filters': {
            'status': status, 'date_from': date_from,
            'date_to': date_to, 'delivery': delivery_id,
            'source': source, 'q': q,
        },
        'past_city': past_city,
        'past_region': past_region,
    })


@role_required('teacher')
def order_create(request):
    user = request.user
    delivery = user.delivery_address
    if not delivery:
        messages.error(request, '담당 학교가 지정되지 않았습니다. 업체에 문의하세요.')
        return redirect('home')

    now = timezone.localtime()
    deadline_city = now.replace(hour=11, minute=20, second=0, microsecond=0)
    deadline_region = now.replace(hour=13, minute=50, second=0, microsecond=0)
    past_city = now > deadline_city
    past_region = now > deadline_region

    books = Book.objects.filter(is_active=True).select_related('publisher')
    series_list = sorted(set(b.series for b in books if b.series))
    books_json = get_books_json(books)

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
            messages.error(request, '주문할 교재를 1권 이상 선택하세요.')
        else:
            order = Order.objects.create(
                order_no=Order.generate_order_no(),
                agency=user.agency,
                teacher=user,
                delivery=delivery,
                memo=request.POST.get('memo', ''),
                source=Order.Source.SIMPLE,
            )
            for book_id, qty in items:
                try:
                    book = Book.objects.get(id=book_id, is_active=True)
                    OrderItem(order=order, book=book, quantity=qty).save()
                except Book.DoesNotExist:
                    pass
            OrderStatusLog.objects.create(
                order=order, old_status='', new_status='pending',
                changed_by=user, memo='주문 생성',
            )
            _audit(request, AuditLog.Action.ORDER_CREATE, order, f'주문 {order.order_no} 생성')
            messages.success(request, f'주문 완료. 주문번호: {order.order_no}')
            return redirect('order_detail', pk=order.pk)

    return render(request, 'orders/order_create.html', {
        'delivery': delivery,
        'series_list': series_list,
        'books_json': books_json,
        'past_city': past_city,
        'past_region': past_region,
        'now_str': now.strftime('%H:%M'),
    })


@role_required('agency')
def individual_order_create(request):
    """개인선생님이 직접 교재를 주문하는 뷰"""
    user = request.user
    if not user.is_individual:
        messages.error(request, '개인선생님만 이용할 수 있습니다.')
        return redirect('home')

    teacher = user.individual_teacher
    deliveries = DeliveryAddress.objects.filter(agency=user, is_active=True).order_by('name')

    books = Book.objects.filter(is_active=True).select_related('publisher')
    series_list = sorted(set(b.series for b in books if b.series))
    books_json = get_books_json(books, price_mode='list')

    if request.method == 'POST':
        delivery_id = request.POST.get('delivery_id', '').strip()
        new_delivery_name = request.POST.get('new_delivery_name', '').strip()
        new_delivery_address = request.POST.get('new_delivery_address', '').strip()
        new_delivery_phone = request.POST.get('new_delivery_phone', '').strip()

        delivery = None
        if delivery_id:
            try:
                delivery = DeliveryAddress.objects.get(pk=delivery_id, agency=user, is_active=True)
            except DeliveryAddress.DoesNotExist:
                messages.error(request, '선택한 배송지를 찾을 수 없습니다.')
                return redirect('individual_order_create')
        elif new_delivery_name:
            delivery = DeliveryAddress.objects.create(
                agency=user,
                name=new_delivery_name,
                address=new_delivery_address,
                phone=new_delivery_phone,
            )
        else:
            messages.error(request, '배송지를 선택하거나 새로 입력해 주세요.')
            return redirect('individual_order_create')

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
            messages.error(request, '주문할 교재를 1권 이상 선택하세요.')
        else:
            teacher.delivery_address = delivery
            teacher.save(update_fields=['delivery_address'])

            order = Order.objects.create(
                order_no=Order.generate_order_no(),
                agency=user,
                teacher=teacher,
                delivery=delivery,
                memo=request.POST.get('memo', ''),
                source=Order.Source.ADMIN,
            )
            for book_id, qty in items:
                try:
                    book = Book.objects.get(id=book_id, is_active=True)
                    OrderItem(order=order, book=book, quantity=qty).save()
                except Book.DoesNotExist:
                    pass
            OrderStatusLog.objects.create(
                order=order, old_status='', new_status='pending',
                changed_by=user, memo='개인선생님 주문',
            )
            _audit(request, AuditLog.Action.ORDER_CREATE, order, f'[개인] 주문 {order.order_no} 생성')
            messages.success(request, f'주문 완료. 주문번호: {order.order_no}')
            return redirect('order_detail', pk=order.pk)

    return render(request, 'orders/individual_order_create.html', {
        'deliveries': deliveries,
        'series_list': series_list,
        'books_json': books_json,
    })


@login_required
def order_detail(request, pk):
    order = get_object_or_404(get_order_queryset(request.user), pk=pk)
    items = order.items.select_related('book', 'book__publisher')
    status_logs = order.status_logs.select_related('changed_by')
    return render(request, 'orders/order_detail.html', {
        'order': order,
        'items': items,
        'status_logs': status_logs,
        'can_cancel': (
            order.status == Order.Status.PENDING
            and (
                (request.user.role == 'teacher' and order.teacher == request.user)
                or (request.user.is_individual_agency and order.agency == request.user)
            )
        ),
        'can_ship': (
            request.user.role == 'admin'
            and order.status == Order.Status.PENDING
        ),
        'can_deliver': (
            request.user.role == 'admin'
            and order.status == Order.Status.SHIPPING
        ),
    })


@role_required('admin')
def order_copy(request, pk):
    """기존 주문을 복사하여 새 주문 생성"""
    src = get_object_or_404(Order, pk=pk)
    src_items = list(src.items.select_related('book', 'book__publisher'))

    new_order = Order.objects.create(
        order_no=Order.generate_order_no(),
        agency=src.agency,
        teacher=src.teacher,
        delivery=src.delivery,
        source=Order.Source.ADMIN,
        memo=f'[복사] {src.order_no}',
    )
    for item in src_items:
        OrderItem.objects.create(
            order=new_order,
            book=item.book,
            custom_book_name=item.custom_book_name,
            quantity=item.quantity,
            list_price=item.list_price,
            supply_rate=item.supply_rate,
            unit_price=item.unit_price,
            amount=item.amount,
        )
    messages.success(request, f'주문 {src.order_no}를 복사하여 새 주문 {new_order.order_no}을 생성했습니다.')
    return redirect('order_detail', pk=new_order.pk)


@role_required('admin')
def order_edit(request, pk):
    order = get_object_or_404(Order, pk=pk)
    items = list(order.items.select_related('book', 'book__publisher'))

    books = Book.objects.filter(is_active=True).select_related('publisher')
    series_list = get_series_list(books)
    books_json = get_books_json(books)

    existing_rows = json.dumps([{
        'series': item.book.series or '기타' if item.book else '',
        'book_id': str(item.book_id) if item.book_id else '',
        'qty': item.quantity,
        'unit_price': item.unit_price,
        'is_custom': not item.book_id,
        'custom_name': item.custom_book_name or '',
    } for item in items], ensure_ascii=False)

    if request.method == 'POST':
        submitted_updated_at = request.POST.get('updated_at', '')
        if submitted_updated_at:
            from datetime import datetime as dt
            try:
                submitted_ts = dt.fromisoformat(submitted_updated_at)
                if order.updated_at and order.updated_at.replace(microsecond=0) > submitted_ts.replace(microsecond=0):
                    messages.error(request, '다른 사용자가 이 주문을 수정했습니다. 새로고침 후 다시 시도해주세요.')
                    return redirect('order_edit', pk=pk)
            except (ValueError, TypeError):
                pass

        order.memo = request.POST.get('memo', '')
        order.carrier = request.POST.get('carrier', '').strip()
        order.tracking_no = request.POST.get('tracking_no', '').strip() if order.carrier == 'hanjin' else ''
        order.save(update_fields=['memo', 'carrier', 'tracking_no'])

        delivery = order.delivery
        new_school = request.POST.get('delivery_school', '').strip()
        new_addr = request.POST.get('delivery_address', '').strip()
        new_phone = request.POST.get('delivery_phone', '').strip()
        if new_school and new_school != delivery.name:
            delivery, _ = DeliveryAddress.objects.get_or_create(
                agency=order.agency, name=new_school,
                defaults={'address': new_addr, 'phone': new_phone},
            )
            order.delivery = delivery
            order.save(update_fields=['delivery'])
        if new_addr:
            delivery.address = new_addr
            delivery.save(update_fields=['address'])
        if new_phone:
            delivery.phone = new_phone
            delivery.save(update_fields=['phone'])

        new_items = parse_post_items(request.POST)

        if not new_items:
            messages.error(request, '주문 품목이 1건 이상 있어야 합니다.')
        else:
            order.items.all().delete()
            create_order_items(order, new_items)
            messages.success(request, '주문이 수정되었습니다.')
            _audit(request, AuditLog.Action.ORDER_EDIT, order, f'주문 {order.order_no} 수정')
            return redirect('order_detail', pk=order.pk)

    return render(request, 'orders/order_edit.html', {
        'order': order,
        'items': items,
        'series_list': series_list,
        'books_json': books_json,
        'existing_rows': existing_rows,
    })


@role_required('admin')
def order_create_admin(request):
    """총판이 전화 주문을 받아 대신 입력하는 뷰"""
    agencies, agencies_json = get_agencies_json()
    teachers, teachers_json = get_teachers_json()

    now = timezone.localtime()
    deadline_city = now.replace(hour=11, minute=20, second=0, microsecond=0)
    deadline_region = now.replace(hour=13, minute=50, second=0, microsecond=0)
    past_city = now > deadline_city
    past_region = now > deadline_region

    books = Book.objects.filter(is_active=True).select_related('publisher')
    series_list = get_series_list(books)
    books_json = get_books_json(books)

    if request.method == 'POST':
        agency_id = request.POST.get('agency_id', '').strip()
        try:
            agency = User.objects.get(pk=agency_id, role='agency', is_active=True)
        except (User.DoesNotExist, ValueError):
            messages.error(request, '업체를 선택해 주세요.')
            return redirect('order_create_admin')

        teacher, err = resolve_teacher(
            request.POST.get('teacher_id', '').strip(),
            request.POST.get('new_teacher_name', '').strip(),
            request.POST.get('new_teacher_phone', '').strip(),
            agency,
        )
        if err:
            messages.error(request, err)
            return redirect('order_create_admin')

        delivery, err = resolve_delivery(
            request.POST.get('delivery_school', '').strip(),
            request.POST.get('delivery_address', '').strip(),
            request.POST.get('delivery_phone', '').strip(),
            agency, teacher,
        )
        if err:
            messages.error(request, err)
            return redirect('order_create_admin')

        items = parse_post_items(request.POST)

        if not items:
            messages.error(request, '주문할 교재를 1권 이상 선택하세요.')
        else:
            order = Order.objects.create(
                order_no=Order.generate_order_no(),
                agency=agency,
                teacher=teacher,
                delivery=teacher.delivery_address,
                memo=request.POST.get('memo', ''),
                source=Order.Source.ADMIN,
            )
            create_order_items(order, items)
            OrderStatusLog.objects.create(
                order=order, old_status='', new_status='pending',
                changed_by=request.user, memo='관리자 대리 주문',
            )
            _audit(request, AuditLog.Action.ORDER_CREATE, order, f'[대리] 주문 {order.order_no} 생성')
            messages.success(request, f'[{teacher.name}] 대리 주문 완료. 주문번호: {order.order_no}')
            return redirect('order_detail', pk=order.pk)

    return render(request, 'orders/order_create_admin.html', {
        'agencies': agencies,
        'agencies_json': agencies_json,
        'teachers_json': teachers_json,
        'series_list': series_list,
        'books_json': books_json,
        'past_city': past_city,
        'past_region': past_region,
        'now_str': now.strftime('%H:%M'),
    })


@role_required('teacher')
def order_cancel(request, pk):
    qs = get_order_queryset(request.user).filter(pk=pk, status=Order.Status.PENDING)
    if request.user.is_individual_agency:
        qs = qs.filter(agency=request.user)
    else:
        qs = qs.filter(teacher=request.user)
    order = get_object_or_404(qs)
    if request.method == 'POST':
        order.status = Order.Status.CANCELLED
        order.save(update_fields=['status'])
        OrderStatusLog.objects.create(
            order=order, old_status='pending', new_status='cancelled',
            changed_by=request.user, memo='선생님 취소',
        )
        _audit(request, AuditLog.Action.ORDER_CANCEL, order, f'주문 {order.order_no} 취소')
        messages.success(request, f'주문 {order.order_no}이 취소되었습니다.')
        return redirect('order_list')
    return render(request, 'orders/order_cancel_confirm.html', {'order': order})


@role_required('admin')
def order_delete(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method == 'POST':
        order_no = order.order_no
        order.is_deleted = True
        order.deleted_at = timezone.now()
        order.save(update_fields=['is_deleted', 'deleted_at'])
        _audit(request, AuditLog.Action.ORDER_DELETE, order, f'주문 {order_no} 삭제(soft)')
        messages.success(request, f'주문 {order_no}을 삭제했습니다. (24시간 내 복구 가능)')
        return redirect('order_list')
    return redirect('order_detail', pk=pk)


@role_required('admin')
def order_bulk_delete(request):
    if request.method != 'POST':
        return redirect('order_list')
    ids = request.POST.getlist('ids')
    if ids:
        now = timezone.now()
        qs = Order.objects.filter(pk__in=ids)
        count = qs.count()
        qs.update(is_deleted=True, deleted_at=now)
        for order in Order.objects.filter(pk__in=ids):
            _audit(request, AuditLog.Action.ORDER_DELETE, order, f'주문 {order.order_no} 일괄 삭제(soft)')
        messages.success(request, f'{count}건의 주문을 삭제했습니다. (24시간 내 복구 가능)')
    return redirect('order_list')


@role_required('admin')
def order_restore(request, pk):
    """삭제된 주문 복구"""
    order = get_object_or_404(Order, pk=pk, is_deleted=True)
    if request.method == 'POST':
        order.is_deleted = False
        order.deleted_at = None
        order.save(update_fields=['is_deleted', 'deleted_at'])
        _audit(request, AuditLog.Action.ORDER_RESTORE, order, f'주문 {order.order_no} 복구')
        messages.success(request, f'주문 {order.order_no}을 복구했습니다.')
    return redirect('order_list')
