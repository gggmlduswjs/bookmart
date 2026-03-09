def inbox_count(request):
    if request.user.is_authenticated and getattr(request.user, 'role', '') == 'admin':
        from orders.models import InboxMessage
        return {'unread_inbox_count': InboxMessage.objects.filter(is_processed=False).count()}
    return {}
