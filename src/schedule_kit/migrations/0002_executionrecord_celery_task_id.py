from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("schedule_kit", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="executionrecord",
            name="celery_task_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
    ]
