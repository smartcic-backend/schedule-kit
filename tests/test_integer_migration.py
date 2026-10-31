import uuid
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True)
def test_uuid_record_migration_stops_without_data_loss():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    old_target = [
        ("schedule_kit", "0002_executionrecord_occurred_at"),
        ("example", "0001_initial"),
    ]
    executor.migrate(old_target)
    old_apps = executor.loader.project_state(old_target).apps
    model = old_apps.get_model("schedule_kit", "ExecutionRecord")
    original = uuid.uuid4()
    record = model.objects.create(task_id=original, occurred_at=timezone.now())
    try:
        with pytest.raises(
            RuntimeError, match="UUID execution records exist"
        ) as blocked:
            MigrationExecutor(connection).migrate(latest)
        message = str(blocked.value)
        assert "SK-ID-UPGRADE-BLOCKED" in message
        assert "1 record(s)" in message
        assert "showmigrations" in message
        assert "mds/upgrade_integer_ids.md" in message
        assert "--fake" in message
        assert model.objects.get(pk=record.pk).task_id == original
    finally:
        model.objects.all().delete()
        MigrationExecutor(connection).migrate(latest)


@pytest.mark.django_db(transaction=True)
def test_integer_record_rollback_stops_before_removing_data():
    from schedule_kit.models import ExecutionRecord

    synced_at = timezone.now()
    record = ExecutionRecord.objects.create(
        task_id=42, occurred_at=synced_at, main_synced_at=synced_at
    )
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    try:
        with pytest.raises(RuntimeError, match="SK-ID-ROLLBACK-BLOCKED"):
            executor.migrate(
                [
                    ("schedule_kit", "0002_executionrecord_occurred_at"),
                    ("example", "0001_initial"),
                ]
            )
        # 0005 (nullable i18n columns) is freely reversible and already unapplied
        # here, so read only the columns the blocked rollback must preserve.
        assert ExecutionRecord.objects.filter(pk=record.pk).values_list(
            "task_id", "main_synced_at"
        ).get() == (42, synced_at)
    finally:
        ExecutionRecord.objects.all().delete()
        MigrationExecutor(connection).migrate(latest)
