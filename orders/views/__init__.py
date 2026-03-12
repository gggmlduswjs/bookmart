from .dashboard import (
    dashboard, agency_dashboard, site_settings,
    notice_list, notice_create, notice_edit, notice_delete, notice_toggle,
    api_counts,
)
from .order import (
    order_list, order_create, individual_order_create, order_create_admin,
    order_detail, order_copy, order_edit, order_cancel,
    order_delete, order_bulk_delete, order_restore, order_search_api,
)
from .shipping import order_ship, order_deliver, delivery_manage, order_quick_ship, order_quick_deliver, order_quick_unship, order_quick_undeliver, order_bulk_tracking
from .document import (
    order_quote, order_quote_bulk, order_invoice, order_invoice_bulk,
    quote_email, business_doc_list, business_doc_delete, business_doc_toggle,
)
from .return_ import (
    return_list, return_create, return_create_from_order,
    return_detail, return_confirm, return_reject,
)
from .report import (
    ledger, sales_report, purchase_order, payment_create,
    export_ledger, export_sales, export_orders, export_purchase,
    import_legacy, import_legacy_delete,
)
from .inbox import (
    inbox_list, inbox_single_skip, inbox_delete, inbox_bulk_delete,
    inbox_bulk_skip, fetch_emails, inbox_process, inbox_reply,
    attachment_download, attachment_preview,
    sms_webhook, sms_desk, send_sms_ajax, parse_order_excel, sms_import_xml,
)
from .call import (
    call_order_upload, call_order_confirm, call_inbox,
    call_recording_process, call_recording_skip, call_recording_retry,
    call_recording_retry_all,
    call_sync_drive, call_recording_webhook,
    gdrive_auth_start, gdrive_auth_callback,
)
from .mobile import mobile_delivery_list, mobile_delivery_done
