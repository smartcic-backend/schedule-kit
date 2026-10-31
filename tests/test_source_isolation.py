"""Several projects share one DB and the local schedule_kit_executionrecord table."""

import logging
from datetime import timedelta

import pytest
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from schedule_kit.api import update_record
from schedule_kit.models import ExecutionRecord
from schedule_kit.tasks.maintenance import cleanup_execution_records

pytestmark = pytest.mark.django_db

SHARED = {
    "WRITE_MAIN_EXECUTION_RECORDS": True,
    "EXECUTION_SOURCE": "example-service",
    "PENDING_TIMEOUT_HOURS": 1,
    "TASK_RECORD_KEEP_MAX_DAYS": 7,
    "TASK_RECORD_KEEP_MAX_COUNT": 1,
}
OWN = "example-service:example.AlertRuleTask"
OTHER = "other-service:example.AlertRuleTask"


@pytest.fixture
def main_table():
    from schedule_kit import transports

    transports.reset_main_columns_cache()
    with connection.cursor() as c:
        c.execute("""CREATE TABLE celery_skdl_executionrecord (
            id INTEGER PRIMARY KEY, task_title VARCHAR(255), task_function VARCHAR(255),
            task_model VARCHAR(255), task_id INTEGER, task_created_by_id INTEGER,
            result VARCHAR(8), start_time DATETIME, end_time DATETIME, message TEXT,
            periodic_task_id INTEGER
        )""")
    yield
    with connection.cursor() as c:
        c.execute("DROP TABLE celery_skdl_executionrecord")
    transports.reset_main_columns_cache()


def make(task_model, status, age=timedelta(0), synced=False, task_id=1):
    occurred = timezone.now() - age
    return ExecutionRecord.objects.create(
        task_model=task_model,
        task_id=task_id,
        task_created_by_id=1,
        status=status,
        occurred_at=occurred,
        end_time=None if status in ("pending", "running") else occurred,
        main_synced_at=occurred if synced else None,
    )


def main_models():
    with connection.cursor() as c:
        c.execute("SELECT task_model FROM celery_skdl_executionrecord")
        return [row[0] for row in c.fetchall()]


def status(record):
    return ExecutionRecord.objects.get(pk=record.pk).status


def test_shared_maintenance_only_touches_own_source(main_table, caplog):
    old = timedelta(days=30)
    own_pending = make(OWN, "pending", age=timedelta(hours=2))
    other_pending = make(OTHER, "pending", age=timedelta(hours=2))
    own_unsynced = make(OWN, "success", task_id=2)
    other_unsynced = make(OTHER, "success", task_id=2)
    own_expired = make(OWN, "success", age=old, synced=True, task_id=3)
    other_expired = make(OTHER, "success", age=old, synced=True, task_id=3)
    own_extra = [make(OWN, "fail", synced=True, task_id=4) for _ in range(2)]
    other_extra = [make(OTHER, "fail", synced=True, task_id=4) for _ in range(2)]

    with caplog.at_level(logging.INFO), override_settings(CELERY_SCHEDULER=SHARED):
        cleanup_execution_records.run()

    # Timeout
    assert status(own_pending) == "fail"
    assert status(other_pending) == "pending"
    # Retry: only our unsynced outcomes are projected.
    assert ExecutionRecord.objects.get(pk=own_unsynced.pk).main_synced_at is not None
    assert ExecutionRecord.objects.get(pk=other_unsynced.pk).main_synced_at is None
    assert OTHER not in main_models()
    # Day and count retention.
    assert not ExecutionRecord.objects.filter(pk=own_expired.pk).exists()
    assert ExecutionRecord.objects.filter(pk=other_expired.pk).exists()
    assert ExecutionRecord.objects.filter(pk__in=[r.pk for r in own_extra]).count() == 1
    assert ExecutionRecord.objects.filter(pk__in=[r.pk for r in other_extra]).count() == 2
    assert "does not match" not in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("source", ["", "example-service"])
def test_unshared_cleanup_keeps_other_sources(source):
    config = {"EXECUTION_SOURCE": source, "TASK_RECORD_KEEP_MAX_DAYS": 7}
    old = timedelta(days=30)
    unprefixed = make("example.AlertRuleTask", "success", age=old)
    own = make(OWN, "success", age=old)
    other = make(OTHER, "success", age=old)
    other_pending = make(OTHER, "pending", age=old)

    with override_settings(CELERY_SCHEDULER=config):
        cleanup_execution_records.run()

    assert not ExecutionRecord.objects.filter(pk=unprefixed.pk).exists()
    assert ExecutionRecord.objects.filter(pk=own.pk).exists() is (not source)
    assert ExecutionRecord.objects.filter(pk=other.pk).exists()
    assert status(other_pending) == "pending"


def test_update_record_ignores_other_source(caplog):
    other = make(OTHER, "pending")
    with override_settings(CELERY_SCHEDULER=SHARED):
        update_record(other.pk, True, "callback for someone else")
    record = ExecutionRecord.objects.get(pk=other.pk)
    assert (record.status, record.message) == ("pending", "")
    assert "another execution source" in caplog.text


def test_update_record_still_completes_own_and_unattributed_records():
    own = make(OWN, "pending")
    unattributed = make("", "pending")
    with override_settings(CELERY_SCHEDULER={"EXECUTION_SOURCE": "example-service"}):
        update_record(own.pk, True, "done")
        update_record(unattributed.pk, False, "failed")
    assert status(own) == "success"
    assert status(unattributed) == "fail"
