from orders.models import DeliveryAddress, Order


def get_order_queryset(user):
    qs = Order.objects.select_related('agency', 'teacher', 'delivery')
    if user.role == 'admin':
        return qs.all()
    elif user.role == 'agency':
        return qs.filter(agency=user)
    elif user.role == 'teacher':
        return qs.filter(teacher=user)
    return Order.objects.none()


def get_delivery_queryset(user):
    if user.role == 'admin':
        return DeliveryAddress.objects.filter(is_active=True).select_related('agency')
    elif user.role == 'agency':
        return DeliveryAddress.objects.filter(agency=user, is_active=True)
    elif user.role == 'teacher':
        if user.delivery_address_id:
            return DeliveryAddress.objects.filter(id=user.delivery_address_id, is_active=True)
    return DeliveryAddress.objects.none()
