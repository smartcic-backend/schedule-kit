import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("example", "0001_initial"),
        ("django_celery_beat", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AsyncAlertRuleTask",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=70, unique=True)),
                ("description", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "active"), ("disabled", "disabled")],
                        default="active",
                        max_length=8,
                    ),
                ),
                ("execution_cycle", models.CharField(max_length=128)),
                ("timezone", models.CharField(default="UTC", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("cpu_threshold", models.FloatField()),
                ("target_host", models.CharField(max_length=255)),
                ("notify_email", models.EmailField(max_length=254)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "task",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="asyncalerttask",
                        to="django_celery_beat.periodictask",
                    ),
                ),
            ],
            options={
                "verbose_name": "CPU 告警排程（非同步）",
            },
        ),
    ]
