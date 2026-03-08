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
    path('agencies/import/', views.agency_import, name='agency_import'),
    path('agencies/import/sample/', views.agency_import_sample, name='agency_import_sample'),
    path('agencies/<int:pk>/toggle/', views.agency_toggle, name='agency_toggle'),

    # 업체 전용 — 배송지(학교) 관리
    path('deliveries/', views.delivery_list, name='delivery_list'),
    path('deliveries/new/', views.delivery_create, name='delivery_create'),

    # 업체 전용 — 선생님 관리
    path('teachers/', views.teacher_list, name='teacher_list'),
    path('teachers/new/', views.teacher_create, name='teacher_create'),
    path('teachers/<int:pk>/reset-password/', views.teacher_reset_password, name='teacher_reset_password'),
    path('teachers/<int:pk>/toggle/', views.teacher_toggle, name='teacher_toggle'),

    # 초대 링크
    path('teachers/<int:pk>/invite/', views.invite_send, name='invite_send'),
    path('teachers/<int:pk>/invite-link/', views.invite_link, name='invite_link'),
    path('invite/<str:token>/', views.invite_setup, name='invite_setup'),

    # 업체 간편주문 링크
    path('my-link/', views.agency_link, name='agency_link'),
    path('my-link/regenerate/', views.agency_regenerate_slug, name='agency_regenerate_slug'),
]
