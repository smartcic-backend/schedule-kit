import json
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from ..conf import get_queue_name, get_safety_margin, get_min_expire, get_max_expire
from ..utils.cron import get_or_create_schedule, estimate_period_seconds


def _calc_expire(expr: str) -> int:
    period = estimate_period_seconds(expr)
    expire = period - get_safety_margin()
    return max(get_min_expire(), min(get_max_expire(), expire))


def sync_to_periodic_task(instance, created: bool) -> None:
    schedule, schedule_type = get_or_create_schedule(
        instance.execution_cycle, instance.timezone
    )
    expire = _calc_expire(instance.execution_cycle)
    enabled = instance.status == "active"
    args = json.dumps(instance.get_task_args())
    now = timezone.now()

    if instance.task_id is None:
        kwargs = {
            "name": instance.title,
            "task": instance.task_name,
            "queue": get_queue_name(),
            "args": args,
            "expire_seconds": expire,
            "enabled": enabled,
            "start_time": now,
        }
        if schedule_type == "crontab":
            kwargs["crontab"] = schedule
        else:
            kwargs["interval"] = schedule

        pt = PeriodicTask.objects.create(**kwargs)
        # bypass signals to avoid recursion
        type(instance).objects.filter(pk=instance.pk).update(task=pt)
        instance.task = pt
        return

    pt = instance.task
    old_enabled = pt.enabled
    old_cycle = getattr(instance, "_old_execution_cycle", None)
    cycle_changed = old_cycle is not None and old_cycle != instance.execution_cycle

    if schedule_type == "crontab":
        pt.crontab = schedule
        pt.interval = None
    else:
        pt.interval = schedule
        pt.crontab = None

    pt.name = instance.title
    pt.task = instance.task_name
    pt.queue = get_queue_name()
    pt.args = args
    pt.expire_seconds = expire
    pt.enabled = enabled

    # 停用→啟用：跳過停用期間，從現在開始計算下次執行
    # 排程定義改變：以新排程從現在重新計算
    if (not old_enabled and enabled) or cycle_changed:
        pt.last_run_at = now

    pt.save()


def delete_periodic_task(instance) -> None:
    if instance.task_id is not None:
        try:
            instance.task.delete()
        except Exception:
            pass
