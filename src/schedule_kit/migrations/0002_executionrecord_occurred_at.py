from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("schedule_kit", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="executionrecord",
            old_name="start_time",
            new_name="occurred_at",
        ),
        migrations.AlterField(
            model_name="executionrecord",
            name="task_title",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AlterField(
            model_name="executionrecord",
            name="task_function",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AlterModelOptions(
            name="executionrecord",
            options={"ordering": ["-occurred_at"]},
        ),
    ]
