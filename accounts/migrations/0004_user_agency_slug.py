import uuid
from django.db import migrations, models


def populate_agency_slugs(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    for user in User.objects.filter(role='agency', agency_slug__isnull=True):
        user.agency_slug = uuid.uuid4()
        user.save(update_fields=['agency_slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_invite_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='agency_slug',
            field=models.UUIDField(blank=True, null=True, unique=True, verbose_name='간편주문 링크'),
        ),
        migrations.RunPython(populate_agency_slugs, migrations.RunPython.noop),
    ]
