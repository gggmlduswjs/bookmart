from django.urls import path
from . import views, views_simple

urlpatterns = [
    # ── 간편주문 (공개, 로그인 불필요) ──────────────────────────────────────────
    # 짧은 코드 (신규)
    path('s/<str:slug>/', views_simple.simple_landing, name='simple_landing'),
    path('s/<str:slug>/order/', views_simple.simple_order, name='simple_order'),
    path('s/<str:slug>/confirm/<int:order_id>/', views_simple.simple_confirm, name='simple_confirm'),
    path('s/<str:slug>/orders/', views_simple.simple_order_list, name='simple_order_list'),
    path('s/<str:slug>/delivery/', views_simple.simple_delivery_status, name='simple_delivery_status'),
    path('s/<str:slug>/parse-excel/', views_simple.simple_parse_excel, name='simple_parse_excel'),

    # ── 대시보드 ──────────────────────────────────────────────────────────────
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/agency/', views.agency_dashboard, name='agency_dashboard'),

    # ── 주문 ──────────────────────────────────────────────────────────────────
    path('orders/', views.order_list, name='order_list'),
    path('orders/create/', views.order_create, name='order_create'),
    path('orders/admin-create/', views.order_create_admin, name='order_create_admin'),
    path('orders/parse-excel/', views.parse_order_excel, name='parse_order_excel'),
    path('orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('orders/<int:pk>/cancel/', views.order_cancel, name='order_cancel'),
    path('orders/<int:pk>/delete/', views.order_delete, name='order_delete'),
    path('orders/bulk-delete/', views.order_bulk_delete, name='order_bulk_delete'),
    path('orders/<int:pk>/ship/', views.order_ship, name='order_ship'),
    path('orders/<int:pk>/deliver/', views.order_deliver, name='order_deliver'),
    path('orders/<int:pk>/invoice/', views.order_invoice, name='order_invoice'),
    path('orders/invoice/bulk/', views.order_invoice_bulk, name='order_invoice_bulk'),
    path('orders/<int:pk>/quote/', views.order_quote, name='order_quote'),
    path('orders/quote/bulk/', views.order_quote_bulk, name='order_quote_bulk'),

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
    path('inbox/<int:pk>/skip/', views.inbox_single_skip, name='inbox_single_skip'),
    path('inbox/<int:pk>/delete/', views.inbox_delete, name='inbox_delete'),
    path('inbox/bulk-delete/', views.inbox_bulk_delete, name='inbox_bulk_delete'),
    path('inbox/fetch/', views.fetch_emails, name='fetch_emails'),
    path('inbox/<int:pk>/', views.inbox_process, name='inbox_process'),
    path('inbox/<int:pk>/reply/', views.inbox_reply, name='inbox_reply'),
    path('inbox/attachment/<int:pk>/download/', views.attachment_download, name='attachment_download'),
    path('inbox/attachment/<int:pk>/preview/', views.attachment_preview, name='attachment_preview'),
    path('inbox/sms-desk/', views.sms_desk, name='sms_desk'),
    path('inbox/send-sms/', views.send_sms_ajax, name='send_sms_ajax'),
    path('webhook/sms/', views.sms_webhook, name='sms_webhook'),

    # ── 엑셀 Export ────────────────────────────────────────────────────────────
    path('ledger/export/', views.export_ledger, name='export_ledger'),
    path('sales/export/', views.export_sales, name='export_sales'),
    path('purchase/export/', views.export_purchase, name='export_purchase'),
]
