import datetime
from datetime import timedelta

from django.contrib import messages
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
    now = timezone.localtime()

    unprocessed_inbox = InboxMessage.objects.filter(is_processed=False).exclude(subject='[발신]').count()
    today_orders = Order.objects.filter(ordered_at__date=today).count()
    pending_orders = Order.objects.filter(status='pending').count()
    shipping_orders = Order.objects.filter(status='shipping').count()

    recent_inbox = InboxMessage.objects.filter(is_processed=False).exclude(subject='[발신]')[:5]
    pending_order_list = Order.objects.filter(status='pending').order_by('-ordered_at')[:5]
    pending_returns = Return.objects.filter(status='requested').order_by('-requested_at')[:3]

    deadline_city, deadline_region, _, _ = get_deadlines(now)

    recent_delivered = Order.objects.filter(status='delivered').order_by('-ordered_at')[:5]

    # 통화 녹음 대기 건수
    call_pending = CallRecording.objects.filter(
        status__in=[CallRecording.Status.PENDING, CallRecording.Status.PARSED]
    ).count()

    # 최근 활동 로그
    recent_activity = AuditLog.objects.select_related('user').order_by('-created_at')[:8]

    # 요청 배송일 임박 주문
    upcoming_delivery = (
        Order.objects.filter(
            status__in=['pending', 'shipping'],
            requested_delivery_date__isnull=False,
            requested_delivery_date__lte=today + timedelta(days=3),
        )
        .select_related('teacher', 'delivery', 'agency')
        .order_by('requested_delivery_date')[:10]
    )
    overdue_delivery = [o for o in upcoming_delivery if o.requested_delivery_date < today]

    # 업체 분류별 통계
    category_stats = (
        Order.objects.filter(ordered_at__date=today)
        .values('agency__agency_category')
        .annotate(cnt=Count('id'))
        .order_by('-cnt')
    )

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
        'upcoming_delivery': upcoming_delivery,
        'overdue_delivery_count': len(overdue_delivery),
        'category_stats': category_stats,
        'today': today,
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
