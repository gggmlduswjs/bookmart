from django.urls import path
from . import views

urlpatterns = [
    path('', views.book_list, name='book_list'),
    path('new/', views.book_create, name='book_create'),
    path('<int:pk>/edit/', views.book_edit, name='book_edit'),
    path('<int:pk>/toggle/', views.book_toggle, name='book_toggle'),
    path('<int:pk>/delete/', views.book_delete, name='book_delete'),
    path('bulk-delete/', views.book_bulk_delete, name='book_bulk_delete'),
    path('import/', views.book_import, name='book_import'),
    path('import/sample/', views.book_import_sample, name='book_import_sample'),
    path('options/', views.book_options, name='book_options'),
    path('publishers/', views.publisher_list, name='publisher_list'),
    path('publishers/new/', views.publisher_create, name='publisher_create'),
    path('publishers/<int:pk>/edit/', views.publisher_edit, name='publisher_edit'),
]
