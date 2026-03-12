import logging

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404

from accounts.decorators import role_required
from orders.models import BusinessDocument, Order

logger = logging.getLogger(__name__)


def _number_to_korean(n):
    """숫자를 한글 금액 표기로 변환 (예: 462000 → 사십육만이천)"""
    if n == 0:
        return '영'
    units = ['', '만', '억', '조']
    digits = ['', '일', '이', '삼', '사', '오', '육', '칠', '팔', '구']
    sub_units = ['', '십', '백', '천']
    result = ''
    group_idx = 0
    while n > 0:
        group = n % 10000
        n //= 10000
        if group > 0:
            group_str = ''
            for i in range(4):
                d = group % 10
                group //= 10
                if d > 0:
                    prefix = digits[d] if not (d == 1 and i > 0) else ''
                    group_str = prefix + sub_units[i] + group_str
            result = group_str + units[group_idx] + result
        group_idx += 1
    return result


@role_required('admin', 'agency')
def order_quote(request, pk):
    """견적서 인쇄"""
    order = get_object_or_404(Order, pk=pk)
    items = order.items.select_related('book', 'book__publisher')
    for item in items:
        item.list_price_total = item.list_price * item.quantity
    total_amount = sum(item.list_price_total for item in items)
    total_qty = sum(item.quantity for item in items)
    empty_rows = range(max(0, 16 - items.count()))
    amount_korean = _number_to_korean(total_amount)
    return render(request, 'orders/order_quote.html', {
        'order': order,
        'items': items,
        'total_amount': total_amount,
        'total_qty': total_qty,
        'empty_rows': empty_rows,
        'amount_korean': amount_korean,
    })


@role_required('admin', 'agency')
def order_quote_bulk(request):
    """견적서 일괄 인쇄"""
    ids_str = request.GET.get('ids', '')
    try:
        ids = [int(x) for x in ids_str.split(',') if x.strip()]
    except ValueError:
        ids = []
    if not ids:
        return HttpResponse('인쇄할 주문이 없습니다.', status=400)

    orders_data = []
    qs = Order.objects.filter(pk__in=ids).select_related(
        'teacher', 'delivery', 'agency'
    ).order_by('ordered_at')
    if request.user.role == 'agency':
        qs = qs.filter(agency=request.user)

    for order in qs:
        items = order.items.select_related('book', 'book__publisher')
        for item in items:
            item.list_price_total = item.list_price * item.quantity
        total_amount = sum(item.list_price_total for item in items)
        total_qty = sum(item.quantity for item in items)
        empty_rows = range(max(0, 16 - items.count()))
        amount_korean = _number_to_korean(total_amount)
        orders_data.append({
            'order': order,
            'items': items,
            'total_amount': total_amount,
            'total_qty': total_qty,
            'empty_rows': empty_rows,
            'amount_korean': amount_korean,
        })

    return render(request, 'orders/order_quote_bulk.html', {
        'orders_data': orders_data,
    })


@role_required('admin', 'agency')
def order_invoice(request, pk):
    order = get_object_or_404(Order, pk=pk)
    items = order.items.select_related('book', 'book__publisher')
    total_amount = sum(item.amount for item in items)
    total_qty = sum(item.quantity for item in items)
    empty_rows = range(max(0, 13 - items.count()))
    return render(request, 'orders/order_invoice.html', {
        'order': order,
        'items': items,
        'total_amount': total_amount,
        'total_qty': total_qty,
        'empty_rows': empty_rows,
    })


@role_required('admin', 'agency')
def order_invoice_bulk(request):
    ids_str = request.GET.get('ids', '')
    try:
        ids = [int(x) for x in ids_str.split(',') if x.strip()]
    except ValueError:
        ids = []
    if not ids:
        return HttpResponse('인쇄할 주문이 없습니다.', status=400)

    orders_data = []
    qs = Order.objects.filter(pk__in=ids).select_related(
        'teacher', 'delivery', 'agency'
    ).order_by('ordered_at')
    if request.user.role == 'agency':
        qs = qs.filter(agency=request.user)

    for order in qs:
        items = order.items.select_related('book', 'book__publisher')
        total_amount = sum(item.amount for item in items)
        total_qty = sum(item.quantity for item in items)
        empty_rows = range(max(0, 13 - items.count()))
        orders_data.append({
            'order': order,
            'items': items,
            'total_amount': total_amount,
            'total_qty': total_qty,
            'empty_rows': empty_rows,
        })

    return render(request, 'orders/order_invoice_bulk.html', {
        'orders_data': orders_data,
    })


# ── 견적서 이메일 발송 ────────────────────────────────────────────────────────

@role_required('admin')
def quote_email(request, pk):
    """견적서를 이메일로 발송 (사업자 서류 자동첨부, 미리보기)"""
    order = get_object_or_404(
        Order.objects.select_related('teacher', 'delivery', 'agency'), pk=pk
    )
    items = order.items.select_related('book', 'book__publisher')
    for item in items:
        item.list_price_total = item.list_price * item.quantity
    total_amount = sum(item.list_price_total for item in items)
    total_qty = sum(item.quantity for item in items)
    amount_korean = _number_to_korean(total_amount)

    docs = BusinessDocument.objects.all()
    school_name = order.delivery.name if order.delivery else ''

    # 기본값
    default_subject = f'[북마트] {school_name} 견적서 발송드립니다'
    default_body = (
        f'{school_name} 담당자님 안녕하세요.\n'
        f'북마트E&C입니다.\n\n'
        f'요청하신 교재 견적서를 보내드립니다.\n\n'
        f'■ 견적 내역\n'
    )
    for item in items:
        default_body += f'  - {item.display_name} ({item.display_publisher}) x {item.quantity}부\n'
    default_body += (
        f'\n합계: {total_amount:,}원 (정가 기준)\n\n'
        f'문의사항은 연락 주세요.\n'
        f'전화: 02-833-0864 / 031-917-0864\n'
        f'감사합니다.\n\n'
        f'북마트E&C 전우득 드림'
    )

    if request.method == 'POST':
        to_email = request.POST.get('to_email', '').strip()
        subject = request.POST.get('subject', '').strip()
        body = request.POST.get('body', '').strip()
        doc_ids = request.POST.getlist('doc_ids')

        if not to_email:
            messages.error(request, '수신 이메일을 입력하세요.')
            return redirect('quote_email', pk=pk)
        if not subject:
            messages.error(request, '제목을 입력하세요.')
            return redirect('quote_email', pk=pk)

        # 첨부파일 준비
        attachments = []
        if doc_ids:
            for doc in BusinessDocument.objects.filter(pk__in=doc_ids):
                try:
                    doc.file.open('rb')
                    data = doc.file.read()
                    doc.file.close()
                    ext = doc.extension
                    filename = f'{doc.name}.{ext}' if ext else doc.name
                    attachments.append({
                        'filename': filename,
                        'data': data,
                        'content_type': 'application/octet-stream',
                    })
                except Exception as e:
                    logger.error('서류 파일 읽기 실패 (%s): %s', doc.name, e)

        # 이메일 발송
        from django.conf import settings as conf
        from orders.email_utils import send_email_with_attachments

        account_id = getattr(conf, 'NAVER_EMAIL_1_ID', '')
        account_pw = getattr(conf, 'NAVER_EMAIL_1_PW', '')
        if not account_id or not account_pw:
            messages.error(request, '이메일 계정이 설정되어 있지 않습니다.')
            return redirect('quote_email', pk=pk)

        ok = send_email_with_attachments(
            account_id, account_pw, to_email, subject, body,
            attachments=attachments,
        )
        if ok:
            messages.success(request, f'{to_email}으로 견적서를 발송했습니다. (첨부 {len(attachments)}건)')
            return redirect('order_detail', pk=pk)
        else:
            messages.error(request, '이메일 발송에 실패했습니다. 로그를 확인하세요.')

    return render(request, 'orders/quote_email.html', {
        'order': order,
        'items': items,
        'total_amount': total_amount,
        'total_qty': total_qty,
        'amount_korean': amount_korean,
        'docs': docs,
        'default_subject': default_subject,
        'default_body': default_body,
    })


# ── 사업자 서류 관리 ──────────────────────────────────────────────────────────

@role_required('admin')
def business_doc_list(request):
    """사업자 서류 목록 + 업로드"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        file = request.FILES.get('file')
        if not name or not file:
            messages.error(request, '서류명과 파일을 입력하세요.')
        else:
            BusinessDocument.objects.create(
                name=name,
                file=file,
                auto_attach='auto_attach' in request.POST,
            )
            messages.success(request, f'"{name}" 서류를 등록했습니다.')
        return redirect('business_doc_list')

    docs = BusinessDocument.objects.all()
    return render(request, 'orders/business_doc_list.html', {'docs': docs})


@role_required('admin')
def business_doc_delete(request, pk):
    """사업자 서류 삭제"""
    if request.method == 'POST':
        doc = get_object_or_404(BusinessDocument, pk=pk)
        doc.file.delete(save=False)
        doc.delete()
        messages.success(request, '서류를 삭제했습니다.')
    return redirect('business_doc_list')


@role_required('admin')
def business_doc_toggle(request, pk):
    """자동첨부 토글"""
    if request.method == 'POST':
        doc = get_object_or_404(BusinessDocument, pk=pk)
        doc.auto_attach = not doc.auto_attach
        doc.save(update_fields=['auto_attach'])
    return redirect('business_doc_list')
