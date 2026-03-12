import math
from decimal import Decimal
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, IntegrityError
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
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

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

    class Source(models.TextChoices):
        SIMPLE  = 'simple',  '간편주문'
        INBOX   = 'inbox',   '수신함'
        ADMIN   = 'admin',   '관리자'
        CALL    = 'call',    '통화주문'
        IMPORT  = 'import',  '극동임포트'

    class Carrier(models.TextChoices):
        HANJIN = 'hanjin', '한진택배'
        DIRECT = 'direct', '직접배송'

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
    source = models.CharField(
        max_length=10, choices=Source.choices, default=Source.ADMIN,
        verbose_name='주문 경로'
    )
    memo = models.TextField(blank=True, verbose_name='메모')
    carrier = models.CharField(
        max_length=10, choices=Carrier.choices, blank=True, default='',
        verbose_name='배송방법'
    )
    tracking_no = models.CharField(max_length=50, blank=True, verbose_name='운송장번호')
    ordered_at = models.DateTimeField(default=timezone.now, verbose_name='주문일시')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일시')
    is_deleted = models.BooleanField(default=False, verbose_name='삭제여부')
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name='삭제일시')

    class Meta:
        db_table = 'orders'
        verbose_name = '주문'
        verbose_name_plural = '주문 목록'
        ordering = ['-ordered_at']
        indexes = [
            models.Index(fields=['agency', 'ordered_at']),
            models.Index(fields=['status', 'ordered_at']),
            models.Index(fields=['tracking_no']),
        ]

    def __str__(self):
        return f'{self.order_no} ({self.delivery.name})'

    @property
    def total_amount(self):
        return sum(item.amount for item in self.items.all())

    @classmethod
    def generate_order_no(cls):
        for _ in range(5):
            now = timezone.now()
            prefix = now.strftime('%Y%m%d%H%M%S')
            last = cls.objects.filter(order_no__startswith=prefix).count()
            order_no = f'{prefix}{last + 1:03d}'
            if not cls.objects.filter(order_no=order_no).exists():
                return order_no
        # fallback: 밀리초 포함
        return timezone.now().strftime('%Y%m%d%H%M%S%f')[:20]


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='items', verbose_name='주문'
    )
    book = models.ForeignKey(
        'books.Book', on_delete=models.PROTECT, related_name='order_items',
        verbose_name='교재', null=True, blank=True
    )
    custom_book_name = models.CharField(max_length=255, blank=True, default='', verbose_name='커스텀 교재명')
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

    @property
    def display_name(self):
        return self.book.name if self.book else self.custom_book_name

    @property
    def display_publisher(self):
        return self.book.publisher.name if self.book else ''

    @property
    def display_series(self):
        return self.book.series if self.book else ''

    def save(self, *args, **kwargs):
        if self.book:
            # 단가·금액은 항상 서버에서 계산 (클라이언트 값 무시)
            self.list_price = self.book.list_price
            override = getattr(self.order.agency, 'supply_rate_override', None)
            if override is not None:
                self.supply_rate = override
            else:
                self.supply_rate = self.book.publisher.supply_rate
            self.unit_price = math.floor(self.list_price * float(self.supply_rate) / 100)
        else:
            # 커스텀 교재: 클라이언트 값 사용
            self.list_price = self.unit_price
            self.supply_rate = Decimal('100.00')
        self.amount = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        name = self.book.name if self.book else self.custom_book_name
        return f'{name} × {self.quantity}'


class Shipment(models.Model):
    class Carrier(models.TextChoices):
        HANJIN   = 'hanjin',   '한진택배'
        DIRECT   = 'direct',   '직접배송'

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='shipments', verbose_name='주문'
    )
    carrier = models.CharField(
        max_length=10, choices=Carrier.choices, default=Carrier.HANJIN,
        verbose_name='택배사'
    )
    tracking_no = models.CharField(max_length=50, blank=True, verbose_name='운송장번호')
    memo = models.TextField(blank=True, verbose_name='배송메모')
    shipped_at = models.DateTimeField(null=True, blank=True, verbose_name='발송일시')
    delivered_at = models.DateTimeField(null=True, blank=True, verbose_name='배송완료일시')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'shipments'
        verbose_name = '배송'
        verbose_name_plural = '배송 목록'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order', 'created_at']),
            models.Index(fields=['tracking_no']),
        ]

    def __str__(self):
        return f'{self.order.order_no} — {self.get_carrier_display()} {self.tracking_no}'

    @property
    def tracking_url(self):
        if self.carrier == 'hanjin' and self.tracking_no:
            return f'https://www.hanjin.co.kr/kor/CMS/DeliveryMgr/WaybillSch.do?mCode=MN038&wblnumList={self.tracking_no}'
        return ''


class Return(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'requested', '신청'
        CONFIRMED = 'confirmed', '확정'
        REJECTED = 'rejected', '거절'

    class Reason(models.TextChoices):
        OVER_ORDER   = 'over_order',   '과주문'
        DAMAGED      = 'damaged',      '파손'
        WRONG_ITEM   = 'wrong_item',   '오배송'
        EXCHANGE     = 'exchange',     '교체'
        ETC          = 'etc',          '기타'

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
    reason = models.CharField(
        max_length=15, choices=Reason.choices, default=Reason.ETC,
        verbose_name='반품 사유'
    )
    memo = models.TextField(blank=True, verbose_name='메모')
    order = models.ForeignKey(
        Order, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='returns', verbose_name='원주문'
    )
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
        verbose_name='교재', null=True, blank=True
    )
    custom_book_name = models.CharField(max_length=255, blank=True, default='', verbose_name='커스텀 교재명')
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

    @property
    def display_name(self):
        return self.book.name if self.book else self.custom_book_name

    def save(self, *args, **kwargs):
        if self.book:
            self.list_price = self.book.list_price
            override = getattr(self.ret.agency, 'supply_rate_override', None)
            if override is not None:
                self.supply_rate = override
            else:
                self.supply_rate = self.book.publisher.supply_rate
            self.unit_price = math.floor(self.list_price * float(self.supply_rate) / 100)
        else:
            self.list_price = self.unit_price
            self.supply_rate = Decimal('100.00')
        self.requested_amount = self.unit_price * self.requested_qty
        if self.confirmed_qty is not None:
            self.confirmed_amount = self.unit_price * self.confirmed_qty
        super().save(*args, **kwargs)

    def __str__(self):
        name = self.book.name if self.book else self.custom_book_name
        return f'{name} 반품 × {self.requested_qty}'


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
    is_read      = models.BooleanField(default=False, verbose_name='읽음')
    # SMS 전화번호 (수신: 발신자 번호, 발신: 수신자 번호 — 대화 그룹핑용)
    phone        = models.CharField(max_length=20, blank=True, default='', db_index=True, verbose_name='전화번호')
    # 이메일 중복 방지: account_label + IMAP UID
    imap_key     = models.CharField(max_length=100, null=True, blank=True,
                                    unique=True, verbose_name='IMAP 키')
    # 이메일 Message-ID (답장 시 In-Reply-To 헤더에 사용)
    message_id   = models.CharField(max_length=500, blank=True, default='',
                                    verbose_name='Message-ID')
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
    def is_image(self):
        ext = self.filename.lower().rsplit('.', 1)[-1] if '.' in self.filename else ''
        return ext in ('jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp')

    @property
    def extension(self):
        return self.filename.lower().rsplit('.', 1)[-1] if '.' in self.filename else ''


class Payment(models.Model):
    agency = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='payments', limit_choices_to={'role': 'agency'},
        verbose_name='업체'
    )
    order = models.ForeignKey(
        Order, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='payments', verbose_name='연결 주문'
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


class LinkAccessLog(models.Model):
    agency = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='link_access_logs', limit_choices_to={'role': 'agency'},
        verbose_name='업체'
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='link_accesses',
        verbose_name='선생님'
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP')
    user_agent = models.CharField(max_length=500, blank=True, verbose_name='User-Agent')
    action = models.CharField(max_length=20, choices=[
        ('visit', '링크 접속'),
        ('register', '신규 등록'),
        ('order', '주문 완료'),
    ], verbose_name='행동')
    accessed_at = models.DateTimeField(auto_now_add=True, verbose_name='접속 시각')

    class Meta:
        db_table = 'link_access_logs'
        verbose_name = '간편링크 접속 이력'
        verbose_name_plural = '간편링크 접속 이력'
        ordering = ['-accessed_at']
        indexes = [
            models.Index(fields=['agency', 'accessed_at']),
        ]


# ── 감사 로그 (1-2) ──────────────────────────────────────────────────────────

class AuditLog(models.Model):
    """주요 액션에 대한 감사 로그"""
    class Action(models.TextChoices):
        ORDER_CREATE    = 'order_create',    '주문 생성'
        ORDER_EDIT      = 'order_edit',      '주문 수정'
        ORDER_DELETE    = 'order_delete',    '주문 삭제'
        ORDER_CANCEL    = 'order_cancel',    '주문 취소'
        ORDER_SHIP      = 'order_ship',      '발송 처리'
        ORDER_DELIVER   = 'order_deliver',   '배송완료'
        ORDER_RESTORE   = 'order_restore',   '주문 복구'
        RETURN_CREATE   = 'return_create',   '반품 신청'
        RETURN_CONFIRM  = 'return_confirm',  '반품 확정'
        RETURN_REJECT   = 'return_reject',   '반품 거절'
        PASSWORD_RESET  = 'password_reset',  '비밀번호 초기화'
        USER_TOGGLE     = 'user_toggle',     '계정 활성/비활성'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='audit_logs',
        verbose_name='수행자'
    )
    action = models.CharField(max_length=20, choices=Action.choices, verbose_name='액션')
    target_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name='대상 타입'
    )
    target_id = models.PositiveIntegerField(null=True, blank=True, verbose_name='대상 ID')
    target = GenericForeignKey('target_type', 'target_id')
    detail = models.TextField(blank=True, verbose_name='상세 내용')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_logs'
        verbose_name = '감사 로그'
        verbose_name_plural = '감사 로그'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        user_name = self.user.name if self.user else '시스템'
        return f'[{self.get_action_display()}] {user_name} ({self.created_at:%Y-%m-%d %H:%M})'


# ── 주문 상태 변경 이력 (3-1) ────────────────────────────────────────────────

class OrderStatusLog(models.Model):
    """주문 상태 변경 타임라인"""
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='status_logs',
        verbose_name='주문'
    )
    old_status = models.CharField(max_length=10, blank=True, verbose_name='이전 상태')
    new_status = models.CharField(max_length=10, choices=Order.Status.choices, verbose_name='변경 상태')
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='변경자'
    )
    memo = models.TextField(blank=True, verbose_name='메모')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'order_status_logs'
        verbose_name = '주문 상태 이력'
        verbose_name_plural = '주문 상태 이력'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.order.order_no}: {self.old_status} → {self.new_status}'


class CallRecording(models.Model):
    """통화 녹음 자동 수신/처리"""
    class Status(models.TextChoices):
        PENDING     = 'pending',     '대기'
        PROCESSING  = 'processing',  '처리중'
        PARSED      = 'parsed',      '파싱완료'
        ORDERED     = 'ordered',     '주문생성'
        SKIPPED     = 'skipped',     '건너뜀'
        FAILED      = 'failed',      '실패'

    audio_file = models.FileField(upload_to='call_recordings/%Y%m/', verbose_name='녹음파일')
    file_name = models.CharField(max_length=200, blank=True, verbose_name='원본파일명')
    caller_phone = models.CharField(max_length=20, blank=True, verbose_name='발신번호')
    duration_sec = models.IntegerField(null=True, blank=True, verbose_name='통화시간(초)')
    recorded_at = models.DateTimeField(null=True, blank=True, verbose_name='녹음일시')
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING,
        verbose_name='처리상태'
    )
    transcript = models.TextField(blank=True, verbose_name='변환 텍스트')
    summary = models.CharField(max_length=300, blank=True, verbose_name='통화 요약')
    is_order = models.BooleanField(null=True, blank=True, verbose_name='주문 통화 여부')
    parsed_data = models.JSONField(null=True, blank=True, verbose_name='파싱 결과')
    order = models.ForeignKey(
        Order, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='call_recordings', verbose_name='생성된 주문'
    )
    error_msg = models.CharField(max_length=300, blank=True, verbose_name='오류메시지')
    source = models.CharField(max_length=30, blank=True, verbose_name='수신경로',
                              help_text='gdrive, webhook, browser 등')
    gdrive_file_id = models.CharField(max_length=100, blank=True, verbose_name='Google Drive 파일ID')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'call_recordings'
        verbose_name = '통화 녹음'
        verbose_name_plural = '통화 녹음 목록'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.file_name or "녹음"} ({self.get_status_display()})'


class Notice(models.Model):
    class Level(models.TextChoices):
        INFO    = 'info',    '정보'
        WARNING = 'warning', '경고'
        URGENT  = 'urgent',  '긴급'

    title = models.CharField(max_length=200, verbose_name='제목')
    content = models.TextField(verbose_name='내용')
    level = models.CharField(
        max_length=10, choices=Level.choices, default=Level.INFO,
        verbose_name='중요도'
    )
    is_active = models.BooleanField(default=True, verbose_name='활성')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notices'
        verbose_name = '공지사항'
        verbose_name_plural = '공지사항'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.get_level_display()}] {self.title}'


class SiteConfig(models.Model):
    """싱글톤 사이트 설정"""
    deadline_city = models.TimeField(default='11:20', verbose_name='시내 마감시간')
    deadline_region = models.TimeField(default='13:50', verbose_name='지방 마감시간')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'site_config'
        verbose_name = '사이트 설정'

    def __str__(self):
        return f'마감: 시내 {self.deadline_city:%H:%M} / 지방 {self.deadline_region:%H:%M}'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
