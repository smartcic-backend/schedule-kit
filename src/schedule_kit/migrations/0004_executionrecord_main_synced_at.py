from django.db import migrations, models


def protect_sync_state_on_rollback(apps, schema_editor):
    model = apps.get_model("schedule_kit", "ExecutionRecord")
    if model.objects.using(schema_editor.connection.alias).exists():
        raise RuntimeError(
            "[SK-ID-ROLLBACK-BLOCKED] Execution records exist. Removing main_synced_at "
            "would lose retry/deduplication state. Back up and follow mds/upgrade_integer_ids.md."
        )


class Migration(migrations.Migration):
    dependencies = [("schedule_kit", "0003_integer_task_id")]
    operations = [
        migrations.AddField(
            model_name="executionrecord",
            name="main_synced_at",
            field=models.DateTimeField(
                null=True, blank=True, editable=False, db_index=True
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, protect_sync_state_on_rollback),
    ]
