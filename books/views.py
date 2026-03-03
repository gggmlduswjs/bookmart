import json
import math
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from accounts.decorators import role_required
from .forms import PublisherForm, BookForm
from .models import Publisher, Book


# ── 교재 목록 ──────────────────────────────────────────────────────────────────

@role_required('admin')
def book_list(request):
    publishers = Publisher.objects.prefetch_related('books').all()
    return render(request, 'books/book_list.html', {'publishers': publishers})


# ── 출판사 CRUD ────────────────────────────────────────────────────────────────

@role_required('admin')
def publisher_list(request):
    publishers = Publisher.objects.all()
    return render(request, 'books/publisher_list.html', {'publishers': publishers})


@role_required('admin')
def publisher_create(request):
    if request.method == 'POST':
        form = PublisherForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, '출판사가 등록되었습니다.')
            return redirect('publisher_list')
    else:
        form = PublisherForm()
    return render(request, 'books/publisher_form.html', {'form': form, 'title': '출판사 등록'})


@role_required('admin')
def publisher_edit(request, pk):
    publisher = get_object_or_404(Publisher, pk=pk)
    if request.method == 'POST':
        form = PublisherForm(request.POST, instance=publisher)
        if form.is_valid():
            form.save()
            messages.success(request, '출판사 정보가 수정되었습니다.')
            return redirect('publisher_list')
    else:
        form = PublisherForm(instance=publisher)
    return render(request, 'books/publisher_form.html', {'form': form, 'title': '출판사 수정'})


# ── 교재 CRUD ──────────────────────────────────────────────────────────────────

@role_required('admin')
def book_create(request):
    if request.method == 'POST':
        form = BookForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, '교재가 등록되었습니다.')
            return redirect('book_list')
    else:
        form = BookForm()
    return render(request, 'books/book_form.html', {'form': form, 'title': '교재 등록'})


@role_required('admin')
def book_edit(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == 'POST':
        form = BookForm(request.POST, instance=book)
        if form.is_valid():
            form.save()
            messages.success(request, '교재 정보가 수정되었습니다.')
            return redirect('book_list')
    else:
        form = BookForm(instance=book)
    return render(request, 'books/book_form.html', {'form': form, 'title': '교재 수정'})


@role_required('admin')
def book_toggle(request, pk):
    book = get_object_or_404(Book, pk=pk)
    book.is_active = not book.is_active
    book.save(update_fields=['is_active'])
    action = '활성화' if book.is_active else '비활성화'
    messages.success(request, f'[{book.name}] {action}되었습니다.')
    return redirect('book_list')


# ── 주문 폼용 드롭다운 (로그인만 있으면 됨) ────────────────────────────────────

@login_required
def book_options(request):
    series = request.GET.get('series', '')
    row = request.GET.get('row', '0')
    books = (Book.objects.filter(series=series, is_active=True).select_related('publisher')
             if series else Book.objects.none())
    return render(request, 'books/partials/book_options.html', {'books': books, 'row': row})
