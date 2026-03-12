import datetime
from datetime import timedelta

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db.models import Count, Max, Q, Sum

from accounts.decorators import role_required
from accounts.models import User
from django.shortcuts import get_object_or_404
from orders.models import Order, OrderItem, Return, InboxMessage, DeliveryAddress, CallRecording, AuditLog, SiteConfig, Notice
from ._helpers import get_deadlines


@role_required('admin')
def dashboard(request):
    today = timezone.localtime().date()
    yesterday = today - timedelta(days=1)
    now = timezone.localtime()

    # KPI 1: 미처리 수신함
    unread_qs = InboxMessage.objects.filter(is_processed=False).exclude(subject='[발신]')
    unprocessed_inbox = unread_qs.count()
    inbox_email = unread_qs.filter(source='email').count()
    inbox_sms = unread_qs.filter(source='sms').count()
    call_pending = CallRecording.objects.filter(
        status__in=[CallRecording.Status.PENDING, CallRecording.Status.PARSED]
    ).count()

    # KPI 2: 발송 대기
    pending_orders = Order.objects.filter(status='pending').count()
    pending_overdue = Order.objects.filter(
        status='pending',
        requested_delivery_date__isnull=False,
        requested_delivery_date__lt=today,
    ).count()
    pending_imminent = Order.objects.filter(
        status='pending',
        requested_delivery_date__isnull=False,
        requested_delivery_date__gte=today,
        requested_delivery_date__lte=today + timedelta(days=1),
    ).count()

    # KPI 3: 발송중
    shipping_orders = Order.objects.filter(status='shipping').count()
    shipping_hanjin = Order.objects.filter(status='shipping', carrier='hanjin').count()
    shipping_direct = Order.objects.filter(status='shipping', carrier='direct').count()

    # KPI 4: 오늘 접수
    today_orders = Order.objects.filter(ordered_at__date=today).count()
    yesterday_orders = Order.objects.filter(ordered_at__date=yesterday).count()
    diff = today_orders - yesterday_orders
    today_vs_yesterday = f'+{diff}' if diff >= 0 else str(diff)

    # 마감시간
    deadline_city, deadline_region, _, _ = get_deadlines(now)

    # 오늘 요약
    delivered_today = Order.objects.filter(status='delivered', ordered_at__date=today).count()
    pending_returns_count = Return.objects.filter(status='requested').count()
    today_revenue = OrderItem.objects.filter(
        order__ordered_at__date=today,
        order__status__in=['pending', 'shipping', 'delivered'],
    ).aggregate(total=Sum('amount'))['total'] or 0

    # 배송일 초과 건수 (alert)
    overdue_delivery_count = Order.objects.filter(
        status__in=['pending', 'shipping'],
        requested_delivery_date__isnull=False,
        requested_delivery_date__lt=today,
    ).count()

    # 최근 활동 로그
    recent_activity = AuditLog.objects.select_related('user').order_by('-created_at')[:5]

    return render(request, 'orders/dashboard.html', {
        'unprocessed_inbox': unprocessed_inbox,
        'inbox_email': inbox_email,
        'inbox_sms': inbox_sms,
        'call_pending': call_pending,
        'pending_orders': pending_orders,
        'pending_overdue': pending_overdue,
        'pending_imminent': pending_imminent,
        'shipping_orders': shipping_orders,
        'shipping_hanjin': shipping_hanjin,
        'shipping_direct': shipping_direct,
        'today_orders': today_orders,
        'today_vs_yesterday': today_vs_yesterday,
        'deadline_city': deadline_city,
        'deadline_region': deadline_region,
        'now': now,
        'delivered_today': delivered_today,
        'pending_returns_count': pending_returns_count,
        'today_revenue': today_revenue,
        'overdue_delivery_count': overdue_delivery_count,
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

    # 학교별 통계를 2개 쿼리로 집계 (N+1 방지)
    school_order_agg = {}
    for row in (
        Order.objects.filter(agency=user, delivery__in=deliveries)
        .values('delivery_id')
        .annotate(
            pending=Count('id', filter=Q(status='pending')),
            shipping=Count('id', filter=Q(status='shipping')),
            last_ordered=Max('ordered_at'),
        )
    ):
        school_order_agg[row['delivery_id']] = row

    teacher_counts = dict(
        teachers.values('delivery_address_id')
        .annotate(cnt=Count('id'))
        .values_list('delivery_address_id', 'cnt')
    )

    school_stats = []
    for d in deliveries:
        agg = school_order_agg.get(d.pk, {})
        school_stats.append({
            'school': d,
            'teacher_count': teacher_counts.get(d.pk, 0),
            'last_ordered': agg.get('last_ordered'),
            'pending': agg.get('pending', 0),
            'shipping': agg.get('shipping', 0),
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


@role_required('admin')
def site_settings(request):
    config = SiteConfig.get()
    if request.method == 'POST':
        city_str = request.POST.get('deadline_city', '').strip()
        region_str = request.POST.get('deadline_region', '').strip()
        try:
            config.deadline_city = datetime.time.fromisoformat(city_str)
            config.deadline_region = datetime.time.fromisoformat(region_str)
            config.save(update_fields=['deadline_city', 'deadline_region', 'updated_at'])
            messages.success(request, f'마감시간이 변경되었습니다. 시내 {city_str} / 지방 {region_str}')
        except (ValueError, TypeError):
            messages.error(request, '시간 형식이 올바르지 않습니다. (예: 11:20)')
        return redirect('site_settings')
    return render(request, 'orders/site_settings.html', {'config': config})


@role_required('admin')
def notice_list(request):
    notices = Notice.objects.all().order_by('-created_at')
    return render(request, 'orders/notice_list.html', {'notice_list': notices, 'cur': 'notice_list'})


@role_required('admin')
def notice_create(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        content = request.POST.get('content', '').strip()
        level = request.POST.get('level', 'info')
        if not title:
            messages.error(request, '제목을 입력해주세요.')
            return render(request, 'orders/notice_form.html', {
                'form_title': '공지 작성', 'cur': 'notice_list',
                'notice': {'title': title, 'content': content, 'level': level},
            })
        Notice.objects.create(title=title, content=content, level=level)
        messages.success(request, '공지가 등록되었습니다.')
        return redirect('notice_list')
    return render(request, 'orders/notice_form.html', {'form_title': '공지 작성', 'cur': 'notice_list'})


@role_required('admin')
def notice_edit(request, pk):
    notice = get_object_or_404(Notice, pk=pk)
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        content = request.POST.get('content', '').strip()
        level = request.POST.get('level', 'info')
        if not title:
            messages.error(request, '제목을 입력해주세요.')
            return render(request, 'orders/notice_form.html', {
                'form_title': '공지 수정', 'notice': notice, 'cur': 'notice_list',
            })
        notice.title = title
        notice.content = content
        notice.level = level
        notice.save(update_fields=['title', 'content', 'level'])
        messages.success(request, '공지가 수정되었습니다.')
        return redirect('notice_list')
    return render(request, 'orders/notice_form.html', {
        'form_title': '공지 수정', 'notice': notice, 'cur': 'notice_list',
    })


@role_required('admin')
def notice_delete(request, pk):
    notice = get_object_or_404(Notice, pk=pk)
    if request.method == 'POST':
        notice.delete()
        messages.success(request, '공지가 삭제되었습니다.')
    return redirect('notice_list')


@role_required('admin')
def notice_toggle(request, pk):
    notice = get_object_or_404(Notice, pk=pk)
    if request.method == 'POST':
        notice.is_active = not notice.is_active
        notice.save(update_fields=['is_active'])
        state = '활성' if notice.is_active else '비활성'
        messages.success(request, f'공지가 {state} 처리되었습니다.')
    return redirect('notice_list')


@role_required('admin')
def api_counts(request):
    """실시간 카운트 배지 (3.2) - 60초 간격 폴링용"""
    pending = Order.objects.filter(status='pending').count()
    unread = InboxMessage.objects.filter(is_processed=False).exclude(subject='[발신]').count()
    shipping = Order.objects.filter(status='shipping').count()
    return JsonResponse({
        'pending_orders': pending,
        'unread_inbox': unread,
        'pending_delivery': shipping,
    })
