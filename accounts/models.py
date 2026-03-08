import secrets
import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, login_id, password, role, name, **extra_fields):
        if not login_id:
            raise ValueError('login_id는 필수입니다')
        user = self.model(login_id=login_id, role=role, name=name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, login_id, password, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('name', '관리자')
        user = self.create_user(login_id, password, **extra_fields)
        user.is_staff = True
        user.is_superuser = True
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = 'admin', '총판'
        AGENCY = 'agency', '업체'
        TEACHER = 'teacher', '선생님'

    login_id = models.CharField(max_length=50, unique=True, verbose_name='아이디')
    role = models.CharField(max_length=10, choices=Role.choices, verbose_name='역할')
    name = models.CharField(max_length=100, verbose_name='이름/업체명')
    phone = models.CharField(max_length=20, blank=True, verbose_name='연락처')

    # teacher만 사용: 소속 업체
    agency = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='teachers', limit_choices_to={'role': 'agency'},
        verbose_name='소속 업체'
    )
    # teacher만 사용: 담당 학교 (1:1 고정)
    delivery_address = models.ForeignKey(
        'orders.DeliveryAddress', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='assigned_teachers', verbose_name='담당 학교'
    )

    agency_slug = models.UUIDField(
        null=True, blank=True, unique=True, verbose_name='간편주문 링크'
    )

    is_active = models.BooleanField(default=True, verbose_name='활성')
    is_staff = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=True, verbose_name='비번 변경 필요')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'login_id'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'users'
        verbose_name = '사용자'
        verbose_name_plural = '사용자 목록'

    def __str__(self):
        return f'{self.name} ({self.get_role_display()})'

    def save(self, *args, **kwargs):
        if self.role == self.Role.AGENCY and not self.agency_slug:
            self.agency_slug = uuid.uuid4()
        super().save(*args, **kwargs)

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_agency(self):
        return self.role == self.Role.AGENCY

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER


class AgencyInfo(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE,
        related_name='agency_info', limit_choices_to={'role': 'agency'},
        verbose_name='업체 계정'
    )
    rep_name = models.CharField(max_length=100, blank=True, verbose_name='대표자명')
    biz_no = models.CharField(max_length=20, blank=True, verbose_name='사업자번호')
    fax = models.CharField(max_length=20, blank=True, verbose_name='팩스')
    postal_code = models.CharField(max_length=10, blank=True, verbose_name='우편번호')
    address = models.CharField(max_length=255, blank=True, verbose_name='주소')

    class Meta:
        db_table = 'agency_info'
        verbose_name = '업체 상세정보'
        verbose_name_plural = '업체 상세정보'

    def __str__(self):
        return f'{self.user.name} 상세정보'


class InviteToken(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='invite_tokens',
        verbose_name='대상 사용자'
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(verbose_name='만료일시')
    used_at = models.DateTimeField(null=True, blank=True, verbose_name='사용일시')

    class Meta:
        db_table = 'invite_tokens'
        verbose_name = '초대 토큰'
        verbose_name_plural = '초대 토큰 목록'

    def __str__(self):
        return f'{self.user.name} 초대 ({self.token[:8]}...)'

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()

    @classmethod
    def create_for_user(cls, user, expire_days=7):
        token = secrets.token_urlsafe(32)
        return cls.objects.create(
            user=user,
            token=token,
            expires_at=timezone.now() + timezone.timedelta(days=expire_days),
        )
