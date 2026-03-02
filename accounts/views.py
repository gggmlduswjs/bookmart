from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy

from .decorators import role_required
from .forms import (LoginForm, CustomPasswordChangeForm, AgencyForm,
                    TeacherForm, DeliveryAddressForm, generate_temp_password)
from .models import User
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
                'back_url': 'agency_list',
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
                'back_url': 'teacher_list',
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
        'back_url': 'teacher_list',
    })


@role_required('agency')
def teacher_toggle(request, pk):
    teacher = get_object_or_404(User, pk=pk, role='teacher', agency=request.user)
    teacher.is_active = not teacher.is_active
    teacher.save(update_fields=['is_active'])
    action = '활성화' if teacher.is_active else '비활성화'
    messages.success(request, f'{teacher.name} 계정이 {action}되었습니다.')
    return redirect('teacher_list')
