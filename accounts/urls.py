from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('password-change/', views.CustomPasswordChangeView.as_view(), name='password_change'),

    # 총판 전용 — 업체 관리
    path('agencies/', views.agency_list, name='agency_list'),
    path('agencies/new/', views.agency_create, name='agency_create'),
    path('agencies/<int:pk>/toggle/', views.agency_toggle, name='agency_toggle'),

    # 업체 전용 — 배송지(학교) 관리
    path('deliveries/', views.delivery_list, name='delivery_list'),
    path('deliveries/new/', views.delivery_create, name='delivery_create'),

    # 업체 전용 — 선생님 관리
    path('teachers/', views.teacher_list, name='teacher_list'),
    path('teachers/new/', views.teacher_create, name='teacher_create'),
    path('teachers/<int:pk>/reset-password/', views.teacher_reset_password, name='teacher_reset_password'),
    path('teachers/<int:pk>/toggle/', views.teacher_toggle, name='teacher_toggle'),
]
