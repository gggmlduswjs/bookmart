from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0004_add_inbox_attachment'),
    ]

    operations = [
        migrations.AddField(
            model_name='inboxmessage',
            name='is_read',
            field=models.BooleanField(default=False, verbose_name='읽음'),
        ),
        migrations.AddField(
            model_name='inboxmessage',
            name='message_id',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='Message-ID'),
        ),
    ]
