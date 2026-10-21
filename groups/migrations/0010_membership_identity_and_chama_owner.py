import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('groups', '0009_alter_mpesatransaction_options_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='chama',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='created_chamas',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='membership',
            name='national_id',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AlterField(
            model_name='membership',
            name='user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='chama_memberships',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name='membership',
            constraint=models.UniqueConstraint(
                condition=models.Q(national_id__isnull=False),
                fields=('chama', 'national_id'),
                name='unique_national_id_per_chama',
            ),
        ),
        migrations.AlterField(
            model_name='membership',
            name='phone_number',
            field=models.CharField(max_length=15),
        ),
        migrations.AddConstraint(
            model_name='membership',
            constraint=models.UniqueConstraint(
                fields=('chama', 'phone_number'),
                name='unique_phone_per_chama',
            ),
        ),
    ]
