from django import forms
from .models import Publisher, Book


class PublisherForm(forms.ModelForm):
    class Meta:
        model = Publisher
        fields = ['name', 'supply_rate', 'is_active']
        labels = {'name': '출판사명', 'supply_rate': '공급률(%)', 'is_active': '활성'}
        widgets = {
            'supply_rate': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'max': '100', 'style': 'width:80px'}),
        }


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = ['publisher', 'series', 'month', 'grade', 'name', 'list_price',
                  'agencies', 'is_returnable', 'is_active', 'sort_order']
        labels = {
            'publisher': '출판사', 'series': '시리즈', 'month': '월',
            'grade': '학년', 'name': '교재명',
            'list_price': '정가(원)', 'agencies': '취급 업체',
            'is_returnable': '반품 가능',
            'is_active': '주문 가능', 'sort_order': '정렬순서',
        }
        widgets = {
            'list_price': forms.NumberInput(attrs={'style': 'width:100px'}),
            'sort_order': forms.NumberInput(attrs={'style': 'width:60px'}),
            'month': forms.Select(attrs={'style': 'width:80px'}),
            'grade': forms.Select(attrs={'style': 'width:100px'}),
            'agencies': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from accounts.models import User
        self.fields['publisher'].queryset = Publisher.objects.filter(is_active=True)
        self.fields['series'].required = False
        self.fields['agencies'].queryset = User.objects.filter(role='agency', is_active=True).order_by('name')
        self.fields['agencies'].required = False
