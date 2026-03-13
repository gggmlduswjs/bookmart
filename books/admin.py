from django.contrib import admin
from .models import Publisher, Book


@admin.register(Publisher)
class PublisherAdmin(admin.ModelAdmin):
    list_display = ('name', 'supply_rate', 'is_active')
    list_editable = ('supply_rate', 'is_active')


class BookInline(admin.TabularInline):
    model = Book
    extra = 0
    fields = ('series', 'month', 'grade', 'name', 'list_price', 'is_returnable', 'is_active', 'sort_order')


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('publisher', 'series', 'month', 'grade', 'name', 'list_price', 'is_returnable', 'is_active')
    list_filter = ('publisher', 'series', 'month', 'grade', 'is_active', 'is_returnable')
    search_fields = ('name', 'series')
    list_editable = ('is_active',)
    filter_horizontal = ('agencies',)
    ordering = ('publisher', 'series', 'month', 'sort_order', 'name')
