import uuid
from datetime import timedelta

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def default_token_expiry():
    return django.utils.timezone.now() + timedelta(days=7)


class Migration(migrations.Migration):

    dependencies = [
        ("coreapp", "0012_contactrequest"),
    ]

    operations = [
        migrations.CreateModel(
            name="AmenityCheckInToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(default=default_token_expiry)),
                ("is_active", models.BooleanField(default=True)),
                ("amenity", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="checkin_tokens", to="coreapp.amenity")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="issued_checkin_tokens", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="amenitycheckintoken",
            index=models.Index(fields=["token"], name="coreapp_amen_token_8fbc86_idx"),
        ),
        migrations.AddIndex(
            model_name="amenitycheckintoken",
            index=models.Index(fields=["amenity"], name="coreapp_amen_amenity__8f2e74_idx"),
        ),
        migrations.AddIndex(
            model_name="amenitycheckintoken",
            index=models.Index(fields=["is_active", "expires_at"], name="coreapp_amen_is_active_4b8cf3_idx"),
        ),
    ]
