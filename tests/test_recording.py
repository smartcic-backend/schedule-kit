import uuid
from unittest.mock import patch

import pytest
from django.db import connection, DatabaseError
from django.test import override_settings
from django.utils import timezone
from celery import current_app
from example.models import AlertRuleTask
from schedule_kit.models import ExecutionRecord
from schedule_kit.decorators import recorded_task
from schedule_kit.exceptions import CeleryKitError
from schedule_kit.api import update_record

pytestmark = pytest.mark.django_db


@pytest.fixture
def rule(user):
    return AlertRuleTask.objects.create(
        title="Recorded",
        execution_cycle="*/5 * * * *",
        created_by=user,
        cpu_threshold=80,
        target_host="test",
        notify_email="test@example.test",
    )


@pytest.fixture
def main_table():
    with connection.cursor() as c:
        c.execute("""CREATE TABLE celery_skdl_executionrecord (
            id INTEGER PRIMARY KEY, task_title VARCHAR(255), task_function VARCHAR(255),
            task_model VARCHAR(255), task_id INTEGER, task_created_by_id INTEGER,
            result VARCHAR(8), start_time DATETIME, end_time DATETIME, message TEXT,
            periodic_task_id INTEGER REFERENCES django_celery_beat_periodictask(id)
        )""")
    with override_settings(
        CELERY_SCHEDULER={
            "WRITE_MAIN_EXECUTION_RECORDS": True,
            "EXECUTION_SOURCE": "example-service",
        }
    ):
        yield
    with connection.cursor() as c:
        c.execute("DROP TABLE celery_skdl_executionrecord")


def main_rows():
    with connection.cursor() as c:
        c.execute(
            "SELECT task_model, task_id, task_created_by_id, result, periodic_task_id FROM celery_skdl_executionrecord ORDER BY id"
        )
        return c.fetchall()


def task(rule, body=None, **options):
    @recorded_task(
        name="review_" + uuid.uuid4().hex, scheduler_model=AlertRuleTask, **options
    )
    def run(scheduler_id, extra="option", record_id=None):
        if body:
            return body(record_id)
        return rule, True, "ok"

    return run


def test_integer_ids_and_shared_success(rule, main_table):
    record_id = task(rule).run(rule.pk, "multiple arguments")
    assert isinstance(rule.pk, int)
    record = ExecutionRecord.objects.get(pk=record_id)
    assert record.task_id == rule.pk
    assert record.periodic_task_id == rule.task_id
    assert main_rows() == [
        (
            "example-service:example.AlertRuleTask",
            rule.pk,
            rule.created_by_id,
            "success",
            rule.task_id,
        )
    ]


def test_business_failure_is_celery_failure(rule, main_table):
    current_app.conf.update(broker_url="memory://", result_backend="cache+memory://")
    run = task(rule, lambda _: (rule, False, "failed"))
    result = run.apply(args=[rule.pk], task_id=str(uuid.uuid4()))
    assert result.state == "FAILURE"
    assert main_rows()[0][3] == "fail"


def test_exception_has_owner_and_does_not_leak_exception_message(rule, main_table):
    def body(_):
        raise ValueError("private-credential")

    with pytest.raises(ValueError, match="private-credential"):
        task(rule, body).run(scheduler_id=rule.pk)
    rec = ExecutionRecord.objects.get()
    assert rec.task_created_by_id == rule.created_by_id
    assert rec.task_model == "example-service:example.AlertRuleTask"
    assert "private-credential" not in rec.message
    assert main_rows()[0][3] == "fail"


def test_local_create_failure_does_not_block_sync_task(rule, main_table):
    with patch.object(ExecutionRecord, "save", side_effect=DatabaseError("broken")):
        assert task(rule).run(rule.pk) is None
    assert (
        main_rows() == []
    )  # Without a durable record there is no safe retry/deduplication key.


def test_async_requires_durable_record_before_dispatch(rule):
    called = []
    with patch.object(ExecutionRecord, "save", side_effect=DatabaseError("broken")):
        with pytest.raises(CeleryKitError):
            task(rule, lambda _: called.append(True), require_record=True).run(rule.pk)
    assert not called


def test_completion_error_does_not_mask_original_exception(rule, main_table):
    def body(_):
        raise ValueError("original")

    with patch(
        "django.db.models.query.QuerySet.update", side_effect=DatabaseError("broken")
    ):
        with pytest.raises(ValueError, match="original"):
            task(rule, body).run(rule.pk)
    assert main_rows() == []  # Do not publish an outcome whose local write failed.


def test_missing_main_table_does_not_change_success(rule):
    with override_settings(
        CELERY_SCHEDULER={
            "WRITE_MAIN_EXECUTION_RECORDS": True,
            "EXECUTION_SOURCE": "example-service",
        }
    ):
        record_id = task(rule).run(rule.pk)
    assert ExecutionRecord.objects.get(pk=record_id).status == "success"


def test_callback_writes_once_and_early_callback_is_not_overwritten(rule, main_table):
    def body(record_id):
        update_record(record_id, True, "done before dispatcher returns")
        return rule, None, "dispatched"

    record_id = task(rule, body, require_record=True).run(rule.pk)
    update_record(record_id, True, "duplicate")
    assert ExecutionRecord.objects.get(pk=record_id).status == "success"
    assert len(main_rows()) == 1
    assert main_rows()[0][3] == "success"


def test_pending_callback_failure_is_shared(rule, main_table):
    record_id = task(
        rule, lambda _: (rule, None, "dispatched"), require_record=True
    ).run(rule.pk)
    assert main_rows() == []
    update_record(record_id, False, "agent failed")
    assert main_rows()[0][3] == "fail"


def test_delete_scheduler_removes_shared_fk_and_keeps_local_history(rule, main_table):
    record_id = task(rule).run(rule.pk)
    rule.delete()
    connection.check_constraints()
    assert main_rows() == []
    assert ExecutionRecord.objects.get(pk=record_id).periodic_task_id is None


def test_count_retention_does_not_cross_models():
    from schedule_kit.tasks.maintenance import cleanup_execution_records

    for model in ("First", "Second"):
        for _ in range(3):
            ExecutionRecord.objects.create(
                task_id=1,
                task_model=model,
                occurred_at=timezone.now(),
                status="success",
            )
    with override_settings(CELERY_SCHEDULER={"TASK_RECORD_KEEP_MAX_COUNT": 2}):
        cleanup_execution_records.run()
    assert ExecutionRecord.objects.filter(task_model="First").count() == 2
    assert ExecutionRecord.objects.filter(task_model="Second").count() == 2


def test_shared_retention_scoped_to_model_and_id(rule, main_table):
    with override_settings(TASK_RECORD_KEEP_MAX_COUNT=2):
        for _ in range(4):
            task(rule).run(rule.pk)
    assert len(main_rows()) == 2


def test_timeout_is_written_to_main(rule, main_table):
    from datetime import timedelta
    from schedule_kit.tasks.maintenance import cleanup_execution_records

    rec_id = task(rule, lambda _: (rule, None, "waiting"), require_record=True).run(
        rule.pk
    )
    ExecutionRecord.objects.filter(pk=rec_id).update(
        occurred_at=timezone.now() - timedelta(hours=48)
    )
    cleanup_execution_records.run()
    assert main_rows()[0][3] == "fail"


def test_same_model_and_id_in_two_sources_do_not_share_retention(rule, main_table):
    for source in ("child-a", "child-b"):
        with override_settings(
            CELERY_SCHEDULER={
                "WRITE_MAIN_EXECUTION_RECORDS": True,
                "EXECUTION_SOURCE": source,
            },
            TASK_RECORD_KEEP_MAX_COUNT=1,
        ):
            task(rule).run(rule.pk)
    assert {row[0] for row in main_rows()} == {
        "child-a:example.AlertRuleTask",
        "child-b:example.AlertRuleTask",
    }
    assert len(main_rows()) == 2


def test_same_named_models_in_different_apps_have_distinct_identities(main_table):
    from types import SimpleNamespace
    from schedule_kit.recording import scheduler_identity

    first = SimpleNamespace(_meta=SimpleNamespace(label="app_a.ReportTask"))
    second = SimpleNamespace(_meta=SimpleNamespace(label="app_b.ReportTask"))
    assert scheduler_identity(first) != scheduler_identity(second)


def test_missing_source_fails_before_business_dispatch(rule):
    from django.core.exceptions import ImproperlyConfigured

    called = []
    with override_settings(CELERY_SCHEDULER={"WRITE_MAIN_EXECUTION_RECORDS": True}):
        with pytest.raises(ImproperlyConfigured, match="EXECUTION_SOURCE"):
            task(rule, lambda _: called.append(True)).run(rule.pk)
    assert called == []


def test_local_update_failure_then_repeated_callback_writes_once(rule, main_table):
    rec_id = task(rule, lambda _: (rule, None, "waiting"), require_record=True).run(
        rule.pk
    )
    with patch(
        "django.db.models.query.QuerySet.update",
        side_effect=DatabaseError("local failure"),
    ):
        update_record(rec_id, True, "done")
    assert main_rows() == []
    assert ExecutionRecord.objects.get(pk=rec_id).status == "pending"
    update_record(rec_id, True, "retry")
    update_record(rec_id, True, "duplicate")
    assert len(main_rows()) == 1
    record = ExecutionRecord.objects.get(pk=rec_id)
    assert record.status == "success"
    assert record.main_synced_at is not None


def test_main_insert_failure_retries_without_changing_terminal_result(rule, main_table):
    with patch(
        "schedule_kit.recording._insert_main_record",
        side_effect=DatabaseError("main failure"),
    ):
        rec_id = task(rule).run(rule.pk)
    record = ExecutionRecord.objects.get(pk=rec_id)
    assert record.status == "success"
    assert record.main_synced_at is None
    assert main_rows() == []
    update_record(rec_id, False, "conflicting duplicate callback")
    update_record(rec_id, True, "another callback")
    assert len(main_rows()) == 1
    assert main_rows()[0][3] == "success"


def test_marker_failure_rolls_back_insert_and_retry_writes_once(rule, main_table):
    rec_id = task(rule, lambda _: (rule, None, "waiting"), require_record=True).run(
        rule.pk
    )
    original_save = ExecutionRecord.save

    def fail_marker(instance, *args, **kwargs):
        if kwargs.get("update_fields") == ["main_synced_at"]:
            raise DatabaseError("marker failure")
        return original_save(instance, *args, **kwargs)

    with patch.object(ExecutionRecord, "save", fail_marker):
        update_record(rec_id, True, "done")
    assert main_rows() == []
    assert ExecutionRecord.objects.get(pk=rec_id).main_synced_at is None
    update_record(rec_id, True, "retry")
    update_record(rec_id, True, "duplicate")
    assert len(main_rows()) == 1


def test_maintenance_keeps_unsynced_records_and_retries_them(rule, main_table):
    from schedule_kit.tasks.maintenance import cleanup_execution_records

    with patch(
        "schedule_kit.recording._insert_main_record",
        side_effect=DatabaseError("main failure"),
    ):
        rec_id = task(rule).run(rule.pk)
        with override_settings(
            CELERY_SCHEDULER={
                "WRITE_MAIN_EXECUTION_RECORDS": True,
                "EXECUTION_SOURCE": "example-service",
                "TASK_RECORD_KEEP_MAX_COUNT": 0,
                "TASK_RECORD_KEEP_MAX_DAYS": 0,
            }
        ):
            cleanup_execution_records.run()
        assert ExecutionRecord.objects.filter(pk=rec_id, main_synced_at=None).exists()
    cleanup_execution_records.run()
    cleanup_execution_records.run()
    assert len(main_rows()) == 1
    assert ExecutionRecord.objects.get(pk=rec_id).main_synced_at is not None
