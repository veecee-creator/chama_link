from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('groups', '0010_membership_identity_and_chama_owner'),
    ]

    operations = [
        migrations.AddField(
            model_name='membership',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
    ]
