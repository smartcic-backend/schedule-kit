import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExecutionRecord",
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
                ("task_title", models.CharField(blank=True, default="", max_length=70)),
                ("task_function", models.CharField(max_length=255)),
                ("task_model", models.CharField(blank=True, default="", max_length=255)),
                ("task_id", models.IntegerField()),
                ("task_created_by_id", models.IntegerField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("running", "running"),
                            ("pending", "pending"),
                            ("success", "success"),
                            ("fail", "fail"),
                        ],
                        default="running",
                        max_length=8,
                    ),
                ),
                ("start_time", models.DateTimeField()),
                ("end_time", models.DateTimeField(blank=True, null=True)),
                ("message", models.TextField(blank=True, default="")),
                (
                    "periodic_task",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="execution_records",
                        to="django_celery_beat.periodictask",
                    ),
                ),
            ],
            options={
                "ordering": ["-start_time"],
            },
        ),
    ]
