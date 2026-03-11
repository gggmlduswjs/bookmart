import json
import math

from django.contrib import messages
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User
from books.models import Book
from orders.models import (
    AuditLog, CallRecording, DeliveryAddress,
    Order, OrderItem, OrderStatusLog,
)

from ._helpers import _audit


# ── 통화녹음 → 주문 ─────────────────────────────────────────────────────────

@role_required('admin')
def call_order_upload(request):
    """통화녹음/텍스트 → 주문 파싱 (3가지 입력: 브라우저 녹음, 텍스트, 파일 업로드)"""
    from orders.call_order import transcribe_audio, parse_order_from_text

    if request.method == 'POST':
        input_mode = request.POST.get('input_mode', 'file')
        transcript = None

        if input_mode == 'text':
            transcript = request.POST.get('transcript_text', '').strip()
            if not transcript:
                messages.error(request, '통화 내용을 입력해주세요.')
                return redirect('call_order_upload')
        else:
            audio = request.FILES.get('audio')
            if not audio:
                messages.error(request, '녹음 파일을 선택해주세요.')
                return redirect('call_order_upload')
            transcript, err = transcribe_audio(audio)
            if err:
                messages.error(request, err)
                return redirect('call_order_upload')

        books = Book.objects.filter(is_active=True).select_related('publisher')
        book_list = [{
            'id': b.id,
            'series': b.series or '기타',
            'name': b.name,
            'publisher': b.publisher.name,
            'unit_price': math.floor(b.list_price * float(b.publisher.supply_rate) / 100),
        } for b in books]

        parsed, err = parse_order_from_text(transcript, book_list)
        if err:
            messages.error(request, err)
            return render(request, 'orders/call_order_upload.html', {
                'transcript': transcript,
            })

        request.session['call_order_data'] = {
            'transcript': transcript,
            'parsed': parsed,
        }
        return redirect('call_order_confirm')

    return render(request, 'orders/call_order_upload.html')


@role_required('admin')
def call_order_confirm(request):
    """파싱 결과 확인 후 주문 생성"""
    data = request.session.get('call_order_data')
    if not data:
        messages.error(request, '파싱 데이터가 없습니다. 다시 업로드해주세요.')
        return redirect('call_order_upload')

    transcript = data['transcript']
    parsed = data['parsed']

    book_ids = [item['book_id'] for item in parsed.get('items', []) if item.get('book_id')]
    books_map = {}
    if book_ids:
        for b in Book.objects.filter(id__in=book_ids, is_active=True).select_related('publisher'):
            books_map[b.id] = {
                'id': b.id,
                'name': b.name,
                'publisher': b.publisher.name,
                'series': b.series or '기타',
                'unit_price': math.floor(b.list_price * float(b.publisher.supply_rate) / 100),
            }

    for item in parsed.get('items', []):
        bid = item.get('book_id')
        if bid and bid in books_map:
            item['book_info'] = books_map[bid]
        else:
            item['book_info'] = None

    agencies = User.objects.filter(role='agency', is_active=True).order_by('name')
    agencies_json = json.dumps([{'id': a.pk, 'name': a.name} for a in agencies], ensure_ascii=False)

    teachers = (
        User.objects.filter(role='teacher', is_active=True)
        .select_related('agency', 'delivery_address')
        .order_by('agency__name', 'name')
    )
    teachers_json = json.dumps([{
        'id': t.pk, 'name': t.name, 'phone': t.phone or '',
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
        'id': b.id, 'series': b.series or '기타', 'name': b.name,
        'publisher': b.publisher.name,
        'unit_price': math.floor(b.list_price * float(b.publisher.supply_rate) / 100),
    } for b in books], ensure_ascii=False)

    matched_teacher_id = ''
    teacher_name = parsed.get('teacher_name', '')
    teacher_phone = parsed.get('phone', '')
    if teacher_name:
        teacher_match = User.objects.filter(
            role='teacher', is_active=True, name__icontains=teacher_name
        ).first()
        if teacher_match:
            matched_teacher_id = str(teacher_match.pk)

    prefill_rows = json.dumps([{
        'series': item.get('book_info', {}).get('series', '') if item.get('book_info') else '',
        'book_id': str(item['book_id']) if item.get('book_id') and item.get('book_info') else '',
        'qty': item.get('qty', 1),
        'unit_price': item.get('book_info', {}).get('unit_price', 0) if item.get('book_info') else 0,
        'is_custom': not item.get('book_info'),
        'custom_name': item.get('name', ''),
        'confidence': item.get('confidence', 'high'),
    } for item in parsed.get('items', [])], ensure_ascii=False)

    if request.method == 'POST':
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
            return redirect('call_order_confirm')

        if teacher_id:
            try:
                teacher = User.objects.select_related('delivery_address').get(
                    pk=teacher_id, role='teacher', is_active=True
                )
            except (User.DoesNotExist, ValueError):
                messages.error(request, '선생님을 선택해 주세요.')
                return redirect('call_order_confirm')
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
            return redirect('call_order_confirm')

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
            return redirect('call_order_confirm')

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
            messages.error(request, '주문 품목이 1건 이상 있어야 합니다.')
            return redirect('call_order_confirm')

        order = Order.objects.create(
            order_no=Order.generate_order_no(),
            agency=agency,
            teacher=teacher,
            delivery=teacher.delivery_address,
            memo=(request.POST.get('memo', '') + '\n[통화녹음 주문]').strip(),
            source=Order.Source.CALL,
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
            changed_by=request.user, memo='통화녹음에서 주문 생성',
        )
        _audit(request, AuditLog.Action.ORDER_CREATE, order, f'[통화녹음] 주문 {order.order_no} 생성')

        recording_id = data.get('recording_id')
        if recording_id:
            CallRecording.objects.filter(pk=recording_id).update(
                order=order, status=CallRecording.Status.ORDERED,
            )

        request.session.pop('call_order_data', None)
        messages.success(request, f'통화 주문 등록 완료! 주문번호: {order.order_no}')
        return redirect('order_detail', pk=order.pk)

    return render(request, 'orders/call_order_confirm.html', {
        'transcript': transcript,
        'parsed': parsed,
        'parsed_json': json.dumps(parsed, ensure_ascii=False),
        'agencies_json': agencies_json,
        'teachers_json': teachers_json,
        'series_list': series_list,
        'books_json': books_json,
        'prefill_rows': prefill_rows,
        'matched_teacher_id': matched_teacher_id,
        'teacher_name': teacher_name,
        'teacher_phone': teacher_phone,
        'school_name': parsed.get('school_name', ''),
        'memo': parsed.get('memo', ''),
    })


# ── 통화 녹음 수신함 ─────────────────────────────────────────────────────────

@role_required('admin')
def call_inbox(request):
    """통화 수신함 → 통합 수신함의 통화 탭으로 리다이렉트"""
    status = request.GET.get('status', '')
    url = '/inbox/?tab=call'
    if status:
        url += f'&call_status={status}'
    return redirect(url)


@role_required('admin')
def call_recording_process(request, pk):
    """개별 녹음 처리 - 파싱 결과 확인 후 주문 생성"""
    rec = get_object_or_404(CallRecording, pk=pk)

    if rec.status == CallRecording.Status.PENDING:
        from orders.call_order import transcribe_audio, parse_order_from_text

        rec.status = CallRecording.Status.PROCESSING
        rec.save(update_fields=['status'])

        if not rec.transcript:
            rec.audio_file.open('rb')
            transcript, err = transcribe_audio(rec.audio_file)
            rec.audio_file.close()
            if err:
                rec.status = CallRecording.Status.FAILED
                rec.error_msg = err[:300]
                rec.save(update_fields=['status', 'error_msg'])
                messages.error(request, f'음성 변환 실패: {err}')
                return redirect('call_inbox')
            rec.transcript = transcript
            rec.save(update_fields=['transcript'])

        books = Book.objects.filter(is_active=True).select_related('publisher')
        book_list = [{
            'id': b.id, 'series': b.series or '기타', 'name': b.name,
            'publisher': b.publisher.name,
            'unit_price': math.floor(b.list_price * float(b.publisher.supply_rate) / 100),
        } for b in books]

        parsed, err = parse_order_from_text(rec.transcript, book_list)
        if err:
            rec.status = CallRecording.Status.FAILED
            rec.error_msg = err[:300]
            rec.save(update_fields=['status', 'error_msg'])
            messages.error(request, f'주문 파싱 실패: {err}')
            return redirect('call_inbox')

        rec.parsed_data = parsed
        rec.status = CallRecording.Status.PARSED
        rec.save(update_fields=['parsed_data', 'status'])

    if rec.status not in (CallRecording.Status.PARSED, CallRecording.Status.ORDERED):
        messages.error(request, f'이 녹음은 처리할 수 없는 상태입니다: {rec.get_status_display()}')
        return redirect('call_inbox')

    request.session['call_order_data'] = {
        'transcript': rec.transcript,
        'parsed': rec.parsed_data,
        'recording_id': rec.pk,
    }
    return redirect('call_order_confirm')


@role_required('admin')
def call_recording_skip(request, pk):
    """녹음 건너뛰기"""
    rec = get_object_or_404(CallRecording, pk=pk)
    rec.status = CallRecording.Status.SKIPPED
    rec.save(update_fields=['status'])
    messages.success(request, '건너뛰었습니다.')
    return redirect('call_inbox')


@role_required('admin')
def call_recording_retry(request, pk):
    """실패한 녹음 재시도"""
    rec = get_object_or_404(CallRecording, pk=pk)
    rec.status = CallRecording.Status.PENDING
    rec.error_msg = ''
    rec.save(update_fields=['status', 'error_msg'])
    messages.success(request, '재처리 대기 상태로 변경했습니다.')
    return redirect('call_recording_process', pk=rec.pk)


@role_required('admin')
def call_sync_drive(request):
    """Google Drive 수동 동기화 트리거"""
    from orders.management.commands.sync_call_recordings import sync_from_drive, process_pending_recordings
    try:
        new = sync_from_drive()
        processed = process_pending_recordings()
        messages.success(request, f'동기화 완료: 새 녹음 {new}건, 파싱 {processed}건')
    except Exception as e:
        messages.error(request, f'동기화 오류: {str(e)}')
    return redirect('call_inbox')


@csrf_exempt
@require_POST
def call_recording_webhook(request):
    """외부에서 녹음 파일을 전송하는 웹훅 엔드포인트

    인증: Authorization: Bearer <CALL_RECORDING_API_TOKEN>
    요청: multipart/form-data
      - audio: 녹음 파일 (필수)
      - caller_phone: 발신번호 (선택)
      - recorded_at: 녹음일시 ISO format (선택)
      - auto_process: "true"이면 즉시 파싱 (선택)
    """
    from django.conf import settings as conf

    token = conf.CALL_RECORDING_API_TOKEN
    if not token:
        return JsonResponse({'error': 'webhook not configured'}, status=503)

    auth = request.headers.get('Authorization', '')
    if auth != f'Bearer {token}':
        return JsonResponse({'error': 'unauthorized'}, status=401)

    audio = request.FILES.get('audio')
    if not audio:
        return JsonResponse({'error': 'audio file required'}, status=400)

    rec = CallRecording(
        file_name=audio.name,
        caller_phone=request.POST.get('caller_phone', ''),
        source='webhook',
    )
    rec.audio_file.save(audio.name, audio, save=False)

    recorded_at = request.POST.get('recorded_at', '')
    if recorded_at:
        try:
            from datetime import datetime as dt
            rec.recorded_at = dt.fromisoformat(recorded_at)
        except (ValueError, TypeError):
            pass

    rec.save()

    if request.POST.get('auto_process') == 'true':
        from orders.management.commands.sync_call_recordings import process_pending_recordings
        process_pending_recordings()
        rec.refresh_from_db()

    return JsonResponse({
        'ok': True,
        'id': rec.pk,
        'status': rec.status,
    })


# ── Google Drive OAuth (웹 기반) ────────────────────────────────────────────

@role_required('admin')
def gdrive_auth_start(request):
    """Google Drive 연동 시작 - Google 로그인 페이지로 리다이렉트"""
    from google_auth_oauthlib.flow import Flow
    from django.conf import settings as conf
    from pathlib import Path

    client_json = conf.GOOGLE_OAUTH_CLIENT_JSON
    if not client_json or not Path(client_json).exists():
        messages.error(request, 'Google OAuth 클라이언트 JSON 파일이 없습니다.')
        return redirect('call_inbox')

    scheme = 'https' if request.is_secure() else 'http'
    redirect_uri = f'{scheme}://{request.get_host()}/orders/call/gdrive-callback/'

    flow = Flow.from_client_secrets_file(
        client_json,
        scopes=['https://www.googleapis.com/auth/drive.readonly'],
        redirect_uri=redirect_uri,
    )

    auth_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent',
    )

    request.session['gdrive_oauth_state'] = state
    request.session['gdrive_redirect_uri'] = redirect_uri
    request.session['gdrive_code_verifier'] = flow.code_verifier
    return redirect(auth_url)


@role_required('admin')
def gdrive_auth_callback(request):
    """Google OAuth 콜백 - 토큰 저장"""
    from google_auth_oauthlib.flow import Flow
    from django.conf import settings as conf
    from pathlib import Path

    client_json = conf.GOOGLE_OAUTH_CLIENT_JSON
    state = request.session.get('gdrive_oauth_state')
    redirect_uri = request.session.get('gdrive_redirect_uri')

    if not state or not redirect_uri:
        messages.error(request, 'OAuth 세션이 만료되었습니다. 다시 시도해주세요.')
        return redirect('call_inbox')

    flow = Flow.from_client_secrets_file(
        client_json,
        scopes=['https://www.googleapis.com/auth/drive.readonly'],
        state=state,
        redirect_uri=redirect_uri,
    )
    flow.code_verifier = request.session.get('gdrive_code_verifier')

    authorization_response = request.build_absolute_uri()
    if authorization_response.startswith('http://') and 'bookmart' in authorization_response:
        authorization_response = authorization_response.replace('http://', 'https://', 1)

    try:
        flow.fetch_token(authorization_response=authorization_response)
    except Exception as e:
        messages.error(request, f'Google 인증 실패: {str(e)}')
        messages.error(request, 'Google Cloud Console에서 리디렉트 URI를 확인해주세요: ' + redirect_uri)
        return redirect('call_inbox')

    creds = flow.credentials
    token_path = Path(conf.BASE_DIR) / 'gdrive_token.json'
    token_data = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': list(creds.scopes) if creds.scopes else [],
    }
    token_path.write_text(json.dumps(token_data, indent=2))

    request.session.pop('gdrive_oauth_state', None)
    request.session.pop('gdrive_redirect_uri', None)
    request.session.pop('gdrive_code_verifier', None)

    messages.success(request, 'Google Drive 연동 완료! 이제 통화 녹음이 자동으로 동기화됩니다.')
    return redirect('call_inbox')
