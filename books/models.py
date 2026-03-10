from django.db import models


class Publisher(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='출판사명')
    supply_rate = models.DecimalField(
        max_digits=5, decimal_places=2, verbose_name='공급률(%)'
    )
    is_active = models.BooleanField(default=True, verbose_name='활성')

    class Meta:
        db_table = 'publishers'
        verbose_name = '출판사'
        verbose_name_plural = '출판사 목록'
        ordering = ['name']

    def __str__(self):
        return self.name


class Book(models.Model):
    publisher = models.ForeignKey(
        Publisher, on_delete=models.PROTECT,
        related_name='books', verbose_name='출판사'
    )
    series = models.CharField(max_length=100, blank=True, verbose_name='시리즈')
    name = models.CharField(max_length=255, verbose_name='교재명')
    list_price = models.IntegerField(verbose_name='정가(원)')
    is_returnable = models.BooleanField(default=True, verbose_name='반품 가능')
    is_active = models.BooleanField(default=True, verbose_name='주문 가능')
    sort_order = models.IntegerField(default=0, verbose_name='정렬순서')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        db_table = 'books'
        verbose_name = '교재'
        verbose_name_plural = '교재 목록'
        ordering = ['publisher', 'series', 'sort_order', 'name']

    def __str__(self):
        if self.series:
            return f'[{self.publisher.name}] {self.series} - {self.name}'
        return f'[{self.publisher.name}] {self.name}'

    @property
    def unit_price(self):
        """단가 = 정가 × 공급률 (원 단위, 내림)"""
        import math
        return math.floor(self.list_price * self.publisher.supply_rate / 100)
