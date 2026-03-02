from django.urls import path
from . import views

urlpatterns = [
    path('', views.book_list, name='book_list'),
    path('options/', views.book_options, name='book_options'),  # htmx 드롭다운용
]
