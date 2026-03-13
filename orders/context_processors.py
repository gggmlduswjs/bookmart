def inbox_count(request):
    if request.user.is_authenticated and getattr(request.user, 'role', '') == 'admin':
        from datetime import time as dt_time
        from orders.models import InboxMessage, Order, SiteConfig
        from django.utils import timezone as tz
        now = tz.localtime()
        config = SiteConfig.get()
        # deadline 필드가 문자열일 수 있으므로 안전하게 변환
        dc = config.deadline_city
        dr = config.deadline_region
        if isinstance(dc, str):
            parts = dc.split(':')
            dc = dt_time(int(parts[0]), int(parts[1]))
        if isinstance(dr, str):
            parts = dr.split(':')
            dr = dt_time(int(parts[0]), int(parts[1]))
        dl_city = now.replace(hour=dc.hour, minute=dc.minute, second=0, microsecond=0)
        dl_region = now.replace(hour=dr.hour, minute=dr.minute, second=0, microsecond=0)
        city_diff = (dl_city - now).total_seconds()
        region_diff = (dl_region - now).total_seconds()
        return {
            'unread_inbox_count': InboxMessage.objects.filter(is_processed=False).count(),
            'pending_order_count': Order.objects.filter(status='pending').count(),
            'tb_deadline_city_h': dc.hour,
            'tb_deadline_city_m': dc.minute,
            'tb_deadline_region_h': dr.hour,
            'tb_deadline_region_m': dr.minute,
            'tb_city_past': city_diff <= 0,
            'tb_region_past': region_diff <= 0,
        }
    return {}


def active_notices(request):
    if request.user.is_authenticated:
        try:
            from orders.models import Notice
            return {'notices': Notice.objects.filter(is_active=True).order_by('-created_at')[:5]}
        except Exception:
            return {}
    return {}
