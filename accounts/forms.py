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
        widget=forms.TextInput(attrs={'autofocus': True, 'placeholder': '아이디'})
    )
    password = forms.CharField(
        label='비밀번호',
        widget=forms.PasswordInput(attrs={'placeholder': '비밀번호'})
    )


class CustomPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        label='현재 비밀번호',
        widget=forms.PasswordInput()
    )
    new_password1 = forms.CharField(
        label='새 비밀번호',
        widget=forms.PasswordInput()
    )
    new_password2 = forms.CharField(
        label='새 비밀번호 확인',
        widget=forms.PasswordInput()
    )


class AgencyForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['login_id', 'name', 'phone']
        labels = {'login_id': '아이디', 'name': '업체명', 'phone': '연락처'}


class TeacherForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['login_id', 'name', 'phone', 'delivery_address']
        labels = {
            'login_id': '아이디', 'name': '선생님 이름',
            'phone': '연락처', 'delivery_address': '담당 학교',
        }

    def __init__(self, agency, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from orders.models import DeliveryAddress
        self.fields['delivery_address'].queryset = DeliveryAddress.objects.filter(
            agency=agency, is_active=True
        )
        self.fields['delivery_address'].empty_label = '학교 선택'


class DeliveryAddressForm(forms.Form):
    name = forms.CharField(label='학교명')
    address = forms.CharField(label='주소', required=False)
    phone = forms.CharField(label='전화번호', required=False)


class IndividualRegisterForm(forms.Form):
    name = forms.CharField(label='이름', max_length=100)
    phone = forms.CharField(label='연락처', max_length=20)
    login_id = forms.CharField(label='아이디', max_length=50)
    password1 = forms.CharField(label='비밀번호', widget=forms.PasswordInput)
    password2 = forms.CharField(label='비밀번호 확인', widget=forms.PasswordInput)

    def clean_login_id(self):
        login_id = self.cleaned_data['login_id']
        if User.objects.filter(login_id=login_id).exists():
            raise forms.ValidationError('이미 사용 중인 아이디입니다.')
        return login_id

    def clean(self):
        cleaned_data = super().clean()
        pw1 = cleaned_data.get('password1')
        pw2 = cleaned_data.get('password2')
        if pw1 and pw2 and pw1 != pw2:
            self.add_error('password2', '비밀번호가 일치하지 않습니다.')
        if pw1 and len(pw1) < 4:
            self.add_error('password1', '비밀번호는 4자 이상이어야 합니다.')
        return cleaned_data
