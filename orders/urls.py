from django.urls import path
from . import views

urlpatterns = [
    # ── 대시보드 ──────────────────────────────────────────────────────────────
    path('dashboard/', views.dashboard, name='dashboard'),

    # ── 주문 ──────────────────────────────────────────────────────────────────
    path('orders/', views.order_list, name='order_list'),
    path('orders/create/', views.order_create, name='order_create'),
    path('orders/admin-create/', views.order_create_admin, name='order_create_admin'),
    path('orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('orders/<int:pk>/cancel/', views.order_cancel, name='order_cancel'),
    path('orders/<int:pk>/ship/', views.order_ship, name='order_ship'),
    path('orders/<int:pk>/deliver/', views.order_deliver, name='order_deliver'),

    # ── 반품 ──────────────────────────────────────────────────────────────────
    path('returns/', views.return_list, name='return_list'),
    path('returns/create/', views.return_create, name='return_create'),
    path('returns/<int:pk>/', views.return_detail, name='return_detail'),
    path('returns/<int:pk>/confirm/', views.return_confirm, name='return_confirm'),
    path('returns/<int:pk>/reject/', views.return_reject, name='return_reject'),

    # ── 정산/현황 ──────────────────────────────────────────────────────────────
    path('ledger/', views.ledger, name='ledger'),
    path('sales/', views.sales_report, name='sales_report'),
    path('purchase/', views.purchase_order, name='purchase_order'),
    path('payments/new/', views.payment_create, name='payment_create'),

    # ── 수신함 ────────────────────────────────────────────────────────────────
    path('inbox/', views.inbox_list, name='inbox_list'),
    path('inbox/bulk-skip/', views.inbox_bulk_skip, name='inbox_bulk_skip'),
    path('inbox/fetch/', views.fetch_emails, name='fetch_emails'),
    path('inbox/<int:pk>/', views.inbox_process, name='inbox_process'),
    path('inbox/attachment/<int:pk>/download/', views.attachment_download, name='attachment_download'),
    path('inbox/attachment/<int:pk>/preview/', views.attachment_preview, name='attachment_preview'),
    path('webhook/sms/', views.sms_webhook, name='sms_webhook'),

    # ── 엑셀 Export ────────────────────────────────────────────────────────────
    path('ledger/export/', views.export_ledger, name='export_ledger'),
    path('sales/export/', views.export_sales, name='export_sales'),
    path('purchase/export/', views.export_purchase, name='export_purchase'),
]
