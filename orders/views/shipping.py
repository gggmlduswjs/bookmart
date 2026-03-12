import json

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from orders.models import Order, OrderStatusLog, AuditLog
from orders.sms import send_ship_notification, send_delivery_notification
from ._helpers import _audit


@role_required('admin')
def order_ship(request, pk):
    order = get_object_or_404(Order, pk=pk, status=Order.Status.PENDING)
    if request.method == 'POST':
        carrier = request.POST.get('carrier', 'hanjin')
        order.carrier = carrier
        order.tracking_no = request.POST.get('tracking_no', '').strip() if carrier == 'hanjin' else ''
        order.status = Order.Status.SHIPPING
        order.save(update_fields=['status', 'carrier', 'tracking_no'])
        OrderStatusLog.objects.create(
            order=order, old_status='pending', new_status='shipping',
            changed_by=request.user, memo=f'발송 ({order.get_carrier_display()})',
        )
        _audit(request, AuditLog.Action.ORDER_SHIP, order, f'주문 {order.order_no} 발송 처리')

        sms_ok = send_ship_notification(order)
        if sms_ok:
            messages.success(request, f'주문 {order.order_no} → 발송중 처리 + 선생님께 문자 발송 완료.')
        else:
            messages.success(request, f'주문 {order.order_no} → 발송중 처리 완료.')
            if not (order.teacher.phone or order.teacher.mobile):
                messages.warning(request, '선생님 전화번호가 등록되어 있지 않아 문자를 보내지 못했습니다.')
    return redirect('order_detail', pk=pk)


@role_required('admin')
def order_deliver(request, pk):
    order = get_object_or_404(Order, pk=pk, status=Order.Status.SHIPPING)
    if request.method == 'POST':
        order.status = Order.Status.DELIVERED
        order.save(update_fields=['status'])
        OrderStatusLog.objects.create(
            order=order, old_status='shipping', new_status='delivered',
            changed_by=request.user,
        )
        _audit(request, AuditLog.Action.ORDER_DELIVER, order, f'주문 {order.order_no} 배송완료')
        send_delivery_notification(order)
        messages.success(request, f'주문 {order.order_no} → 발송완료 처리되었습니다.')
    return redirect('order_detail', pk=pk)


def _group_by_region(orders):
    """Group orders by delivery region: 서울, 경기, 지방, 미분류"""
    region_labels = {'seoul': '서울', 'gyeonggi': '경기', 'regional': '지방'}
    groups = {'seoul': [], 'gyeonggi': [], 'regional': [], '': []}
    for order in orders:
        r = order.delivery.region if order.delivery else ''
        groups.setdefault(r, []).append(order)
    result = []
    for key in ['seoul', 'gyeonggi', 'regional', '']:
        if groups.get(key):
            result.append({
                'label': region_labels.get(key, '미분류'),
                'region': key,
                'orders': groups[key],
                'count': len(groups[key]),
            })
    return result


@role_required('admin')
def delivery_manage(request):
    """배송관리 페이지: 접수/발송중 주문 일괄 처리"""
    tab = request.GET.get('tab', 'pending')

    if request.method == 'POST':
        action = request.POST.get('action', '')
        ids = request.POST.getlist('ids')
        if ids:
            if action == 'ship':
                orders = Order.objects.filter(pk__in=ids, status=Order.Status.PENDING)
                count = 0
                for order in orders:
                    carrier = request.POST.get(f'carrier_{order.pk}', 'hanjin')
                    tracking = request.POST.get(f'tracking_{order.pk}', '').strip() if carrier == 'hanjin' else ''
                    order.carrier = carrier
                    order.tracking_no = tracking
                    order.status = Order.Status.SHIPPING
                    order.save(update_fields=['status', 'carrier', 'tracking_no'])
                    OrderStatusLog.objects.create(
                        order=order, old_status='pending', new_status='shipping',
                        changed_by=request.user, memo=f'일괄 발송 ({order.get_carrier_display()})',
                    )
                    send_ship_notification(order)
                    count += 1
                messages.success(request, f'{count}건 발송 처리 완료.')
                return redirect(f'{request.path}?tab=pending')
            elif action == 'deliver':
                orders = Order.objects.filter(pk__in=ids, status=Order.Status.SHIPPING)
                count = 0
                for order in orders:
                    order.status = Order.Status.DELIVERED
                    order.save(update_fields=['status'])
                    OrderStatusLog.objects.create(
                        order=order, old_status='shipping', new_status='delivered',
                        changed_by=request.user, memo='일괄 배송완료',
                    )
                    send_delivery_notification(order)
                    count += 1
                messages.success(request, f'{count}건 배송완료 처리.')
                return redirect(f'{request.path}?tab=shipping')

    pending_orders = (
        Order.objects.filter(status=Order.Status.PENDING)
        .select_related('agency', 'teacher', 'delivery')
        .prefetch_related('items')
        .order_by('ordered_at')
    )
    shipping_orders = (
        Order.objects.filter(status=Order.Status.SHIPPING)
        .select_related('agency', 'teacher', 'delivery')
        .prefetch_related('items')
        .order_by('ordered_at')
    )
    delivered_orders = (
        Order.objects.filter(status=Order.Status.DELIVERED)
        .select_related('agency', 'teacher', 'delivery')
        .prefetch_related('items')
        .order_by('-ordered_at')[:100]
    )
    for order in pending_orders:
        order.total_amt = sum(item.amount for item in order.items.all())
        order.item_count = order.items.count()
    for order in shipping_orders:
        order.total_amt = sum(item.amount for item in order.items.all())
        order.item_count = order.items.count()
    for order in delivered_orders:
        order.total_amt = sum(item.amount for item in order.items.all())
        order.item_count = order.items.count()

    return render(request, 'orders/delivery_manage.html', {
        'pending_orders': pending_orders,
        'shipping_orders': shipping_orders,
        'delivered_orders': delivered_orders,
        'pending_groups': _group_by_region(pending_orders),
        'shipping_groups': _group_by_region(shipping_orders),
        'pending_count': pending_orders.count(),
        'shipping_count': shipping_orders.count(),
        'delivered_count': delivered_orders.count() if hasattr(delivered_orders, 'count') else len(delivered_orders),
        'tab': tab,
    })


@role_required('admin')
@require_POST
def order_quick_ship(request):
    """AJAX: 주문목록에서 인라인 발송처리"""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': '잘못된 요청'}, status=400)

    pk = data.get('order_id')
    carrier = data.get('carrier', 'hanjin')
    tracking_no = data.get('tracking_no', '').strip()

    order = get_object_or_404(Order, pk=pk, status=Order.Status.PENDING)
    order.carrier = carrier
    order.tracking_no = tracking_no if carrier == 'hanjin' else ''
    order.status = Order.Status.SHIPPING
    order.save(update_fields=['status', 'carrier', 'tracking_no'])

    OrderStatusLog.objects.create(
        order=order, old_status='pending', new_status='shipping',
        changed_by=request.user, memo=f'발송 ({order.get_carrier_display()})',
    )
    _audit(request, AuditLog.Action.ORDER_SHIP, order, f'[인라인] 주문 {order.order_no} 발송')
    sms_ok = send_ship_notification(order)

    return JsonResponse({
        'ok': True,
        'order_no': order.order_no,
        'sms_sent': sms_ok,
    })


@role_required('admin')
@require_POST
def order_quick_deliver(request):
    """AJAX: 주문목록에서 인라인 배송완료"""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': '잘못된 요청'}, status=400)

    pk = data.get('order_id')
    order = get_object_or_404(Order, pk=pk, status=Order.Status.SHIPPING)
    order.status = Order.Status.DELIVERED
    order.save(update_fields=['status'])

    OrderStatusLog.objects.create(
        order=order, old_status='shipping', new_status='delivered',
        changed_by=request.user, memo='인라인 배송완료',
    )
    _audit(request, AuditLog.Action.ORDER_DELIVER, order, f'[인라인] 주문 {order.order_no} 배송완료')
    send_delivery_notification(order)

    return JsonResponse({'ok': True, 'order_no': order.order_no})
