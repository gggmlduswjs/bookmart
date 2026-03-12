import json
import logging
import math
import re as _re
from collections import OrderedDict

from django.contrib import messages
from django.core.files.base import ContentFile
from django.db.models import Count, Q, Max, Subquery, OuterRef
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt

from accounts.decorators import role_required
from accounts.models import User
from books.models import Book
from orders.models import (
    AuditLog, CallRecording, DeliveryAddress, InboxAttachment, InboxMessage,
    Order, OrderItem, OrderStatusLog,
)
from orders.sms import send_sms

from ._helpers import _audit, get_books_json, get_agencies_json, get_teachers_json, get_series_list

logger = logging.getLogger(__name__)


def _extract_phone_digits(sender: str) -> str:
    """sender 문자열에서 전화번호 숫자만 추출 (예: '이쁜둘째딸' → '', '010-5429-6196' → '01054296196')"""
    m = _re.search(r'(\d[\d\-]{8,})', sender or '')
    if m:
        return m.group(1).replace('-', '')
    return ''


def _extract_reply_phone(msg) -> str:
    """수신 SMS에서 답장용 전화번호 추출 (sender → subject → content 순)"""
    for text in [msg.sender, msg.subject, (msg.content or '')[:200]]:
        if not text:
            continue
        m = _re.search(r'(\d[\d\-]{8,})', text)
        if m:
            return m.group(1).replace('-', '')
    return ''


def _build_sms_conversations(sms_qs, hide_done):
    """SMS 메시지를 전화번호 기준으로 대화별로 그룹핑.
    phone 필드가 있으면 우선 사용, 없으면 sender에서 추출."""
    conversations = OrderedDict()  # phone_key -> conv dict

    msgs = list(sms_qs)
    for msg in msgs:
        is_sent = msg.subject == '[발신]'
        # phone 필드 우선, 없으면 sender에서 추출
        phone = getattr(msg, 'phone', '') or ''
        if not phone:
            phone = _extract_phone_digits(msg.sender)
        if not phone:
            phone = msg.sender.strip()

        if phone not in conversations:
            conversations[phone] = {
                'phone': phone,
                'sender_name': '' if is_sent else msg.sender,
                'latest_msg': msg,
                'latest_time': msg.received_at,
                'total_count': 0,
                'unread_count': 0,
                'unprocessed_count': 0,
                'latest_pk': msg.pk,
                'preview': msg.content[:80] if msg.content else '',
                'has_order': msg.order_id is not None,
            }
        else:
            conv = conversations[phone]
            if msg.received_at > conv['latest_time']:
                conv['latest_msg'] = msg
                conv['latest_time'] = msg.received_at
                conv['latest_pk'] = msg.pk
                conv['preview'] = msg.content[:80] if msg.content else ''
            if not conv['sender_name'] and not is_sent:
                conv['sender_name'] = msg.sender

        conv = conversations[phone]
        if not is_sent:
            conv['total_count'] += 1
        if not msg.is_read and not is_sent:
            conv['unread_count'] += 1
        if not msg.is_processed and not is_sent:
            conv['unprocessed_count'] += 1
        if msg.order_id:
            conv['has_order'] = True

    result = list(conversations.values())
    if hide_done:
        result = [c for c in result if c['total_count'] > 0]
    return result


# ── 통합 수신함 ────────────────────────────────────────────────────────────────

@role_required('admin')
def inbox_list(request):
    hide_done = request.GET.get('hide_done', '')
    search = request.GET.get('q', '').strip()
    tab = request.GET.get('tab', 'email')
    qs = InboxMessage.objects.annotate(
        attachment_count=Count('attachments')
    ).select_related('order')
    if hide_done:
        qs = qs.filter(is_processed=False)
    if search:
        qs = qs.filter(
            Q(sender__icontains=search) |
            Q(subject__icontains=search) |
            Q(content__icontains=search)
        )
    email_qs = qs.filter(source='email').order_by('-received_at')
    # SMS: 발신 포함해서 가져와서 대화별 그룹핑
    sms_all = qs.filter(source='sms').order_by('-received_at')
    sms_conversations = _build_sms_conversations(sms_all, hide_done)
    unread_email = InboxMessage.objects.filter(is_processed=False, source='email').count()
    unread_sms = InboxMessage.objects.filter(is_processed=False, source='sms').exclude(subject='[발신]').count()

    # 통화 녹음 탭 데이터
    from pathlib import Path
    from django.conf import settings as conf
    from django.core.paginator import Paginator

    call_qs = CallRecording.objects.all()
    call_status = request.GET.get('call_status', '')
    if call_status:
        call_qs = call_qs.filter(status=call_status)
    call_paginator = Paginator(call_qs.order_by('-created_at'), 30)
    call_page = call_paginator.get_page(request.GET.get('call_page'))
    call_counts = dict(
        CallRecording.objects.values_list('status').annotate(c=Count('id')).values_list('status', 'c')
    )
    pending_calls = call_counts.get('pending', 0) + call_counts.get('parsed', 0)
    token_path = Path(conf.BASE_DIR) / 'gdrive_token.json'

    return render(request, 'orders/inbox_list.html', {
        'email_messages': email_qs,
        'sms_conversations': sms_conversations,
        'tab': tab,
        'hide_done': hide_done,
        'search': search,
        'unread_email': unread_email,
        'unread_sms': unread_sms,
        'unread_count': unread_email + unread_sms,
        'call_page': call_page,
        'call_status': call_status,
        'call_counts': call_counts,
        'pending_calls': pending_calls,
        'gdrive_connected': token_path.exists(),
    })


@role_required('admin')
def inbox_single_skip(request, pk):
    """단건 처리완료 (is_processed=True)"""
    if request.method != 'POST':
        return redirect('inbox_list')
    msg = get_object_or_404(InboxMessage, pk=pk)
    tab = 'sms' if msg.source == 'sms' else 'email'
    if not msg.is_processed:
        msg.is_processed = True
        msg.save(update_fields=['is_processed'])
        messages.success(request, '처리완료했습니다.')
    return redirect(f'/inbox/?tab={tab}')


def _get_imap_account(label):
    """imap_key의 account_label로 계정 정보 반환"""
    from django.conf import settings as conf
    account_map = {}
    if hasattr(conf, 'NAVER_EMAIL_1_ID'):
        account_map['007bm'] = (conf.NAVER_EMAIL_1_ID, conf.NAVER_EMAIL_1_PW)
    if hasattr(conf, 'NAVER_EMAIL_2_ID'):
        account_map['002bm'] = (conf.NAVER_EMAIL_2_ID, conf.NAVER_EMAIL_2_PW)
    return account_map.get(label)


def _delete_imap_by_key(imap_key):
    from orders.email_utils import delete_email_imap
    parts = imap_key.split(':', 1)
    if len(parts) != 2:
        return
    label, uid_str = parts
    creds = _get_imap_account(label)
    if creds:
        delete_email_imap(creds[0], creds[1], uid_str)


def _delete_imap_bulk(imap_keys):
    from orders.email_utils import delete_emails_imap
    by_account = {}
    for key in imap_keys:
        parts = key.split(':', 1)
        if len(parts) != 2:
            continue
        label, uid_str = parts
        by_account.setdefault(label, []).append(uid_str)
    for label, uids in by_account.items():
        creds = _get_imap_account(label)
        if creds:
            delete_emails_imap(creds[0], creds[1], uids)


@role_required('admin')
def inbox_delete(request, pk):
    """수신 메시지 단건 삭제"""
    if request.method != 'POST':
        return redirect('inbox_list')
    msg = get_object_or_404(InboxMessage, pk=pk)
    tab = 'sms' if msg.source == 'sms' else 'email'
    if msg.source == 'email' and msg.imap_key:
        _delete_imap_by_key(msg.imap_key)
    msg.attachments.all().delete()
    msg.delete()
    messages.success(request, '삭제했습니다.')
    return redirect(f'/inbox/?tab={tab}')


@role_required('admin')
def inbox_bulk_delete(request):
    """선택한 수신 메시지 일괄 삭제"""
    if request.method != 'POST':
        return redirect('inbox_list')
    tab = request.POST.get('tab', 'email')
    msg_ids = request.POST.getlist('msg_ids')
    if msg_ids:
        qs = InboxMessage.objects.filter(pk__in=msg_ids)
        count = qs.count()
        email_msgs = qs.filter(source='email').exclude(imap_key='').values_list('imap_key', flat=True)
        if email_msgs:
            _delete_imap_bulk(list(email_msgs))
        qs.delete()
        messages.success(request, f'{count}건을 삭제했습니다.')
    else:
        messages.warning(request, '선택된 메시지가 없습니다.')
    return redirect(f'/inbox/?tab={tab}')


@role_required('admin')
def inbox_bulk_skip(request):
    """선택한 수신 메시지를 일괄 건너뛰기 (is_processed=True)"""
    if request.method != 'POST':
        return redirect('inbox_list')

    action = request.POST.get('action', '')
    tab = request.POST.get('tab', 'email')
    if action == 'skip_all':
        updated = InboxMessage.objects.filter(is_processed=False, source='email').update(is_processed=True)
        messages.success(request, f'미처리 메일 {updated}건을 모두 건너뛰었습니다.')
    elif action == 'skip_all_sms':
        updated = InboxMessage.objects.filter(is_processed=False, source='sms').update(is_processed=True)
        messages.success(request, f'미처리 문자 {updated}건을 모두 건너뛰었습니다.')
    else:
        msg_ids = request.POST.getlist('msg_ids')
        if msg_ids:
            updated = InboxMessage.objects.filter(
                pk__in=msg_ids, is_processed=False
            ).update(is_processed=True)
            messages.success(request, f'{updated}건을 건너뛰었습니다.')
        else:
            messages.warning(request, '선택된 메시지가 없습니다.')

    return redirect(f'/inbox/?tab={tab}')


@role_required('admin')
def fetch_emails(request):
    """네이버 IMAP 메일 가져오기"""
    if request.method != 'POST':
        return redirect('inbox_list')

    from django.conf import settings as conf
    from orders.email_utils import fetch_naver_emails

    accounts = [
        (conf.NAVER_EMAIL_1_ID, conf.NAVER_EMAIL_1_PW, '007bm'),
        (conf.NAVER_EMAIL_2_ID, conf.NAVER_EMAIL_2_PW, '002bm'),
    ]

    all_existing_keys = set(
        InboxMessage.objects.values_list('imap_key', flat=True)
    )

    new_count = 0
    sync_count = 0
    for acc_id, acc_pw, label in accounts:
        if not acc_id or not acc_pw:
            continue
        emails, read_sync = fetch_naver_emails(acc_id, acc_pw, label,
                                               existing_keys=all_existing_keys)

        if read_sync:
            for imap_key, is_seen in read_sync.items():
                updated = InboxMessage.objects.filter(
                    imap_key=imap_key, is_read=not is_seen
                ).update(is_read=is_seen)
                sync_count += updated

        if not emails:
            continue

        for e in emails:
            msg_obj = InboxMessage.objects.create(
                source=InboxMessage.Source.EMAIL,
                account_label=e['account_label'],
                sender=e['sender'],
                subject=e['subject'],
                content=e['content'],
                received_at=e['received_at'],
                imap_key=e['imap_key'],
                is_processed=False,
                is_read=e.get('is_seen', False),
                message_id=e.get('message_id', ''),
            )
            for att in e.get('attachments', []):
                file_obj = ContentFile(att['data'], name=att['filename'])
                InboxAttachment.objects.create(
                    message=msg_obj,
                    file=file_obj,
                    filename=att['filename'],
                    content_type=att['content_type'],
                    size=len(att['data']),
                )
            new_count += 1

    sync_msg = f' (읽음 상태 {sync_count}건 동기화)' if sync_count else ''

    # AJAX 요청이면 JSON 응답
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'count': new_count, 'sync': sync_count})

    messages.success(request, f'새 메일 {new_count}건을 가져왔습니다.{sync_msg}')
    return redirect('inbox_list')


@role_required('admin')
def inbox_process(request, pk):
    """수신 메시지를 보면서 주문 등록"""
    inbox_msg = get_object_or_404(InboxMessage, pk=pk)

    # 열 때 읽음 처리
    if not inbox_msg.is_read:
        inbox_msg.is_read = True
        inbox_msg.save(update_fields=['is_read'])
        if inbox_msg.source == 'email' and inbox_msg.imap_key:
            from django.conf import settings as conf
            from orders.email_utils import mark_as_read_imap
            parts = inbox_msg.imap_key.split(':', 1)
            if len(parts) == 2:
                label, uid_str = parts
                account_map = {}
                if hasattr(conf, 'NAVER_EMAIL_1_ID'):
                    account_map['007bm'] = (conf.NAVER_EMAIL_1_ID, conf.NAVER_EMAIL_1_PW)
                if hasattr(conf, 'NAVER_EMAIL_2_ID'):
                    account_map['002bm'] = (conf.NAVER_EMAIL_2_ID, conf.NAVER_EMAIL_2_PW)
                creds = account_map.get(label)
                if creds:
                    mark_as_read_imap(creds[0], creds[1], uid_str)

    next_unprocessed = (
        InboxMessage.objects.filter(is_processed=False, source=inbox_msg.source)
        .exclude(pk=pk).order_by('-received_at').first()
    )

    # 처리 완료 (주문 없이)
    if request.method == 'POST' and 'skip' in request.POST:
        inbox_msg.is_processed = True
        inbox_msg.save(update_fields=['is_processed'])
        messages.info(request, '처리 완료되었습니다.')
        nxt = InboxMessage.objects.filter(is_processed=False, source=inbox_msg.source).order_by('-received_at').first()
        if nxt:
            return redirect('inbox_process', pk=nxt.pk)
        return redirect('inbox_list')

    agencies = User.objects.filter(role='agency', is_active=True).order_by('name')
    agencies_json = json.dumps([{
        'id': a.pk, 'name': a.name,
    } for a in agencies], ensure_ascii=False)

    teachers = (
        User.objects.filter(role='teacher', is_active=True)
        .select_related('agency', 'delivery_address')
        .order_by('agency__name', 'name')
    )
    teachers_json = json.dumps([{
        'id': t.pk,
        'name': t.name,
        'phone': t.phone or '',
        'agency_id': t.agency_id,
        'delivery_id': t.delivery_address_id,
        'delivery_name': t.delivery_address.name if t.delivery_address else '',
        'delivery_address': t.delivery_address.address if t.delivery_address else '',
        'delivery_phone': t.delivery_address.phone if t.delivery_address else '',
        'has_delivery': bool(t.delivery_address),
    } for t in teachers], ensure_ascii=False)

    books = Book.objects.filter(is_active=True).select_related('publisher')
    series_list = sorted(set(b.series for b in books if b.series))
    books_json = json.dumps([{
        'id': b.id,
        'series': b.series or '기타',
        'name': b.name,
        'publisher': b.publisher.name,
        'unit_price': math.floor(b.list_price * float(b.publisher.supply_rate) / 100),
    } for b in books], ensure_ascii=False)

    if request.method == 'POST' and 'skip' not in request.POST:
        agency_id = request.POST.get('agency_id', '').strip()
        teacher_id = request.POST.get('teacher_id', '').strip()
        new_teacher_name = request.POST.get('new_teacher_name', '').strip()
        new_teacher_phone = request.POST.get('new_teacher_phone', '').strip()
        delivery_school = request.POST.get('delivery_school', '').strip()
        delivery_address_val = request.POST.get('delivery_address', '').strip()
        delivery_phone = request.POST.get('delivery_phone', '').strip()

        try:
            agency = User.objects.get(pk=agency_id, role='agency', is_active=True)
        except (User.DoesNotExist, ValueError):
            messages.error(request, '업체를 선택해 주세요.')
            return redirect('inbox_process', pk=pk)

        if teacher_id:
            try:
                teacher = User.objects.select_related('delivery_address').get(
                    pk=teacher_id, role='teacher', is_active=True
                )
            except (User.DoesNotExist, ValueError):
                messages.error(request, '선생님을 선택해 주세요.')
                return redirect('inbox_process', pk=pk)
        elif new_teacher_name:
            login_id = f'a_{new_teacher_phone or "nophone"}_{agency.pk}'
            if User.objects.filter(login_id=login_id).exists():
                teacher = User.objects.get(login_id=login_id)
            else:
                teacher = User(
                    login_id=login_id, role='teacher',
                    name=new_teacher_name, phone=new_teacher_phone,
                    agency=agency, must_change_password=False,
                )
                teacher.set_unusable_password()
                teacher.save()
        else:
            messages.error(request, '선생님을 선택하거나 새로 입력해 주세요.')
            return redirect('inbox_process', pk=pk)

        if delivery_school:
            delivery, created = DeliveryAddress.objects.get_or_create(
                agency=agency, name=delivery_school,
                defaults={'address': delivery_address_val, 'phone': delivery_phone},
            )
            if not created and delivery_address_val:
                delivery.address = delivery_address_val
                delivery.phone = delivery_phone
                delivery.save(update_fields=['address', 'phone'])
            teacher.delivery_address = delivery
            teacher.save(update_fields=['delivery_address'])
        elif not teacher.delivery_address:
            messages.error(request, '배송지를 입력해 주세요.')
            return redirect('inbox_process', pk=pk)

        items = []
        i = 0
        while f'book_{i}' in request.POST or f'custom_name_{i}' in request.POST:
            book_id = request.POST.get(f'book_{i}', '').strip()
            custom_name = request.POST.get(f'custom_name_{i}', '').strip()
            custom_price = request.POST.get(f'custom_price_{i}', '').strip()
            qty_str = request.POST.get(f'qty_{i}', '').strip()
            if book_id and qty_str:
                try:
                    qty = int(qty_str)
                    if qty > 0:
                        items.append({'book_id': int(book_id), 'qty': qty})
                except (ValueError, TypeError):
                    pass
            elif custom_name and qty_str:
                try:
                    qty = int(qty_str)
                    price = int(custom_price) if custom_price else 0
                    if qty > 0:
                        items.append({'custom_name': custom_name, 'custom_price': price, 'qty': qty})
                except (ValueError, TypeError):
                    pass
            i += 1

        if not items:
            messages.error(request, '주문할 교재를 1권 이상 선택하세요.')
        else:
            order = Order.objects.create(
                order_no=Order.generate_order_no(),
                agency=agency,
                teacher=teacher,
                delivery=teacher.delivery_address,
                memo=request.POST.get('memo', ''),
                source=Order.Source.INBOX,
            )
            for item in items:
                if 'book_id' in item:
                    try:
                        book = Book.objects.get(id=item['book_id'], is_active=True)
                        OrderItem(order=order, book=book, quantity=item['qty']).save()
                    except Book.DoesNotExist:
                        pass
                else:
                    OrderItem(order=order, custom_book_name=item['custom_name'],
                              unit_price=item['custom_price'], quantity=item['qty']).save()

            OrderStatusLog.objects.create(
                order=order, old_status='', new_status='pending',
                changed_by=request.user, memo='수신함에서 주문 생성',
            )
            _audit(request, AuditLog.Action.ORDER_CREATE, order, f'[수신함] 주문 {order.order_no} 생성')

            inbox_msg.is_processed = True
            inbox_msg.order = order
            inbox_msg.save(update_fields=['is_processed', 'order'])

            messages.success(request, f'주문 등록 완료. 주문번호: {order.order_no}')
            nxt = InboxMessage.objects.filter(is_processed=False, source=inbox_msg.source).order_by('-received_at').first()
            if nxt:
                return redirect('inbox_process', pk=nxt.pk)
            return redirect('inbox_list')

    attachments = inbox_msg.attachments.all()

    # AI 이메일 파싱
    parsed_json = 'null'
    if inbox_msg.content and not inbox_msg.is_processed:
        try:
            from orders.call_order import parse_order_from_email
            books_data = [{
                'id': b.id, 'series': b.series or '기타', 'name': b.name,
                'publisher': b.publisher.name,
                'unit_price': math.floor(b.list_price * float(b.publisher.supply_rate) / 100),
            } for b in books]
            agencies_data = [{'id': a.pk, 'name': a.name} for a in agencies]
            teachers_data = [{
                'id': t.pk, 'name': t.name, 'agency_id': t.agency_id,
                'agency_name': t.agency.name if t.agency else '',
                'delivery_name': t.delivery_address.name if t.delivery_address else '',
            } for t in teachers]
            parsed, err = parse_order_from_email(
                sender=inbox_msg.sender or '',
                subject=inbox_msg.subject or '',
                body=inbox_msg.content,
                book_list=books_data,
                agencies=agencies_data,
                teachers=teachers_data,
            )
            if parsed and not err:
                parsed_json = json.dumps(parsed, ensure_ascii=False)
            elif err:
                logger.warning('이메일 AI 파싱 실패: %s', err)
        except Exception:
            logger.exception('이메일 AI 파싱 오류')

    # SMS 답장용 전화번호 추출 (sender, subject, content 순서로 탐색)
    sms_reply_phone = ''
    if inbox_msg.source == 'sms':
        for text in [inbox_msg.sender, inbox_msg.subject, inbox_msg.content[:200]]:
            if not text:
                continue
            phone_match = _re.search(r'(\d[\d\-]{8,})', text)
            if phone_match:
                sms_reply_phone = phone_match.group(1).replace('-', '')
                break
        # 번호 못 찾으면 기본값 (테스트용)
        if not sms_reply_phone:
            sms_reply_phone = '01054296196'
        if len(sms_reply_phone) == 11:
            sms_reply_phone = f'{sms_reply_phone[:3]}-{sms_reply_phone[3:7]}-{sms_reply_phone[7:]}'
        elif len(sms_reply_phone) == 10:
            sms_reply_phone = f'{sms_reply_phone[:3]}-{sms_reply_phone[3:6]}-{sms_reply_phone[6:]}'

    # SMS 대화 내역 (같은 발신번호의 메시지들 - 수신+발신 포함)
    sms_conversation = []
    if inbox_msg.source == 'sms':
        q_filter = Q(sender__contains=inbox_msg.sender)
        # sender에서 전화번호 추출
        phone_in_sender = _re.search(r'(\d[\d\-]{8,})', inbox_msg.sender or '')
        if phone_in_sender:
            phone_digits = phone_in_sender.group(1).replace('-', '')
            q_filter = q_filter | Q(sender__contains=phone_digits)
        # sms_reply_phone으로도 매칭 (발신 문자 찾기)
        if sms_reply_phone:
            q_filter = q_filter | Q(sender__contains=sms_reply_phone)
            reply_digits = sms_reply_phone.replace('-', '')
            q_filter = q_filter | Q(sender__contains=reply_digits)
        sms_conversation = list(
            InboxMessage.objects.filter(source='sms')
            .filter(q_filter)
            .order_by('received_at')[:100]
        )

    return render(request, 'orders/inbox_process.html', {
        'inbox_msg': inbox_msg,
        'agencies': agencies,
        'agencies_json': agencies_json,
        'teachers_json': teachers_json,
        'series_list': series_list,
        'books_json': books_json,
        'attachments': attachments,
        'next_unprocessed': next_unprocessed,
        'parsed_json': parsed_json,
        'sms_reply_phone': sms_reply_phone,
        'sms_conversation': sms_conversation,
    })


@role_required('admin')
def inbox_reply(request, pk):
    """수신 이메일에 답장 발송"""
    inbox_msg = get_object_or_404(InboxMessage, pk=pk)
    if request.method != 'POST' or inbox_msg.source != 'email':
        return redirect('inbox_process', pk=pk)

    reply_body = request.POST.get('reply_body', '').strip()
    if not reply_body:
        messages.warning(request, '답장 내용을 입력하세요.')
        return redirect('inbox_process', pk=pk)

    from django.conf import settings as conf
    from orders.email_utils import send_reply_email

    sender = inbox_msg.sender or ''
    match = _re.search(r'[\w.\-+]+@[\w.\-]+\.\w+', sender)
    to_email = match.group(0) if match else sender

    subj = inbox_msg.subject or ''
    reply_subject = subj if subj.lower().startswith('re:') else f'Re: {subj}'

    in_reply_to = inbox_msg.message_id or None
    references = inbox_msg.message_id or None

    account_map = {}
    if hasattr(conf, 'NAVER_EMAIL_1_ID'):
        account_map['007bm'] = (conf.NAVER_EMAIL_1_ID, conf.NAVER_EMAIL_1_PW)
    if hasattr(conf, 'NAVER_EMAIL_2_ID'):
        account_map['002bm'] = (conf.NAVER_EMAIL_2_ID, conf.NAVER_EMAIL_2_PW)

    creds = account_map.get(inbox_msg.account_label)
    if not creds:
        creds = (conf.NAVER_EMAIL_1_ID, conf.NAVER_EMAIL_1_PW)

    ok = send_reply_email(
        account_id=creds[0],
        account_pw=creds[1],
        to_email=to_email,
        subject=reply_subject,
        body=reply_body,
        in_reply_to=in_reply_to,
        references=references,
    )

    if ok:
        messages.success(request, f'{to_email}에 답장을 발송했습니다.')
    else:
        messages.error(request, '답장 발송에 실패했습니다. 로그를 확인하세요.')

    return redirect('inbox_process', pk=pk)


@role_required('admin')
def attachment_download(request, pk):
    """첨부파일 다운로드"""
    from urllib.parse import quote
    att = get_object_or_404(InboxAttachment, pk=pk)
    att.file.open('rb')
    data = att.file.read()
    att.file.close()
    resp = HttpResponse(data, content_type=att.content_type or 'application/octet-stream')
    encoded_filename = quote(att.filename)
    resp['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded_filename}"
    return resp


@role_required('admin')
def attachment_preview(request, pk):
    """엑셀 첨부파일 미리보기 (HTML 테이블)"""
    att = get_object_or_404(InboxAttachment, pk=pk)
    if not att.is_excel:
        return HttpResponse('미리보기를 지원하지 않는 파일입니다.', status=400)

    import openpyxl

    try:
        wb = openpyxl.load_workbook(att.file, read_only=True, data_only=True)
    except Exception:
        return HttpResponse('엑셀 파일을 열 수 없습니다.', status=400)

    sheets_html = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        table = f'<h3 style="margin:10px 0 4px;font-size:13px">{ws.title}</h3>'
        table += '<table class="data-table"><thead><tr>'
        for cell in rows[0]:
            table += f'<th>{cell if cell is not None else ""}</th>'
        table += '</tr></thead><tbody>'
        for row in rows[1:200]:
            table += '<tr>'
            for cell in row:
                val = f'{cell:,}' if isinstance(cell, (int, float)) and not isinstance(cell, bool) else (cell if cell is not None else '')
                table += f'<td>{val}</td>'
            table += '</tr>'
        table += '</tbody></table>'
        sheets_html.append(table)
    wb.close()

    html = f'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{att.filename}</title>
<style>
body {{ font-family:'Malgun Gothic',sans-serif; font-size:12px; padding:12px; background:#f5f5f5; }}
table {{ width:100%; border-collapse:collapse; margin-bottom:16px; background:#fff; }}
th {{ background:#666; color:#fff; padding:5px 8px; border:1px solid #555; text-align:center; white-space:nowrap; }}
td {{ padding:4px 8px; border:1px solid #ddd; }}
tr:nth-child(even) td {{ background:#fafafa; }}
h3 {{ color:#e8720c; }}
</style></head><body>
<h2 style="font-size:14px;margin-bottom:8px">{att.filename}</h2>
{"".join(sheets_html)}
</body></html>'''
    return HttpResponse(html)


@csrf_exempt
def sms_webhook(request):
    """
    갤럭시 SMS Forwarder 앱에서 POST로 오는 문자 수신.
    앱 설정: URL = https://도메인/webhook/sms/
    Body format (JSON): {"from":"010-xxxx", "text":"...", "sentStamp":1234567890}
    """
    if request.method != 'POST':
        return HttpResponse('OK')

    from django.utils import timezone
    import datetime

    try:
        body = request.body
        try:
            body_str = body.decode('utf-8')
        except UnicodeDecodeError:
            body_str = body.decode('euc-kr', errors='replace')
        data = json.loads(body_str)
        logger.info('SMS 웹훅 수신 데이터: %s', body_str[:500])
        from_name = data.get('from', '')
        from_number = data.get('from_number') or data.get('number', '')
        # formatted-msg에서 전화번호 추출 시도
        formatted = data.get('detail') or data.get('formatted-msg', '')
        if formatted:
            logger.info('SMS formatted-msg: %s', formatted[:300])
            fm = _re.search(r'(01\d[\d\-]{7,})', formatted)
            if fm and not from_number:
                from_number = fm.group(1).replace('-', '')
        # {number} 리터럴 제거 (Forward SMS 앱에서 변수 치환 실패 시)
        if from_number == '{number}':
            from_number = ''
        from_name = _re.sub(r'\(\{number\}\)', '', from_name).strip()
        # from_name에서 실제 전화번호 추출: "김은경선생님 (01032278210)" → 번호 분리
        name_phone_match = _re.search(r'\(?(01\d[\d\-]{7,})\)?', from_name)
        if name_phone_match and not from_number:
            from_number = name_phone_match.group(1).replace('-', '')
            # 이름에서 번호 부분 제거: "김은경선생님 (010...)" → "김은경선생님"
            from_name = from_name[:name_phone_match.start()].strip().rstrip('(').strip()
        # 이름과 번호 모두 있으면 "이름(번호)" 형식
        if from_name and from_number and from_number not in from_name:
            sender = f'{from_name}({from_number})'
        else:
            sender = from_name or from_number
        content = data.get('text') or data.get('message', '')
        ts = data.get('sentStamp') or data.get('timestamp')
        received_at = None
        if ts:
            ts_str = str(ts).strip()
            # ISO 8601 형식 (Forward SMS 앱의 {time})
            if 'T' in ts_str or '-' in ts_str[:10]:
                try:
                    from django.utils.dateparse import parse_datetime
                    parsed = parse_datetime(ts_str)
                    if parsed:
                        received_at = parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
                except (ValueError, TypeError):
                    pass
            # 밀리초 timestamp
            if not received_at:
                try:
                    received_at = timezone.make_aware(
                        datetime.datetime.fromtimestamp(int(ts_str) / 1000)
                    )
                except (ValueError, TypeError, OSError):
                    pass
        if not received_at:
            received_at = timezone.now()

        # 전화번호 추출 (from_number 또는 sender에서)
        phone_digits = from_number.replace('-', '') if from_number else ''
        if not phone_digits:
            pm = _re.search(r'(\d[\d\-]{8,})', sender)
            if pm:
                phone_digits = pm.group(1).replace('-', '')

        if content:
            InboxMessage.objects.create(
                source=InboxMessage.Source.SMS,
                sender=sender,
                content=content,
                received_at=received_at,
                phone=phone_digits,
            )
    except Exception:
        logger.exception('SMS 웹훅 처리 오류')

    return HttpResponse('OK')


@role_required('admin')
def sms_import_xml(request):
    """SMS Backup & Restore 앱의 XML 파일에서 문자 일괄 가져오기"""
    if request.method != 'POST' or not request.FILES.get('xml_file'):
        return render(request, 'orders/sms_import.html', {'result': None})

    from django.utils import timezone
    import datetime
    import xml.etree.ElementTree as ET

    xml_file = request.FILES['xml_file']
    if not xml_file.name.endswith('.xml'):
        messages.error(request, '.xml 파일만 지원합니다.')
        return render(request, 'orders/sms_import.html', {'result': None})

    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except ET.ParseError as e:
        messages.error(request, f'XML 파싱 오류: {e}')
        return render(request, 'orders/sms_import.html', {'result': None})

    # 기존 SMS 중복 방지: (sender, received_at) 조합
    existing = set(
        InboxMessage.objects.filter(source='sms')
        .values_list('sender', 'received_at')
    )

    new_count = 0
    skip_count = 0
    total = 0

    for sms in root.iter('sms'):
        total += 1
        address = sms.get('address', '').strip()
        body = sms.get('body', '').strip()
        date_ms = sms.get('date', '')
        sms_type = sms.get('type', '1')  # 1=수신, 2=발신
        contact_name = sms.get('contact_name', '').strip()

        if not body:
            skip_count += 1
            continue

        # timestamp 파싱
        try:
            received_at = timezone.make_aware(
                datetime.datetime.fromtimestamp(int(date_ms) / 1000)
            )
        except (ValueError, TypeError, OSError):
            received_at = timezone.now()

        # 발신자 표시: 연락처명이 있으면 "이름(번호)", 없으면 번호만
        if contact_name and contact_name != '(Unknown)':
            sender = f'{contact_name}({address})'
        else:
            sender = address

        # 발신 문자는 subject에 표시
        subject = '[발신]' if sms_type == '2' else ''

        # 중복 체크
        if (sender, received_at) in existing:
            skip_count += 1
            continue

        InboxMessage.objects.create(
            source=InboxMessage.Source.SMS,
            sender=sender,
            subject=subject,
            content=body,
            received_at=received_at,
            is_processed=True,  # 과거 문자는 처리완료 상태로
            is_read=True,
        )
        existing.add((sender, received_at))
        new_count += 1

    result = {
        'total': total,
        'new_count': new_count,
        'skip_count': skip_count,
    }
    messages.success(request, f'총 {total}건 중 {new_count}건 가져옴 (중복/빈내용 {skip_count}건 건너뜀)')
    return render(request, 'orders/sms_import.html', {'result': result})


@role_required('admin')
def sms_desk(request):
    """Google Messages + 주문 입력 분할 화면"""
    agencies = User.objects.filter(role='agency', is_active=True).order_by('name')
    agencies_json = json.dumps([{
        'id': a.pk, 'name': a.name,
    } for a in agencies], ensure_ascii=False)

    teachers = (
        User.objects
        .filter(role='teacher', is_active=True)
        .select_related('agency', 'delivery_address')
        .order_by('agency__name', 'name')
    )
    teachers_json = json.dumps([{
        'id': t.pk,
        'name': t.name,
        'phone': t.phone or '',
        'agency_id': t.agency_id,
        'delivery_id': t.delivery_address_id,
        'delivery_name': t.delivery_address.name if t.delivery_address else '',
        'delivery_address': t.delivery_address.address if t.delivery_address else '',
        'delivery_phone': t.delivery_address.phone if t.delivery_address else '',
        'has_delivery': bool(t.delivery_address),
    } for t in teachers], ensure_ascii=False)

    books = Book.objects.filter(is_active=True).select_related('publisher')
    series_list = sorted(set(b.series for b in books if b.series))
    if any(not b.series for b in books):
        series_list.append('기타')
    books_json = json.dumps([{
        'id': b.id,
        'series': b.series or '기타',
        'name': b.name,
        'publisher': b.publisher.name,
        'unit_price': math.floor(b.list_price * float(b.publisher.supply_rate) / 100),
    } for b in books], ensure_ascii=False)

    if request.method == 'POST':
        agency_id = request.POST.get('agency_id', '').strip()
        teacher_id = request.POST.get('teacher_id', '').strip()
        new_teacher_name = request.POST.get('new_teacher_name', '').strip()
        new_teacher_phone = request.POST.get('new_teacher_phone', '').strip()
        delivery_school = request.POST.get('delivery_school', '').strip()
        delivery_address = request.POST.get('delivery_address', '').strip()
        delivery_phone = request.POST.get('delivery_phone', '').strip()

        try:
            agency = User.objects.get(pk=agency_id, role='agency', is_active=True)
        except (User.DoesNotExist, ValueError):
            messages.error(request, '업체를 선택해 주세요.')
            return redirect('sms_desk')

        if teacher_id:
            try:
                teacher = User.objects.select_related('delivery_address').get(
                    pk=teacher_id, role='teacher', is_active=True
                )
            except (User.DoesNotExist, ValueError):
                messages.error(request, '선생님을 선택해 주세요.')
                return redirect('sms_desk')
        elif new_teacher_name:
            login_id = f'a_{new_teacher_phone or "nophone"}_{agency.pk}'
            if User.objects.filter(login_id=login_id).exists():
                teacher = User.objects.get(login_id=login_id)
            else:
                teacher = User(
                    login_id=login_id, role='teacher',
                    name=new_teacher_name, phone=new_teacher_phone,
                    agency=agency, must_change_password=False,
                )
                teacher.set_unusable_password()
                teacher.save()
        else:
            messages.error(request, '선생님을 선택하거나 새로 입력해 주세요.')
            return redirect('sms_desk')

        if delivery_school:
            delivery, created = DeliveryAddress.objects.get_or_create(
                agency=agency, name=delivery_school,
                defaults={'address': delivery_address, 'phone': delivery_phone},
            )
            if not created and delivery_address:
                delivery.address = delivery_address
                delivery.phone = delivery_phone
                delivery.save(update_fields=['address', 'phone'])
            teacher.delivery_address = delivery
            teacher.save(update_fields=['delivery_address'])
        elif not teacher.delivery_address:
            messages.error(request, '배송지를 입력해 주세요.')
            return redirect('sms_desk')

        items = []
        i = 0
        while f'book_{i}' in request.POST or f'custom_name_{i}' in request.POST:
            book_id = request.POST.get(f'book_{i}', '').strip()
            custom_name = request.POST.get(f'custom_name_{i}', '').strip()
            custom_price = request.POST.get(f'custom_price_{i}', '').strip()
            qty_str = request.POST.get(f'qty_{i}', '').strip()
            if book_id and qty_str:
                try:
                    qty = int(qty_str)
                    if qty > 0:
                        items.append({'book_id': int(book_id), 'qty': qty})
                except (ValueError, TypeError):
                    pass
            elif custom_name and qty_str:
                try:
                    qty = int(qty_str)
                    price = int(custom_price) if custom_price else 0
                    if qty > 0:
                        items.append({'custom_name': custom_name, 'custom_price': price, 'qty': qty})
                except (ValueError, TypeError):
                    pass
            i += 1

        if not items:
            messages.error(request, '주문할 교재를 1권 이상 선택하세요.')
        else:
            order = Order.objects.create(
                order_no=Order.generate_order_no(),
                agency=agency,
                teacher=teacher,
                delivery=teacher.delivery_address,
                memo=request.POST.get('memo', ''),
                source=Order.Source.ADMIN,
            )
            for item in items:
                if 'book_id' in item:
                    try:
                        book = Book.objects.get(id=item['book_id'], is_active=True)
                        OrderItem(order=order, book=book, quantity=item['qty']).save()
                    except Book.DoesNotExist:
                        pass
                else:
                    OrderItem(order=order, custom_book_name=item['custom_name'],
                              unit_price=item['custom_price'], quantity=item['qty']).save()
            messages.success(request, f'[{teacher.name}] 주문 완료. 주문번호: {order.order_no}')
            return redirect('sms_desk')

    return render(request, 'orders/sms_desk.html', {
        'agencies_json': agencies_json,
        'teachers_json': teachers_json,
        'series_list': series_list,
        'books_json': books_json,
    })


@role_required('admin')
def send_sms_ajax(request):
    """알리고를 통한 SMS 발송 (AJAX) — 발송 내역도 InboxMessage에 저장"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    receiver = request.POST.get('receiver', '').strip()
    message = request.POST.get('message', '').strip()
    if not receiver or not message:
        return JsonResponse({'error': '수신번호와 메시지를 입력하세요.'})
    ok = send_sms(receiver, message)
    if ok:
        from django.utils import timezone
        InboxMessage.objects.create(
            source=InboxMessage.Source.SMS,
            sender=receiver,
            subject='[발신]',
            content=message,
            received_at=timezone.now(),
            is_processed=True,
            is_read=True,
            phone=receiver.replace('-', ''),
        )
        return JsonResponse({'success': True, 'message': '발송 완료'})
    detail = getattr(send_sms, '_last_error', '알리고 설정을 확인하세요.')
    return JsonResponse({'error': f'발송 실패: {detail}'})


@role_required('admin')
def parse_order_excel(request):
    """엑셀 파일을 파싱하여 교재명·수량을 매칭한 JSON 반환"""
    from openpyxl import load_workbook

    if request.method != 'POST' or not request.FILES.get('file'):
        return HttpResponse(json.dumps({'error': '파일이 없습니다.'}),
                            content_type='application/json', status=400)

    file = request.FILES['file']
    if not file.name.endswith(('.xlsx', '.xls')):
        return HttpResponse(json.dumps({'error': '.xlsx 파일만 지원합니다.'}),
                            content_type='application/json', status=400)

    try:
        import re
        wb = load_workbook(file, read_only=True, data_only=True)
        ws = wb.active

        books = Book.objects.filter(is_active=True).select_related('publisher')
        book_map = {}
        for b in books:
            book_map[b.name.strip()] = {
                'id': b.id,
                'series': b.series or '기타',
                'name': b.name,
                'publisher': b.publisher.name,
                'unit_price': math.floor(b.list_price * float(b.publisher.supply_rate) / 100),
            }

        def clean_book_name(name):
            name = re.sub(r'^[^)]+\)\s*', '', name)
            return name.strip()

        def normalize(text):
            t = text.strip()
            t = re.sub(r'[\s\-_·•:：/\\&+<>()（）【】\[\]「」『』]', '', t)
            return t.lower()

        def try_match(name):
            if name in book_map:
                return book_map[name]
            cleaned = clean_book_name(name)
            if cleaned != name and cleaned in book_map:
                return book_map[cleaned]
            norm_name = normalize(cleaned)
            for bname, binfo in book_map.items():
                if normalize(bname) == norm_name:
                    return binfo
            best = None
            best_ratio = 0
            for bname, binfo in book_map.items():
                norm_b = normalize(bname)
                shorter = min(len(norm_name), len(norm_b))
                longer = max(len(norm_name), len(norm_b))
                if shorter < 3 or longer == 0:
                    continue
                ratio = shorter / longer
                if ratio < 0.5:
                    continue
                if norm_name in norm_b or norm_b in norm_name:
                    if ratio > best_ratio:
                        best = binfo
                        best_ratio = ratio
            return best

        def is_skip_row(text):
            t = text.strip()
            if not t:
                return True
            if re.match(r'^[●•◆■□▶▷※★☆\-\*]?\s*(출판사|샘플|합계|소계|총합계)', t):
                return True
            if re.match(r'^\d{2,3}[-.\s]?\d{3,4}[-.\s]?\d{4}$', t):
                return True
            if re.match(r'^[가-힣]+\s*(시|도|군|구|읍|면|로|길|동|번지)', t):
                return True
            return False

        def parse_qty(val):
            if val is None:
                return 0
            if isinstance(val, (int, float)):
                return max(0, int(val))
            s = str(val).strip().replace(',', '')
            try:
                return max(0, int(float(s)))
            except (ValueError, TypeError):
                return 0

        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return HttpResponse(json.dumps({'error': '빈 파일입니다.'}),
                                content_type='application/json', status=400)

        header = rows[0]
        name_col = qty_col = None
        for idx, cell in enumerate(header):
            if cell is None:
                continue
            h = str(cell).strip().lower()
            if name_col is None and any(k in h for k in ['교재', '도서', '상품', '품명', '제목', 'book', 'title', 'name']):
                name_col = idx
            if qty_col is None and any(k in h for k in ['수량', '부수', '권수', 'qty', 'quantity', '주문수량']):
                qty_col = idx

        if name_col is None:
            for idx, cell in enumerate(header):
                if cell and str(cell).strip():
                    name_col = idx
                    break

        if name_col is None:
            return HttpResponse(json.dumps({'error': '교재명 열을 찾을 수 없습니다.'}),
                                content_type='application/json', status=400)

        results = []
        for row in rows[1:]:
            if name_col >= len(row):
                continue
            raw_name = row[name_col]
            if raw_name is None:
                continue
            name = str(raw_name).strip()
            if not name or is_skip_row(name):
                continue
            qty = parse_qty(row[qty_col]) if qty_col is not None and qty_col < len(row) else 1
            if qty <= 0:
                qty = 1

            matched = try_match(name)
            if matched:
                results.append({
                    'book_id': matched['id'],
                    'series': matched['series'],
                    'name': matched['name'],
                    'publisher': matched['publisher'],
                    'unit_price': matched['unit_price'],
                    'qty': qty,
                    'matched': True,
                    'original_name': name,
                })
            else:
                results.append({
                    'book_id': None,
                    'name': name,
                    'qty': qty,
                    'matched': False,
                    'original_name': name,
                })

        return HttpResponse(
            json.dumps({'items': results}, ensure_ascii=False),
            content_type='application/json'
        )
    except Exception as e:
        return HttpResponse(
            json.dumps({'error': f'파싱 오류: {str(e)}'}),
            content_type='application/json', status=400,
        )
