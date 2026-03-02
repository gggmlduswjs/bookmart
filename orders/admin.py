from django.contrib import admin
from .models import DeliveryAddress, Order, OrderItem, Return, ReturnItem, Payment


@admin.register(DeliveryAddress)
class DeliveryAddressAdmin(admin.ModelAdmin):
    list_display = ('name', 'agency', 'phone', 'is_active')
    list_filter = ('agency', 'is_active')
    search_fields = ('name', 'agency__name')


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('list_price', 'supply_rate', 'unit_price', 'amount')
    fields = ('book', 'quantity', 'list_price', 'supply_rate', 'unit_price', 'amount')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_no', 'agency', 'delivery', 'status', 'ordered_at')
    list_filter = ('status', 'agency', 'ordered_at')
    search_fields = ('order_no', 'delivery__name', 'agency__name')
    readonly_fields = ('order_no', 'ordered_at')
    inlines = [OrderItemInline]


class ReturnItemInline(admin.TabularInline):
    model = ReturnItem
    extra = 0
    readonly_fields = ('list_price', 'supply_rate', 'unit_price', 'requested_amount')


@admin.register(Return)
class ReturnAdmin(admin.ModelAdmin):
    list_display = ('return_no', 'agency', 'delivery', 'status', 'requested_at')
    list_filter = ('status', 'agency')
    search_fields = ('return_no', 'delivery__name')
    inlines = [ReturnItemInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('agency', 'amount', 'paid_at', 'memo')
    list_filter = ('agency', 'paid_at')
