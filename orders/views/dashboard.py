from django.shortcuts import render
from django.utils import timezone
from django.db.models import Sum

from accounts.decorators import role_required
from accounts.models import User
from orders.models import Order, OrderItem, Return, InboxMessage, DeliveryAddress, CallRecording, AuditLog


@role_required('admin')
def dashboard(request):
    today = timezone.localtime().date()
    now = timezone.localtime()

    unprocessed_inbox = InboxMessage.objects.filter(is_processed=False).count()
    today_orders = Order.objects.filter(ordered_at__date=today).count()
    pending_orders = Order.objects.filter(status='pending').count()
    shipping_orders = Order.objects.filter(status='shipping').count()

    recent_inbox = InboxMessage.objects.filter(is_processed=False)[:5]
    pending_order_list = Order.objects.filter(status='pending').order_by('-ordered_at')[:5]
    pending_returns = Return.objects.filter(status='requested').order_by('-requested_at')[:3]

    deadline_city = now.replace(hour=11, minute=20, second=0, microsecond=0)
    deadline_region = now.replace(hour=13, minute=50, second=0, microsecond=0)

    recent_delivered = Order.objects.filter(status='delivered').order_by('-ordered_at')[:5]

    # 통화 녹음 대기 건수
    call_pending = CallRecording.objects.filter(
        status__in=[CallRecording.Status.PENDING, CallRecording.Status.PARSED]
    ).count()

    # 최근 활동 로그
    recent_activity = AuditLog.objects.select_related('user').order_by('-created_at')[:8]

    return render(request, 'orders/dashboard.html', {
        'unprocessed_inbox': unprocessed_inbox,
        'today_orders': today_orders,
        'pending_orders': pending_orders,
        'shipping_orders': shipping_orders,
        'recent_inbox': recent_inbox,
        'pending_order_list': pending_order_list,
        'pending_returns': pending_returns,
        'deadline_city': deadline_city,
        'deadline_region': deadline_region,
        'now': now,
        'recent_delivered': recent_delivered,
        'today_str': today.strftime('%Y-%m-%d'),
        'call_pending': call_pending,
        'recent_activity': recent_activity,
    })


@role_required('agency')
def agency_dashboard(request):
    user = request.user
    today = timezone.localtime().date()
    now = timezone.localtime()

    deliveries = DeliveryAddress.objects.filter(agency=user, is_active=True)
    teachers = User.objects.filter(role='teacher', agency=user, is_active=True)

    my_orders = Order.objects.filter(agency=user)
    today_orders = my_orders.filter(ordered_at__date=today).count()
    pending_orders = my_orders.filter(status='pending').count()
    shipping_orders = my_orders.filter(status='shipping').count()
    total_schools = deliveries.count()

    month_start = today.replace(day=1)
    month_items = OrderItem.objects.filter(
        order__agency=user,
        order__status__in=['pending', 'shipping', 'delivered'],
        order__ordered_at__date__gte=month_start,
    )
    month_amount = month_items.aggregate(total=Sum('amount'))['total'] or 0

    recent_orders = my_orders.select_related(
        'teacher', 'delivery'
    ).order_by('-ordered_at')[:10]

    school_stats = []
    for d in deliveries:
        last_order = my_orders.filter(delivery=d).order_by('-ordered_at').first()
        school_teachers = teachers.filter(delivery_address=d).count()
        school_stats.append({
            'school': d,
            'teacher_count': school_teachers,
            'last_order': last_order,
            'pending': my_orders.filter(delivery=d, status='pending').count(),
            'shipping': my_orders.filter(delivery=d, status='shipping').count(),
        })

    pending_returns = Return.objects.filter(
        agency=user, status='requested'
    ).select_related('teacher', 'delivery').order_by('-requested_at')[:5]

    return render(request, 'orders/agency_dashboard.html', {
        'today_orders': today_orders,
        'pending_orders': pending_orders,
        'shipping_orders': shipping_orders,
        'total_schools': total_schools,
        'month_amount': month_amount,
        'recent_orders': recent_orders,
        'school_stats': school_stats,
        'pending_returns': pending_returns,
        'now': now,
    })
