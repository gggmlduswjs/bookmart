from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from orders.models import Order, OrderStatusLog, AuditLog
from orders.sms import send_delivery_notification
from ._helpers import _audit


@role_required('admin')
def mobile_delivery_list(request):
    """모바일 배송 목록 — 발송중 주문을 지역별로 그룹핑"""
    orders = (
        Order.objects.filter(status=Order.Status.SHIPPING)
        .select_related('agency', 'teacher', 'delivery')
        .prefetch_related('items')
        .order_by('delivery__region', 'delivery__name')
    )

    # 지역별 그룹핑
    groups = {}
    region_labels = {'seoul': '서울', 'gyeonggi': '경기', 'regional': '지방', '': '미분류'}
    for order in orders:
        order.total_amt = sum(item.amount for item in order.items.all())
        order.item_count = order.items.count()
        region = order.delivery.region or ''
        if region not in groups:
            groups[region] = {
                'label': region_labels.get(region, region),
                'orders': [],
            }
        groups[region]['orders'].append(order)

    # 정렬: 서울 > 경기 > 지방 > 미분류
    order_map = {'seoul': 0, 'gyeonggi': 1, 'regional': 2, '': 3}
    sorted_groups = sorted(groups.items(), key=lambda x: order_map.get(x[0], 99))

    return render(request, 'mobile/delivery.html', {
        'groups': sorted_groups,
        'total_count': orders.count(),
    })


@role_required('admin')
@require_POST
def mobile_delivery_done(request):
    """모바일에서 선택 주문 배송완료 처리 + SMS"""
    ids = request.POST.getlist('ids')
    if not ids:
        return redirect('mobile_delivery_list')

    orders = Order.objects.filter(pk__in=ids, status=Order.Status.SHIPPING)
    count = 0
    for order in orders:
        order.status = Order.Status.DELIVERED
        order.save(update_fields=['status'])
        OrderStatusLog.objects.create(
            order=order, old_status='shipping', new_status='delivered',
            changed_by=request.user, memo='모바일 배송완료',
        )
        _audit(request, AuditLog.Action.ORDER_DELIVER, order, f'[모바일] 주문 {order.order_no} 배송완료')
        send_delivery_notification(order)
        count += 1

    return render(request, 'mobile/delivery_done.html', {
        'count': count,
    })
