from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404

from accounts.decorators import role_required
from orders.models import Order


def _number_to_korean(n):
    """숫자를 한글 금액 표기로 변환 (예: 462000 → 사십육만이천)"""
    if n == 0:
        return '영'
    units = ['', '만', '억', '조']
    digits = ['', '일', '이', '삼', '사', '오', '육', '칠', '팔', '구']
    sub_units = ['', '십', '백', '천']
    result = ''
    group_idx = 0
    while n > 0:
        group = n % 10000
        n //= 10000
        if group > 0:
            group_str = ''
            for i in range(4):
                d = group % 10
                group //= 10
                if d > 0:
                    prefix = digits[d] if not (d == 1 and i > 0) else ''
                    group_str = prefix + sub_units[i] + group_str
            result = group_str + units[group_idx] + result
        group_idx += 1
    return result


@role_required('admin', 'agency')
def order_quote(request, pk):
    """견적서 인쇄"""
    order = get_object_or_404(Order, pk=pk)
    items = order.items.select_related('book', 'book__publisher')
    for item in items:
        item.list_price_total = item.list_price * item.quantity
    total_amount = sum(item.list_price_total for item in items)
    total_qty = sum(item.quantity for item in items)
    empty_rows = range(max(0, 16 - items.count()))
    amount_korean = _number_to_korean(total_amount)
    return render(request, 'orders/order_quote.html', {
        'order': order,
        'items': items,
        'total_amount': total_amount,
        'total_qty': total_qty,
        'empty_rows': empty_rows,
        'amount_korean': amount_korean,
    })


@role_required('admin', 'agency')
def order_quote_bulk(request):
    """견적서 일괄 인쇄"""
    ids_str = request.GET.get('ids', '')
    try:
        ids = [int(x) for x in ids_str.split(',') if x.strip()]
    except ValueError:
        ids = []
    if not ids:
        return HttpResponse('인쇄할 주문이 없습니다.', status=400)

    orders_data = []
    qs = Order.objects.filter(pk__in=ids).select_related(
        'teacher', 'delivery', 'agency'
    ).order_by('ordered_at')
    if request.user.role == 'agency':
        qs = qs.filter(agency=request.user)

    for order in qs:
        items = order.items.select_related('book', 'book__publisher')
        for item in items:
            item.list_price_total = item.list_price * item.quantity
        total_amount = sum(item.list_price_total for item in items)
        total_qty = sum(item.quantity for item in items)
        empty_rows = range(max(0, 16 - items.count()))
        amount_korean = _number_to_korean(total_amount)
        orders_data.append({
            'order': order,
            'items': items,
            'total_amount': total_amount,
            'total_qty': total_qty,
            'empty_rows': empty_rows,
            'amount_korean': amount_korean,
        })

    return render(request, 'orders/order_quote_bulk.html', {
        'orders_data': orders_data,
    })


@role_required('admin', 'agency')
def order_invoice(request, pk):
    order = get_object_or_404(Order, pk=pk)
    items = order.items.select_related('book', 'book__publisher')
    total_amount = sum(item.amount for item in items)
    total_qty = sum(item.quantity for item in items)
    empty_rows = range(max(0, 13 - items.count()))
    return render(request, 'orders/order_invoice.html', {
        'order': order,
        'items': items,
        'total_amount': total_amount,
        'total_qty': total_qty,
        'empty_rows': empty_rows,
    })


@role_required('admin', 'agency')
def order_invoice_bulk(request):
    ids_str = request.GET.get('ids', '')
    try:
        ids = [int(x) for x in ids_str.split(',') if x.strip()]
    except ValueError:
        ids = []
    if not ids:
        return HttpResponse('인쇄할 주문이 없습니다.', status=400)

    orders_data = []
    qs = Order.objects.filter(pk__in=ids).select_related(
        'teacher', 'delivery', 'agency'
    ).order_by('ordered_at')
    if request.user.role == 'agency':
        qs = qs.filter(agency=request.user)

    for order in qs:
        items = order.items.select_related('book', 'book__publisher')
        total_amount = sum(item.amount for item in items)
        total_qty = sum(item.quantity for item in items)
        empty_rows = range(max(0, 13 - items.count()))
        orders_data.append({
            'order': order,
            'items': items,
            'total_amount': total_amount,
            'total_qty': total_qty,
            'empty_rows': empty_rows,
        })

    return render(request, 'orders/order_invoice_bulk.html', {
        'orders_data': orders_data,
    })
