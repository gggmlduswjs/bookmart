from django.core.management.base import BaseCommand
from accounts.models import User


class Command(BaseCommand):
    help = 'admin 계정의 must_change_password를 False로 변경'

    def handle(self, *args, **options):
        updated = User.objects.filter(role='admin', must_change_password=True).update(must_change_password=False)
        self.stdout.write(self.style.SUCCESS(f'admin {updated}건 업데이트 완료'))
