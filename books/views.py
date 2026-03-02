import json
import math
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from accounts.decorators import role_required
from .models import Publisher, Book


@role_required('admin')
def book_list(request):
    publishers = Publisher.objects.prefetch_related('books').filter(is_active=True)
    return render(request, 'books/book_list.html', {'publishers': publishers})


@login_required
def book_options(request):
    """htmx: 시리즈 선택 시 해당 교재 목록 반환"""
    series = request.GET.get('series', '')
    row = request.GET.get('row', '0')
    books = Book.objects.filter(series=series, is_active=True).select_related('publisher') if series else Book.objects.none()
    return render(request, 'books/partials/book_options.html', {'books': books, 'row': row})
