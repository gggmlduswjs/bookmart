import json
import math
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from accounts.decorators import role_required
from books.models import Book
from .models import Order, OrderItem
from .services import get_order_queryset, get_delivery_queryset


@login_required
def order_list(request):
    qs = get_order_queryset(request.user)

    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    delivery_id = request.GET.get('delivery', '')

    if status:
        qs = qs.filter(status=status)
    if date_from:
        qs = qs.filter(ordered_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(ordered_at__date__lte=date_to)
    if delivery_id:
        qs = qs.filter(delivery_id=delivery_id)

    deliveries = get_delivery_queryset(request.user)

    return render(request, 'orders/order_list.html', {
        'orders': qs.order_by('-ordered_at')[:200],
        'deliveries': deliveries,
        'status_choices': Order.Status.choices,
        'filters': {
            'status': status, 'date_from': date_from,
            'date_to': date_to, 'delivery': delivery_id,
        },
    })


@role_required('teacher')
def order_create(request):
    user = request.user
    delivery = user.delivery_address
    if not delivery:
        messages.error(request, '담당 학교가 지정되지 않았습니다. 업체에 문의하세요.')
        return redirect('home')

    books = Book.objects.filter(is_active=True).select_related('publisher')
    series_list = sorted(set(b.series for b in books if b.series))
    books_json = json.dumps([{
        'id': b.id,
        'series': b.series or '기타',
        'name': b.name,
        'publisher': b.publisher.name,
        'unit_price': math.floor(b.list_price * float(b.publisher.supply_rate) / 100),
    } for b in books], ensure_ascii=False)

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
            )
            for book_id, qty in items:
                try:
                    book = Book.objects.get(id=book_id, is_active=True)
                    OrderItem(order=order, book=book, quantity=qty).save()
                except Book.DoesNotExist:
                    pass
            messages.success(request, f'주문 완료. 주문번호: {order.order_no}')
            return redirect('order_detail', pk=order.pk)

    return render(request, 'orders/order_create.html', {
        'delivery': delivery,
        'series_list': series_list,
        'books_json': books_json,
    })


@login_required
def order_detail(request, pk):
    order = get_object_or_404(get_order_queryset(request.user), pk=pk)
    items = order.items.select_related('book', 'book__publisher')
    return render(request, 'orders/order_detail.html', {
        'order': order,
        'items': items,
        'can_cancel': (
            order.status == Order.Status.PENDING
            and request.user.role == 'teacher'
            and order.teacher == request.user
        ),
    })


@role_required('teacher')
def order_cancel(request, pk):
    order = get_object_or_404(
        get_order_queryset(request.user),
        pk=pk, teacher=request.user, status=Order.Status.PENDING
    )
    if request.method == 'POST':
        order.status = Order.Status.CANCELLED
        order.save(update_fields=['status'])
        messages.success(request, f'주문 {order.order_no}이 취소되었습니다.')
        return redirect('order_list')
    return render(request, 'orders/order_cancel_confirm.html', {'order': order})
