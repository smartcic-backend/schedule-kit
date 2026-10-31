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
from schedule_kit.messages import TASK_RAISED, ExecutionMessage

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


# oivsion360 celery_skdl.0042: message_code varchar(100), message_params / message_i18n
# jsonb, all nullable. SQLite stores JSON as TEXT.
I18N_COLUMNS = (
    ", message_code VARCHAR(100) NULL, message_params TEXT NULL, message_i18n TEXT NULL"
)


def _main_table(extra_columns=""):
    from schedule_kit import transports

    transports.reset_main_columns_cache()
    with connection.cursor() as c:
        c.execute(f"""CREATE TABLE celery_skdl_executionrecord (
            id INTEGER PRIMARY KEY, task_title VARCHAR(255), task_function VARCHAR(255),
            task_model VARCHAR(255), task_id INTEGER, task_created_by_id INTEGER,
            result VARCHAR(8), start_time DATETIME, end_time DATETIME, message TEXT,
            periodic_task_id INTEGER REFERENCES django_celery_beat_periodictask(id)
            {extra_columns}
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
    transports.reset_main_columns_cache()


@pytest.fixture
def main_table():
    """Main table before oivsion360 celery_skdl.0042 (legacy schema)."""
    yield from _main_table()


@pytest.fixture
def main_table_i18n():
    """Main table after oivsion360 celery_skdl.0042."""
    yield from _main_table(I18N_COLUMNS)


def test_main_table_fixtures_create_and_drop():
    for name, has_i18n in (("main_table", False), ("main_table_i18n", True)):
        fixture = globals()[name].__wrapped__()
        next(fixture)
        columns = {
            c.name
            for c in connection.introspection.get_table_description(
                connection.cursor(), "celery_skdl_executionrecord"
            )
        }
        assert ("message_i18n" in columns) is has_i18n
        next(fixture, None)
        assert "celery_skdl_executionrecord" not in connection.introspection.table_names()


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
        raise ValueError("password=private-credential")

    with pytest.raises(ValueError, match="private-credential"):
        task(rule, body).run(scheduler_id=rule.pk)
    rec = ExecutionRecord.objects.get()
    assert rec.task_created_by_id == rule.created_by_id
    assert rec.task_model == "example-service:example.AlertRuleTask"
    assert rec.message_code == "schedule_kit.task_raised"
    assert rec.message_params == {"exception": "ValueError"}
    assert rec.message_i18n["zh-hant"] == "任務發生例外：ValueError"
    stored = [rec.message, rec.message_code, rec.message_params, rec.message_i18n]
    assert "private-credential" not in repr(stored)
    with connection.cursor() as c:
        c.execute("SELECT message FROM celery_skdl_executionrecord")
        assert "private-credential" not in repr(c.fetchall())
    assert main_rows()[0][3] == "fail"


@pytest.mark.parametrize(
    "result, code",
    [("not a tuple", "schedule_kit.invalid_return"),
     ((None, "yes", "x"), "schedule_kit.invalid_success")],
)
def test_invalid_return_uses_builtin_codes(rule, result, code):
    with pytest.raises(CeleryKitError):
        task(rule, lambda _: result).run(rule.pk)
    assert ExecutionRecord.objects.get().message_code == code


def test_task_can_return_execution_message(rule):
    message = ExecutionMessage(
        "example.report.sent", "Report sent to %(count)d recipients", {"count": 3}
    )
    record_id = task(rule, lambda _: (rule, True, message)).run(rule.pk)
    rec = ExecutionRecord.objects.get(pk=record_id)
    assert rec.status == "success"
    assert rec.message == "Report sent to 3 recipients"
    assert rec.message_code == "example.report.sent"
    assert rec.message_params == {"count": 3}
    assert rec.message_i18n == {
        "en": "Report sent to 3 recipients",
        "zh-hant": "Report sent to 3 recipients",
    }


def test_task_returning_plain_text_keeps_legacy_fields(rule):
    record_id = task(rule).run(rule.pk)
    rec = ExecutionRecord.objects.get(pk=record_id)
    assert (rec.status, rec.message) == ("success", "ok")
    assert (rec.message_code, rec.message_params, rec.message_i18n) == (None, None, None)


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


def test_pending_callback_failure_with_execution_message_is_shared(rule, main_table):
    record_id = task(
        rule, lambda _: (rule, None, "dispatched"), require_record=True
    ).run(rule.pk)
    update_record(record_id, False, TASK_RAISED.with_params(exception="AgentError"))
    assert main_rows()[0][3] == "fail"
    rec = ExecutionRecord.objects.get(pk=record_id)
    assert rec.message == "Task raised AgentError"
    assert rec.message_i18n["zh-hant"] == "任務發生例外：AgentError"


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
    rec = ExecutionRecord.objects.get(pk=rec_id)
    assert rec.message_code == "schedule_kit.pending_timeout"
    assert rec.message_params == {"status": "pending"}
    assert rec.message_i18n == {
        "en": "timeout: pending exceeded configured limit",
        "zh-hant": "逾時：pending 狀態超過設定的時限",
    }


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
        "schedule_kit.transports.DbTransport.publish",
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
        "schedule_kit.transports.DbTransport.publish",
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


def test_finish_with_execution_message_writes_i18n_fields(rule):
    from schedule_kit.recording import finish_record

    record = ExecutionRecord.objects.create(occurred_at=timezone.now())
    finish_record(record, "fail", TASK_RAISED.with_params(exception="KeyError"))
    record.refresh_from_db()
    assert record.status == "fail"
    assert record.message == "Task raised KeyError"
    assert record.message_code == "schedule_kit.task_raised"
    assert record.message_params == {"exception": "KeyError"}
    assert record.message_i18n == {
        "en": "Task raised KeyError",
        "zh-hant": "任務發生例外：KeyError",
    }


def test_finish_with_plain_text_keeps_legacy_columns(rule):
    from schedule_kit.recording import finish_record

    record = ExecutionRecord.objects.create(
        occurred_at=timezone.now(),
        message_code="stale.code",
        message_params={"a": 1},
        message_i18n={"en": "stale"},
    )
    finish_record(record, "fail", "x" * 5000)
    record.refresh_from_db()
    assert record.status == "fail"
    assert record.message == "x" * 4000
    assert (record.message_code, record.message_params, record.message_i18n) == (
        None,
        None,
        None,
    )


def test_formatting_overflow_preserves_success_and_main_projection(rule, main_table_i18n):
    message = ExecutionMessage("example.number", "Value %(value)f", {"value": 10**400})
    record_id = task(rule, lambda _: (rule, True, message)).run(rule.pk)
    record = ExecutionRecord.objects.get(pk=record_id)
    assert record.status == "success"
    assert record.end_time is not None
    assert record.message == message.msgid
    assert record.message_i18n == {"en": message.msgid, "zh-hant": message.msgid}
    assert record.main_synced_at is not None
    assert main_i18n_rows() == [
        (message.msgid, message.code, {"value": 10**400}, record.message_i18n)
    ]


REPORT_SENT = ExecutionMessage(
    "example.report.sent", "Report sent to %(count)d recipients", {"count": 3}
)


def main_i18n_rows():
    import json

    with connection.cursor() as c:
        c.execute(
            "SELECT message, message_code, message_params, message_i18n "
            "FROM celery_skdl_executionrecord ORDER BY id"
        )
        return [
            (m, code, params and json.loads(params), i18n and json.loads(i18n))
            for m, code, params, i18n in c.fetchall()
        ]


def test_main_i18n_columns_match_local(rule, main_table_i18n):
    record_id = task(rule, lambda _: (rule, True, REPORT_SENT)).run(rule.pk)
    rec = ExecutionRecord.objects.get(pk=record_id)
    assert main_i18n_rows() == [
        (rec.message, rec.message_code, rec.message_params, rec.message_i18n)
    ]
    assert rec.message_code == "example.report.sent"
    assert main_rows()[0][3] == "success"


def test_main_i18n_columns_null_for_plain_text(rule, main_table_i18n):
    task(rule).run(rule.pk)
    assert main_i18n_rows() == [("ok", None, None, None)]


def test_builtin_timeout_reaches_main_in_both_languages(rule, main_table_i18n):
    from datetime import timedelta
    from schedule_kit.tasks.maintenance import cleanup_execution_records

    rec_id = task(rule, lambda _: (rule, None, "waiting"), require_record=True).run(
        rule.pk
    )
    ExecutionRecord.objects.filter(pk=rec_id).update(
        occurred_at=timezone.now() - timedelta(hours=48)
    )
    cleanup_execution_records.run()
    [(message, code, params, i18n)] = main_i18n_rows()
    assert code == "schedule_kit.pending_timeout"
    assert set(i18n) == {"en", "zh-hant"}


def test_legacy_main_schema_degrades_and_warns_once(rule, main_table, caplog):
    first = task(rule, lambda _: (rule, True, REPORT_SENT)).run(rule.pk)
    second = task(rule, lambda _: (rule, True, REPORT_SENT)).run(rule.pk)
    for record_id in (first, second):
        assert ExecutionRecord.objects.get(pk=record_id).main_synced_at is not None
    assert [row[3] for row in main_rows()] == ["success", "success"]
    with connection.cursor() as c:
        c.execute("SELECT message FROM celery_skdl_executionrecord")
        assert {row[0] for row in c.fetchall()} == {"Report sent to 3 recipients"}
    warnings = [r for r in caplog.records if "celery_skdl.0042" in r.getMessage()]
    assert len(warnings) == 1


def test_column_detection_failure_is_not_cached(rule):
    from schedule_kit import transports

    transports.reset_main_columns_cache()
    settings = {"WRITE_MAIN_EXECUTION_RECORDS": True, "EXECUTION_SOURCE": "example-service"}
    with override_settings(CELERY_SCHEDULER=settings):
        rec_id = task(rule, lambda _: (rule, True, REPORT_SENT)).run(rule.pk)
        assert ExecutionRecord.objects.get(pk=rec_id).main_synced_at is None
        with connection.cursor() as c:
            c.execute(
                "CREATE TABLE celery_skdl_executionrecord (id INTEGER PRIMARY KEY, "
                "task_title VARCHAR(255), task_function VARCHAR(255), task_model VARCHAR(255), "
                "task_id INTEGER, task_created_by_id INTEGER, result VARCHAR(8), "
                "start_time DATETIME, end_time DATETIME, message TEXT, periodic_task_id INTEGER"
                + I18N_COLUMNS + ")"
            )
        try:
            update_record(rec_id, True, "retry")  # Terminal: retries the projection.
            assert ExecutionRecord.objects.get(pk=rec_id).main_synced_at is not None
            assert main_i18n_rows()[0][1] == "example.report.sent"
        finally:
            with connection.cursor() as c:
                c.execute("DROP TABLE celery_skdl_executionrecord")
            transports.reset_main_columns_cache()


def test_main_failure_then_retry_writes_i18n_once(rule, main_table_i18n):
    from schedule_kit.tasks.maintenance import cleanup_execution_records

    with patch(
        "schedule_kit.transports.DbTransport.publish",
        side_effect=DatabaseError("main failure"),
    ):
        rec_id = task(rule, lambda _: (rule, True, REPORT_SENT)).run(rule.pk)
    assert main_rows() == []
    cleanup_execution_records.run()
    cleanup_execution_records.run()
    rec = ExecutionRecord.objects.get(pk=rec_id)
    assert main_i18n_rows() == [
        (rec.message, rec.message_code, rec.message_params, rec.message_i18n)
    ]


def test_unsupported_transport_fails_before_business_code(rule):
    from django.core.exceptions import ImproperlyConfigured

    called = []
    with override_settings(
        CELERY_SCHEDULER={
            "WRITE_MAIN_EXECUTION_RECORDS": True,
            "EXECUTION_SOURCE": "example-service",
            "EXECUTION_TRANSPORT": "rbmq",
        }
    ):
        with pytest.raises(ImproperlyConfigured, match="supported values: db"):
            task(rule, lambda _: called.append(True)).run(rule.pk)
    assert called == []
    assert not ExecutionRecord.objects.exists()


def test_default_transport_is_db():
    from schedule_kit.conf import _DEFAULTS, get_execution_transport
    from schedule_kit.transports import DbTransport

    assert _DEFAULTS["EXECUTION_TRANSPORT"] == "db"
    assert isinstance(get_execution_transport(), DbTransport)


def test_failed_i18n_insert_redetects_columns_on_retry(rule, main_table_i18n):
    from schedule_kit.tasks.maintenance import cleanup_execution_records

    task(rule).run(rule.pk)  # Caches "main table has i18n columns".
    with connection.cursor() as c:  # Simulate oivsion360 rolling back 0042.
        c.execute("DROP TABLE celery_skdl_executionrecord")
        c.execute(
            "CREATE TABLE celery_skdl_executionrecord (id INTEGER PRIMARY KEY, "
            "task_title VARCHAR(255), task_function VARCHAR(255), task_model VARCHAR(255), "
            "task_id INTEGER, task_created_by_id INTEGER, result VARCHAR(8), "
            "start_time DATETIME, end_time DATETIME, message TEXT, periodic_task_id INTEGER)"
        )
    rec_id = task(rule, lambda _: (rule, True, REPORT_SENT)).run(rule.pk)
    assert ExecutionRecord.objects.get(pk=rec_id).main_synced_at is None
    cleanup_execution_records.run()  # Retry within the cache window succeeds.
    assert ExecutionRecord.objects.get(pk=rec_id).main_synced_at is not None
    assert main_rows()[0][3] == "success"
