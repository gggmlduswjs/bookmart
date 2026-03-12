def inbox_count(request):
    if request.user.is_authenticated and getattr(request.user, 'role', '') == 'admin':
        from orders.models import InboxMessage, Order, SiteConfig
        from django.utils import timezone as tz
        now = tz.localtime()
        config = SiteConfig.get()
        dl_city = now.replace(hour=config.deadline_city.hour, minute=config.deadline_city.minute, second=0, microsecond=0)
        dl_region = now.replace(hour=config.deadline_region.hour, minute=config.deadline_region.minute, second=0, microsecond=0)
        city_diff = (dl_city - now).total_seconds()
        region_diff = (dl_region - now).total_seconds()
        return {
            'unread_inbox_count': InboxMessage.objects.filter(is_processed=False).count(),
            'pending_order_count': Order.objects.filter(status='pending').count(),
            'tb_deadline_city_h': config.deadline_city.hour,
            'tb_deadline_city_m': config.deadline_city.minute,
            'tb_deadline_region_h': config.deadline_region.hour,
            'tb_deadline_region_m': config.deadline_region.minute,
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
