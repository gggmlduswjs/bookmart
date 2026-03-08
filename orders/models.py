import math
from django.conf import settings
from django.db import models
from django.utils import timezone


class DeliveryAddress(models.Model):
    agency = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='delivery_addresses', limit_choices_to={'role': 'agency'},
        verbose_name='소속 업체'
    )
    name = models.CharField(max_length=100, verbose_name='학교명')
    contact_name = models.CharField(max_length=50, blank=True, verbose_name='담당자')
    phone = models.CharField(max_length=20, blank=True, verbose_name='전화')
    mobile = models.CharField(max_length=20, blank=True, verbose_name='휴대폰')
    fax = models.CharField(max_length=20, blank=True, verbose_name='팩스')
    address = models.CharField(max_length=255, blank=True, verbose_name='주소')
    is_active = models.BooleanField(default=True, verbose_name='활성')

    class Meta:
        db_table = 'delivery_addresses'
        verbose_name = '배송지(학교)'
        verbose_name_plural = '배송지 목록'
        ordering = ['agency', 'name']

    def __str__(self):
        return f'{self.name} ({self.agency.name})'


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '접수'
        SHIPPING = 'shipping', '발송중'
        DELIVERED = 'delivered', '발송완료'
        CANCELLED = 'cancelled', '취소'

    order_no = models.CharField(max_length=30, unique=True, verbose_name='주문번호')
    agency = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='agency_orders', limit_choices_to={'role': 'agency'},
        verbose_name='업체'
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='teacher_orders', limit_choices_to={'role': 'teacher'},
        verbose_name='선생님'
    )
    delivery = models.ForeignKey(
        DeliveryAddress, on_delete=models.PROTECT,
        related_name='orders', verbose_name='배송지'
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING,
        verbose_name='상태'
    )
    memo = models.TextField(blank=True, verbose_name='메모')
    tracking_no = models.CharField(max_length=50, blank=True, verbose_name='운송장번호')
    ordered_at = models.DateTimeField(default=timezone.now, verbose_name='주문일시')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'orders'
        verbose_name = '주문'
        verbose_name_plural = '주문 목록'
        ordering = ['-ordered_at']
        indexes = [
            models.Index(fields=['agency', 'ordered_at']),
            models.Index(fields=['status', 'ordered_at']),
        ]

    def __str__(self):
        return f'{self.order_no} ({self.delivery.name})'

    @property
    def total_amount(self):
        return sum(item.amount for item in self.items.all())

    @classmethod
    def generate_order_no(cls):
        now = timezone.now()
        prefix = now.strftime('%Y%m%d%H%M%S')
        last = cls.objects.filter(order_no__startswith=prefix).count()
        return f'{prefix}{last + 1:03d}'


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='items', verbose_name='주문'
    )
    book = models.ForeignKey(
        'books.Book', on_delete=models.PROTECT, related_name='order_items',
        verbose_name='교재'
    )
    quantity = models.IntegerField(verbose_name='수량')
    # 주문 시점 스냅샷
    list_price = models.IntegerField(verbose_name='정가(스냅샷)')
    supply_rate = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='공급률(스냅샷)')
    unit_price = models.IntegerField(verbose_name='단가')
    amount = models.IntegerField(verbose_name='금액')

    class Meta:
        db_table = 'order_items'
        verbose_name = '주문 상세'
        verbose_name_plural = '주문 상세'
        indexes = [
            models.Index(fields=['book']),
        ]

    def save(self, *args, **kwargs):
        # 단가·금액은 항상 서버에서 계산 (클라이언트 값 무시)
        self.list_price = self.book.list_price
        self.supply_rate = self.book.publisher.supply_rate
        self.unit_price = math.floor(self.list_price * float(self.supply_rate) / 100)
        self.amount = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.book.name} × {self.quantity}'


class Return(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'requested', '신청'
        CONFIRMED = 'confirmed', '확정'
        REJECTED = 'rejected', '거절'

    return_no = models.CharField(max_length=30, unique=True, verbose_name='반품번호')
    agency = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='agency_returns', limit_choices_to={'role': 'agency'},
        verbose_name='업체'
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='teacher_returns', limit_choices_to={'role': 'teacher'},
        verbose_name='선생님'
    )
    delivery = models.ForeignKey(
        DeliveryAddress, on_delete=models.PROTECT,
        related_name='returns', verbose_name='배송지'
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.REQUESTED,
        verbose_name='상태'
    )
    memo = models.TextField(blank=True, verbose_name='메모')
    requested_at = models.DateTimeField(default=timezone.now, verbose_name='신청일시')
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='확정일시')

    class Meta:
        db_table = 'returns'
        verbose_name = '반품'
        verbose_name_plural = '반품 목록'
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['agency', 'requested_at']),
        ]

    def __str__(self):
        return f'{self.return_no} ({self.delivery.name})'

    @classmethod
    def generate_return_no(cls):
        now = timezone.now()
        prefix = 'C' + now.strftime('%Y%m%d%H%M%S')
        last = cls.objects.filter(return_no__startswith=prefix).count()
        return f'{prefix}{last + 1:03d}'


class ReturnItem(models.Model):
    ret = models.ForeignKey(
        Return, on_delete=models.CASCADE, related_name='items', verbose_name='반품'
    )
    book = models.ForeignKey(
        'books.Book', on_delete=models.PROTECT, related_name='return_items',
        verbose_name='교재'
    )
    requested_qty = models.IntegerField(verbose_name='요청수량')
    confirmed_qty = models.IntegerField(null=True, blank=True, verbose_name='확정수량')
    list_price = models.IntegerField(verbose_name='정가(스냅샷)')
    supply_rate = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='공급률(스냅샷)')
    unit_price = models.IntegerField(verbose_name='단가')
    requested_amount = models.IntegerField(verbose_name='요청금액')
    confirmed_amount = models.IntegerField(null=True, blank=True, verbose_name='확정금액')
    adjusted_amount = models.IntegerField(default=0, verbose_name='조정금액')

    class Meta:
        db_table = 'return_items'
        verbose_name = '반품 상세'
        verbose_name_plural = '반품 상세'

    def save(self, *args, **kwargs):
        self.list_price = self.book.list_price
        self.supply_rate = self.book.publisher.supply_rate
        self.unit_price = math.floor(self.list_price * float(self.supply_rate) / 100)
        self.requested_amount = self.unit_price * self.requested_qty
        if self.confirmed_qty is not None:
            self.confirmed_amount = self.unit_price * self.confirmed_qty
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.book.name} 반품 × {self.requested_qty}'


class InboxMessage(models.Model):
    class Source(models.TextChoices):
        EMAIL = 'email', '이메일'
        SMS   = 'sms',   '문자'

    source       = models.CharField(max_length=10, choices=Source.choices, verbose_name='수신 채널')
    account_label= models.CharField(max_length=20, blank=True, verbose_name='계정')   # '007bm', '002bm'
    sender       = models.CharField(max_length=200, verbose_name='발신자')
    subject      = models.CharField(max_length=500, blank=True, verbose_name='제목')
    content      = models.TextField(verbose_name='내용')
    received_at  = models.DateTimeField(verbose_name='수신 시각')
    is_processed = models.BooleanField(default=False, verbose_name='처리 완료')
    order        = models.ForeignKey(
        'Order', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='inbox_messages', verbose_name='연결 주문'
    )
    # 이메일 중복 방지: account_label + IMAP UID
    imap_key     = models.CharField(max_length=100, null=True, blank=True,
                                    unique=True, verbose_name='IMAP 키')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inbox_messages'
        verbose_name = '수신 메시지'
        verbose_name_plural = '수신 메시지 목록'
        ordering = ['-received_at']

    def __str__(self):
        return f'[{self.get_source_display()}] {self.sender} ({self.received_at:%Y-%m-%d %H:%M})'

    @property
    def preview(self):
        return self.content[:80].replace('\n', ' ')


class InboxAttachment(models.Model):
    message = models.ForeignKey(
        InboxMessage, on_delete=models.CASCADE,
        related_name='attachments', verbose_name='수신 메시지'
    )
    file = models.FileField(upload_to='inbox_attachments/%Y/%m/', verbose_name='파일')
    filename = models.CharField(max_length=255, verbose_name='원본 파일명')
    content_type = models.CharField(max_length=100, blank=True, verbose_name='MIME 타입')
    size = models.IntegerField(default=0, verbose_name='파일 크기(bytes)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inbox_attachments'
        verbose_name = '수신 첨부파일'
        verbose_name_plural = '수신 첨부파일'

    def __str__(self):
        return self.filename

    @property
    def is_excel(self):
        ext = self.filename.lower().rsplit('.', 1)[-1] if '.' in self.filename else ''
        return ext in ('xls', 'xlsx')

    @property
    def extension(self):
        return self.filename.lower().rsplit('.', 1)[-1] if '.' in self.filename else ''


class Payment(models.Model):
    agency = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='payments', limit_choices_to={'role': 'agency'},
        verbose_name='업체'
    )
    amount = models.IntegerField(verbose_name='입금액')
    paid_at = models.DateField(verbose_name='입금일')
    memo = models.CharField(max_length=255, blank=True, verbose_name='비고')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments'
        verbose_name = '입금 내역'
        verbose_name_plural = '입금 내역'
        ordering = ['-paid_at']
        indexes = [
            models.Index(fields=['agency', 'paid_at']),
        ]

    def __str__(self):
        return f'{self.agency.name} {self.paid_at} {self.amount:,}원'
