from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from openpyxl import Workbook, load_workbook

from .decorators import role_required
from .forms import (LoginForm, CustomPasswordChangeForm, AgencyForm,
                    TeacherForm, DeliveryAddressForm, generate_temp_password)
from .models import User, AgencyInfo
from orders.models import DeliveryAddress


class CustomLoginView(LoginView):
    form_class = LoginForm
    template_name = 'auth/login.html'

    def get_success_url(self):
        return reverse_lazy('home')


class CustomPasswordChangeView(PasswordChangeView):
    form_class = CustomPasswordChangeForm
    template_name = 'auth/password_change.html'
    success_url = reverse_lazy('home')

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=['must_change_password'])
        messages.success(self.request, '비밀번호가 변경되었습니다.')
        return response


# ── 총판 전용 ─────────────────────────────────────────────────────────────────

@role_required('admin')
def agency_list(request):
    agencies = User.objects.filter(role='agency').order_by('name')
    return render(request, 'accounts/agency_list.html', {'agencies': agencies})


@role_required('admin')
def agency_create(request):
    if request.method == 'POST':
        form = AgencyForm(request.POST)
        if form.is_valid():
            temp_pw = generate_temp_password()
            agency = form.save(commit=False)
            agency.role = 'agency'
            agency.set_password(temp_pw)
            agency.must_change_password = True
            agency.save()
            return render(request, 'accounts/credential.html', {
                'title': '업체 계정 생성 완료',
                'login_id': agency.login_id,
                'password': temp_pw,
                'back_url': reverse('agency_list'),
            })
    else:
        form = AgencyForm()
    return render(request, 'accounts/agency_form.html', {'form': form, 'title': '업체 계정 추가'})


@role_required('admin')
def agency_toggle(request, pk):
    agency = get_object_or_404(User, pk=pk, role='agency')
    agency.is_active = not agency.is_active
    agency.save(update_fields=['is_active'])
    if not agency.is_active:
        agency.teachers.update(is_active=False)
    action = '활성화' if agency.is_active else '비활성화'
    messages.success(request, f'{agency.name} 계정이 {action}되었습니다.')
    return redirect('agency_list')


# ── 업체 전용 — 배송지(학교) ─────────────────────────────────────────────────

@role_required('agency')
def delivery_list(request):
    deliveries = DeliveryAddress.objects.filter(agency=request.user).order_by('name')
    return render(request, 'accounts/delivery_list.html', {'deliveries': deliveries})


@role_required('agency')
def delivery_create(request):
    if request.method == 'POST':
        form = DeliveryAddressForm(request.POST)
        if form.is_valid():
            DeliveryAddress.objects.create(
                agency=request.user,
                name=form.cleaned_data['name'],
                address=form.cleaned_data['address'],
                phone=form.cleaned_data['phone'],
            )
            messages.success(request, f"학교 '{form.cleaned_data['name']}'이 등록되었습니다.")
            return redirect('delivery_list')
    else:
        form = DeliveryAddressForm()
    return render(request, 'accounts/delivery_form.html', {'form': form, 'title': '학교 등록'})


# ── 업체 전용 — 선생님 ────────────────────────────────────────────────────────

@role_required('agency')
def teacher_list(request):
    teachers = User.objects.filter(
        role='teacher', agency=request.user
    ).select_related('delivery_address')
    return render(request, 'accounts/teacher_list.html', {'teachers': teachers})


@role_required('agency')
def teacher_create(request):
    if request.method == 'POST':
        form = TeacherForm(request.user, request.POST)
        if form.is_valid():
            temp_pw = generate_temp_password()
            teacher = form.save(commit=False)
            teacher.role = 'teacher'
            teacher.agency = request.user
            teacher.set_password(temp_pw)
            teacher.must_change_password = True
            teacher.save()
            return render(request, 'accounts/credential.html', {
                'title': '선생님 계정 등록 완료',
                'login_id': teacher.login_id,
                'password': temp_pw,
                'back_url': reverse('teacher_list'),
            })
    else:
        form = TeacherForm(request.user)
    return render(request, 'accounts/teacher_form.html', {'form': form, 'title': '선생님 계정 등록'})


@role_required('agency')
def teacher_reset_password(request, pk):
    teacher = get_object_or_404(User, pk=pk, role='teacher', agency=request.user)
    temp_pw = generate_temp_password()
    teacher.set_password(temp_pw)
    teacher.must_change_password = True
    teacher.save()
    return render(request, 'accounts/credential.html', {
        'title': f'{teacher.name} 비밀번호 초기화',
        'login_id': teacher.login_id,
        'password': temp_pw,
        'back_url': reverse('teacher_list'),
    })


@role_required('agency')
def teacher_toggle(request, pk):
    teacher = get_object_or_404(User, pk=pk, role='teacher', agency=request.user)
    teacher.is_active = not teacher.is_active
    teacher.save(update_fields=['is_active'])
    action = '활성화' if teacher.is_active else '비활성화'
    messages.success(request, f'{teacher.name} 계정이 {action}되었습니다.')
    return redirect('teacher_list')


# ── 업체 엑셀 일괄 등록 ───────────────────────────────────────────────────────

@role_required('admin')
def agency_import(request):
    if request.method == 'POST':
        file = request.FILES.get('file')
        if not file or not file.name.endswith('.xlsx'):
            messages.error(request, '.xlsx 파일만 업로드할 수 있습니다.')
            return redirect('agency_import')

        try:
            wb = load_workbook(file, read_only=True)
            ws = wb.active

            rows = list(ws.iter_rows(min_row=2, values_only=True))
            created_list = []
            skipped = 0

            for row in rows:
                if not row or len(row) < 7:
                    continue

                agency_name = str(row[0] or '').strip()
                login_id = str(row[1] or '').strip()
                password = str(row[2] or '').strip()
                rep_name = str(row[3] or '').strip()
                biz_no = str(row[4] or '').strip()
                phone = str(row[5] or '').strip()
                address = str(row[6] or '').strip()

                if not agency_name or not login_id:
                    continue

                if User.objects.filter(login_id=login_id).exists():
                    skipped += 1
                    continue

                if not password:
                    password = generate_temp_password()

                user = User(
                    login_id=login_id,
                    role='agency',
                    name=agency_name,
                    phone=phone,
                    must_change_password=True,
                )
                user.set_password(password)
                user.save()

                AgencyInfo.objects.create(
                    user=user,
                    rep_name=rep_name,
                    biz_no=biz_no,
                    address=address,
                )

                created_list.append({
                    'name': agency_name,
                    'login_id': login_id,
                    'password': password,
                })

            wb.close()

            if created_list:
                messages.success(
                    request,
                    f'업체 {len(created_list)}건 등록 완료'
                    + (f' (중복 {skipped}건 건너뜀)' if skipped else ''),
                )
            else:
                messages.warning(request, '등록된 업체가 없습니다. 데이터를 확인해주세요.')

            return render(request, 'accounts/agency_import.html', {
                'created_list': created_list,
            })

        except Exception as e:
            messages.error(request, f'파일 처리 중 오류가 발생했습니다: {e}')
            return redirect('agency_import')

    return render(request, 'accounts/agency_import.html')


@role_required('admin')
def agency_import_sample(request):
    wb = Workbook()
    ws = wb.active
    ws.title = '업체 일괄등록'

    headers = ['업체명', '아이디', '비밀번호', '대표자명', '사업자번호', '연락처', '주소']
    ws.append(headers)

    ws.append(['한빛서점', 'hanbit01', 'pass1234', '김대표', '123-45-67890', '010-1234-5678', '서울시 강남구 역삼동 123'])
    ws.append(['새롬북스', 'saerom01', 'pass5678', '이대표', '987-65-43210', '010-9876-5432', '부산시 해운대구 우동 456'])

    for col in range(1, 8):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = 18

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="agency_import_sample.xlsx"'
    wb.save(response)
    return response
