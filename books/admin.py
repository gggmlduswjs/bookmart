from django.contrib import admin
from .models import Publisher, Book


@admin.register(Publisher)
class PublisherAdmin(admin.ModelAdmin):
    list_display = ('name', 'supply_rate', 'is_active')
    list_editable = ('supply_rate', 'is_active')


class BookInline(admin.TabularInline):
    model = Book
    extra = 0
    fields = ('series', 'name', 'list_price', 'is_returnable', 'is_active', 'sort_order')


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('publisher', 'series', 'name', 'list_price', 'is_returnable', 'is_active')
    list_filter = ('publisher', 'is_active', 'is_returnable')
    search_fields = ('name', 'series')
    list_editable = ('is_active',)
    ordering = ('publisher', 'series', 'sort_order', 'name')
