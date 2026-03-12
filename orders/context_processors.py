def inbox_count(request):
    if request.user.is_authenticated and getattr(request.user, 'role', '') == 'admin':
        from orders.models import InboxMessage, Order
        return {
            'unread_inbox_count': InboxMessage.objects.filter(is_processed=False).count(),
            'pending_order_count': Order.objects.filter(status='pending').count(),
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
