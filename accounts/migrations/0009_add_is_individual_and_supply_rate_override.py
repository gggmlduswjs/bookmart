from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_remove_user_plain_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_individual',
            field=models.BooleanField(default=False, verbose_name='개인선생님'),
        ),
        migrations.AddField(
            model_name='user',
            name='supply_rate_override',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=5,
                null=True, verbose_name='공급률 오버라이드(%)',
            ),
        ),
    ]
