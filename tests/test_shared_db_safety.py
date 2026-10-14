"""共用資料庫情境下的 PeriodicTask 安全性測試。

- resync_all 不得刪除仍被其他資料表（含未載入的外部專案資料表）外鍵參照的 PeriodicTask
- signal 以 app_label.model_name 註冊，不同 app 的同名 model 不會互相覆蓋
- 直接刪除仍被排程關聯的 PeriodicTask 時發出警告，並可由 check_celery_status 檢出
"""

import logging
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.models.signals import post_delete
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from example.models import AlertRuleTask, AsyncAlertRuleTask
from schedule_kit.models import ExecutionRecord
from schedule_kit.services import get_referenced_periodic_task_ids, resync_all

BASE = {
    "execution_cycle": "*/5 * * * *",
    "cpu_threshold": 80,
    "target_host": "server-01",
    "notify_email": "ops@example.com",
}


def make(title):
    task = AlertRuleTask.objects.create(title=title, **BASE)
    task.refresh_from_db()
    return task


def make_unlinked_periodic_task(name, task_name="alert_rule_task"):
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=60, period=IntervalSchedule.SECONDS
    )
    return PeriodicTask.objects.create(name=name, task=task_name, interval=interval)


def create_external_reference(periodic_task, table="ext_project_scheduler"):
    """模擬未載入的外部專案排程表，以外鍵參照 PeriodicTask。"""
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE TABLE {table} (id integer PRIMARY KEY, "
            "task_id integer REFERENCES django_celery_beat_periodictask(id))"
        )
        cursor.execute(f"INSERT INTO {table} (id, task_id) VALUES (1, %s)", [periodic_task.id])


# ── resync_all ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_resync_all_keeps_task_referenced_by_external_table():
    pt = make_unlinked_periodic_task("External Project PT")
    create_external_reference(pt)

    result = resync_all(AlertRuleTask)

    assert result["removed"] == 0
    assert PeriodicTask.objects.filter(pk=pt.pk).exists()


@pytest.mark.django_db
def test_resync_all_keeps_task_linked_to_other_model_with_same_task_name(monkeypatch):
    other = AsyncAlertRuleTask.objects.create(title="Async Rule", **BASE)
    other.refresh_from_db()
    monkeypatch.setattr(AlertRuleTask, "task_name", AsyncAlertRuleTask.task_name)

    result = resync_all(AlertRuleTask)

    assert result["removed"] == 0
    assert PeriodicTask.objects.filter(pk=other.task_id).exists()


@pytest.mark.django_db
def test_resync_all_ignores_execution_record_reference():
    pt = make_unlinked_periodic_task("Orphan With History")
    ExecutionRecord.objects.create(
        periodic_task=pt, task_title="Orphan With History", occurred_at=timezone.now()
    )

    result = resync_all(AlertRuleTask)

    assert result["removed"] == 1
    assert not PeriodicTask.objects.filter(pk=pt.pk).exists()


@pytest.mark.django_db
def test_get_referenced_periodic_task_ids_respects_ignore_tables():
    pt = make_unlinked_periodic_task("Ignored Table PT")
    create_external_reference(pt, table="ext_history")

    assert pt.pk in get_referenced_periodic_task_ids()
    assert pt.pk not in get_referenced_periodic_task_ids(ignore_tables=["ext_history"])


# ── signal 註冊 ───────────────────────────────────────────────────────────


def test_post_delete_signal_uid_uses_model_label():
    uids = {receiver[0][0] for receiver in post_delete.receivers}

    assert "schedule_kit.example.alertruletask.post_delete" in uids
    assert "schedule_kit.example.asyncalertruletask.post_delete" in uids


# ── PeriodicTask 被直接刪除 ───────────────────────────────────────────────


@pytest.mark.django_db
def test_direct_periodic_task_delete_warns_and_detaches(caplog):
    task = make("Detached")

    with caplog.at_level(logging.WARNING, logger="schedule_kit.signals"):
        PeriodicTask.objects.filter(pk=task.task_id).delete()

    task.refresh_from_db()
    assert task.task_id is None
    assert "resync_all(AlertRuleTask)" in caplog.text


@pytest.mark.django_db
def test_scheduler_delete_does_not_warn(caplog):
    task = make("Normal Delete")

    with caplog.at_level(logging.WARNING, logger="schedule_kit.signals"):
        task.delete()

    assert caplog.text == ""


@pytest.mark.django_db
def test_check_celery_status_reports_detached_scheduler():
    task = make("Detached Report")
    PeriodicTask.objects.filter(pk=task.task_id).delete()

    out = StringIO()
    call_command("check_celery_status", "--check", "beat", "--format", "simple", stdout=out)

    assert "1 個啟用中的排程已失去 PeriodicTask" in out.getvalue()
    assert "Detached Report" in out.getvalue()
