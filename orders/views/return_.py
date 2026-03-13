import json
import math

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from books.models import Book
from orders.models import Order, Return, ReturnItem, AuditLog
from orders.services import get_return_queryset, get_delivery_queryset
from ._helpers import _audit, get_books_json


@login_required
def return_list(request):
    qs = get_return_queryset(request.user)

    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    delivery_id = request.GET.get('delivery', '')

    if status:
        qs = qs.filter(status=status)
    if date_from:
        qs = qs.filter(requested_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(requested_at__date__lte=date_to)
    if delivery_id:
        qs = qs.filter(delivery_id=delivery_id)

    deliveries = get_delivery_queryset(request.user)

    page_number = request.GET.get('page', 1)
    paginator = Paginator(qs.order_by('-requested_at'), 50)
    page_obj = paginator.get_page(page_number)

    return render(request, 'orders/return_list.html', {
        'returns': page_obj, 'page_obj': page_obj,
        'deliveries': deliveries,
        'status_choices': Return.Status.choices,
        'filters': {
            'status': status, 'date_from': date_from,
            'date_to': date_to, 'delivery': delivery_id,
        },
    })


@role_required('teacher')
def return_create(request):
    user = request.user
    delivery = user.delivery_address
    if not delivery:
        messages.error(request, '담당 학교가 지정되지 않았습니다.')
        return redirect('home')

    books = Book.objects.filter(is_active=True, is_returnable=True).select_related('publisher')
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
            messages.error(request, '반품할 교재를 1권 이상 선택하세요.')
        else:
            ret = Return.objects.create(
                return_no=Return.generate_return_no(),
                agency=user.agency,
                teacher=user,
                delivery=delivery,
                memo=request.POST.get('memo', ''),
            )
            for book_id, qty in items:
                try:
                    book = Book.objects.get(id=book_id, is_active=True, is_returnable=True)
                    ReturnItem(ret=ret, book=book, requested_qty=qty).save()
                except Book.DoesNotExist:
                    pass
            _audit(request, AuditLog.Action.RETURN_CREATE, ret, f'반품 {ret.return_no} 신청')
            messages.success(request, f'반품 신청 완료. 반품번호: {ret.return_no}')
            return redirect('return_detail', pk=ret.pk)

    return render(request, 'orders/return_create.html', {
        'delivery': delivery,
        'series_list': series_list,
        'books_json': books_json,
    })


@role_required('admin')
def return_create_from_order(request, pk):
    """주문 상세에서 바로 반품 생성"""
    order = get_object_or_404(Order, pk=pk)
    items = order.items.select_related('book', 'book__publisher')

    books = Book.objects.filter(is_active=True, is_returnable=True).select_related('publisher')
    series_list = sorted(set(b.series for b in books if b.series))
    books_json = get_books_json(books)

    prefill_items = json.dumps([{
        'book_id': str(item.book_id) if item.book_id else '',
        'series': item.book.series or '기타' if item.book else '',
        'name': item.display_name,
        'qty': item.quantity,
        'unit_price': item.unit_price,
    } for item in items if item.book and item.book.is_returnable], ensure_ascii=False)

    if request.method == 'POST':
        ret_items = []
        i = 0
        while f'book_{i}' in request.POST:
            book_id = request.POST.get(f'book_{i}', '').strip()
            qty_str = request.POST.get(f'qty_{i}', '').strip()
            if book_id and qty_str:
                try:
                    qty = int(qty_str)
                    if qty > 0:
                        ret_items.append((int(book_id), qty))
                except (ValueError, TypeError):
                    pass
            i += 1

        if not ret_items:
            messages.error(request, '반품할 교재를 1권 이상 선택하세요.')
        else:
            reason = request.POST.get('reason', 'etc')
            ret = Return.objects.create(
                return_no=Return.generate_return_no(),
                agency=order.agency,
                teacher=order.teacher,
                delivery=order.delivery,
                memo=request.POST.get('memo', ''),
                reason=reason,
                order=order,
            )
            for book_id, qty in ret_items:
                try:
                    book = Book.objects.get(id=book_id, is_active=True, is_returnable=True)
                    ReturnItem(ret=ret, book=book, requested_qty=qty).save()
                except Book.DoesNotExist:
                    pass
            _audit(request, AuditLog.Action.RETURN_CREATE, ret, f'주문 {order.order_no}에서 반품 {ret.return_no} 생성')
            messages.success(request, f'반품 신청 완료. 반품번호: {ret.return_no}')
            return redirect('return_detail', pk=ret.pk)

    return render(request, 'orders/return_create_from_order.html', {
        'order': order,
        'items': items,
        'series_list': series_list,
        'books_json': books_json,
        'prefill_items': prefill_items,
        'reason_choices': Return.Reason.choices,
    })


@login_required
def return_detail(request, pk):
    ret = get_object_or_404(get_return_queryset(request.user), pk=pk)
    items = ret.items.select_related('book', 'book__publisher')
    # 상태 변경 이력 (AuditLog 기반)
    return_logs = AuditLog.objects.filter(
        action__in=[
            AuditLog.Action.RETURN_CREATE,
            AuditLog.Action.RETURN_CONFIRM,
            AuditLog.Action.RETURN_REJECT,
        ],
        detail__contains=ret.return_no,
    ).select_related('user').order_by('created_at')
    return render(request, 'orders/return_detail.html', {
        'ret': ret,
        'items': items,
        'return_logs': return_logs,
        'can_confirm': request.user.role == 'admin' and ret.status == Return.Status.REQUESTED,
        'can_reject': request.user.role == 'admin' and ret.status == Return.Status.REQUESTED,
    })


@role_required('admin')
def return_confirm(request, pk):
    ret = get_object_or_404(Return, pk=pk, status=Return.Status.REQUESTED)
    items = ret.items.select_related('book')

    if request.method == 'POST':
        for item in items:
            confirmed_qty_str = request.POST.get(f'confirmed_qty_{item.pk}', '0')
            adjusted_str = request.POST.get(f'adjusted_{item.pk}', '0')
            try:
                item.confirmed_qty = max(0, int(confirmed_qty_str))
                item.adjusted_amount = int(adjusted_str)
            except (ValueError, TypeError):
                item.confirmed_qty = 0
                item.adjusted_amount = 0
            item.save()

        ret.status = Return.Status.CONFIRMED
        ret.confirmed_at = timezone.now()
        ret.save(update_fields=['status', 'confirmed_at'])
        _audit(request, AuditLog.Action.RETURN_CONFIRM, ret, f'반품 {ret.return_no} 확정')
        messages.success(request, f'반품 {ret.return_no} 확정 처리되었습니다.')
        return redirect('return_detail', pk=pk)

    return render(request, 'orders/return_confirm.html', {'ret': ret, 'items': items})


@require_POST
@role_required('admin')
def return_create_inline(request, pk):
    """주문 상세에서 인라인 반품 생성 (AJAX)"""
    order = get_object_or_404(Order, pk=pk)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': '잘못된 요청입니다.'}, status=400)

    items_data = data.get('items', [])
    reason = data.get('reason', 'etc')
    memo = data.get('memo', '')

    # 유효한 반품 아이템 필터링
    ret_items = []
    for item in items_data:
        try:
            book_id = int(item.get('book_id', 0))
            qty = int(item.get('qty', 0))
            if book_id and qty > 0:
                ret_items.append((book_id, qty))
        except (ValueError, TypeError):
            continue

    if not ret_items:
        return JsonResponse({'ok': False, 'error': '반품할 교재를 1권 이상 선택하세요.'}, status=400)

    ret = Return.objects.create(
        return_no=Return.generate_return_no(),
        agency=order.agency,
        teacher=order.teacher,
        delivery=order.delivery,
        memo=memo,
        reason=reason,
        order=order,
    )

    created_count = 0
    for book_id, qty in ret_items:
        try:
            book = Book.objects.get(id=book_id, is_active=True)
            ReturnItem(ret=ret, book=book, requested_qty=qty).save()
            created_count += 1
        except Book.DoesNotExist:
            continue

    if created_count == 0:
        ret.delete()
        return JsonResponse({'ok': False, 'error': '유효한 교재가 없습니다.'}, status=400)

    _audit(request, AuditLog.Action.RETURN_CREATE, ret,
           f'주문 {order.order_no}에서 인라인 반품 {ret.return_no} 생성')

    return JsonResponse({
        'ok': True,
        'return_no': ret.return_no,
        'return_pk': ret.pk,
        'message': f'반품 {ret.return_no} 신청 완료 ({created_count}건)',
    })


@role_required('admin')
def return_reject(request, pk):
    ret = get_object_or_404(Return, pk=pk, status=Return.Status.REQUESTED)
    if request.method == 'POST':
        ret.status = Return.Status.REJECTED
        ret.memo = request.POST.get('memo', ret.memo)
        ret.save(update_fields=['status', 'memo'])
        _audit(request, AuditLog.Action.RETURN_REJECT, ret, f'반품 {ret.return_no} 거절')
        messages.success(request, f'반품 {ret.return_no} 거절 처리되었습니다.')
        return redirect('return_detail', pk=pk)
    return render(request, 'orders/return_reject.html', {'ret': ret})
