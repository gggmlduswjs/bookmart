import random
import string
from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from .models import User


def generate_temp_password(length=8):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label='아이디',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autofocus': True, 'placeholder': '아이디'})
    )
    password = forms.CharField(
        label='비밀번호',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '비밀번호'})
    )


class CustomPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        label='현재 비밀번호',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    new_password1 = forms.CharField(
        label='새 비밀번호',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    new_password2 = forms.CharField(
        label='새 비밀번호 확인',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )


class AgencyForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['login_id', 'name', 'phone']
        labels = {'login_id': '아이디', 'name': '업체명', 'phone': '연락처'}
        widgets = {
            'login_id': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }


class TeacherForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['login_id', 'name', 'phone', 'delivery_address']
        labels = {
            'login_id': '아이디', 'name': '선생님 이름',
            'phone': '연락처', 'delivery_address': '담당 학교',
        }
        widgets = {
            'login_id': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'delivery_address': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, agency, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from orders.models import DeliveryAddress
        self.fields['delivery_address'].queryset = DeliveryAddress.objects.filter(
            agency=agency, is_active=True
        )
        self.fields['delivery_address'].empty_label = '학교 선택'


class DeliveryAddressForm(forms.Form):
    name = forms.CharField(
        label='학교명',
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    address = forms.CharField(
        label='주소', required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    phone = forms.CharField(
        label='전화번호', required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
