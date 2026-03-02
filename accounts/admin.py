from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, AgencyInfo


class AgencyInfoInline(admin.StackedInline):
    model = AgencyInfo
    can_delete = False
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('login_id', 'name', 'role', 'phone', 'is_active', 'created_at')
    list_filter = ('role', 'is_active')
    search_fields = ('login_id', 'name', 'phone')
    ordering = ('role', 'name')

    fieldsets = (
        (None, {'fields': ('login_id', 'password')}),
        ('정보', {'fields': ('role', 'name', 'phone', 'agency', 'delivery_address')}),
        ('상태', {'fields': ('is_active', 'must_change_password', 'is_staff', 'is_superuser')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('login_id', 'password1', 'password2', 'role', 'name', 'phone'),
        }),
    )

    inlines = [AgencyInfoInline]
