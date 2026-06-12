import pytest
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from example.models import AlertRuleTask
from schedule_kit.services import resync_all

BASE = {
    "title": "Sync Test",
    "execution_cycle": "*/5 * * * *",
    "cpu_threshold": 80,
    "target_host": "server-01",
    "notify_email": "ops@example.com",
}


def make(**kwargs):
    return AlertRuleTask.objects.create(**{**BASE, **kwargs})


@pytest.mark.django_db
def test_periodic_task_created_on_save():
    task = make()
    task.refresh_from_db()
    assert task.task is not None
    assert task.task.task == "alert_rule_task"
    assert task.task.enabled is True


@pytest.mark.django_db
def test_crontab_schedule():
    task = make()
    task.refresh_from_db()
    pt = task.task
    assert pt.crontab is not None
    assert pt.interval is None
    assert pt.crontab.minute == "*/5"


@pytest.mark.django_db
def test_interval_schedule_on_every():
    task = make(title="Every Test", execution_cycle="@every 30s")
    task.refresh_from_db()
    pt = task.task
    assert pt.interval is not None
    assert pt.interval.every == 30
    assert pt.crontab is None


@pytest.mark.django_db
def test_disable_sets_enabled_false():
    task = make()
    task.status = "disabled"
    task.save()
    task.refresh_from_db()
    assert task.task.enabled is False


@pytest.mark.django_db
def test_cycle_change_updates_schedule():
    task = make()
    task.refresh_from_db()
    task.execution_cycle = "0 * * * *"
    task.save()
    task.refresh_from_db()
    pt = task.task
    assert pt.crontab.minute == "0"
    assert pt.crontab.hour == "*"


@pytest.mark.django_db
def test_periodic_task_deleted_with_model():
    task = make(title="Delete Test")
    task.refresh_from_db()
    pt_id = task.task_id
    task.delete()
    assert not PeriodicTask.objects.filter(pk=pt_id).exists()


@pytest.mark.django_db
def test_queue_from_settings():
    task = make(title="Queue Test")
    task.refresh_from_db()
    assert task.task.queue == "test"  # from tests/settings.py CELERY_SCHEDULER


@pytest.mark.django_db
def test_crontab_uses_default_utc_timezone():
    task = make(title="Timezone Default Test")
    task.refresh_from_db()
    assert str(task.task.crontab.timezone) == "UTC"


@pytest.mark.django_db
def test_crontab_uses_instance_timezone():
    task = make(title="Timezone TW Test", timezone="Asia/Taipei")
    task.refresh_from_db()
    assert str(task.task.crontab.timezone) == "Asia/Taipei"


@pytest.mark.django_db
def test_resync_all_restores_externally_disabled_task():
    task = make(title="Resync Restore")
    task.refresh_from_db()
    # 模擬外部直接停用 PeriodicTask（例如 worker stop API）
    PeriodicTask.objects.filter(pk=task.task_id).update(enabled=False)

    result = resync_all(AlertRuleTask)

    task.refresh_from_db()
    assert task.task.enabled is True
    assert result["synced"] == 1


@pytest.mark.django_db
def test_resync_all_removes_orphan_periodic_task():
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=60, period=IntervalSchedule.SECONDS
    )
    PeriodicTask.objects.create(name="Orphan PT", task="alert_rule_task", interval=interval)

    result = resync_all(AlertRuleTask)

    assert result["removed"] == 1
    assert not PeriodicTask.objects.filter(name="Orphan PT").exists()


@pytest.mark.django_db
def test_resync_all_keeps_unrelated_periodic_tasks():
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=60, period=IntervalSchedule.SECONDS
    )
    PeriodicTask.objects.create(name="Other Service PT", task="other_task", interval=interval)

    result = resync_all(AlertRuleTask)

    assert result["removed"] == 0
    assert PeriodicTask.objects.filter(name="Other Service PT").exists()


@pytest.mark.django_db
def test_resync_all_rebuilds_detached_reference():
    # instance 的 task 參照被清空、舊 PeriodicTask 以同名殘留：
    # 必須先移除孤兒再重建，否則撞 name 唯一性約束
    task = make(title="Resync Detached")
    task.refresh_from_db()
    old_pt_id = task.task_id
    AlertRuleTask.objects.filter(pk=task.pk).update(task=None)

    result = resync_all(AlertRuleTask)

    task.refresh_from_db()
    assert task.task is not None
    assert task.task_id != old_pt_id
    assert result["removed"] == 1
    assert PeriodicTask.objects.filter(task="alert_rule_task").count() == 1


@pytest.mark.django_db
def test_reenable_sets_enabled_true():
    task = make(title="Reenable Test")
    task.status = "disabled"
    task.save()
    task.refresh_from_db()
    assert task.task.enabled is False

    task.status = "active"
    task.save()
    task.refresh_from_db()
    assert task.task.enabled is True
