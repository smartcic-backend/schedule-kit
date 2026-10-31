import logging

from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django_celery_beat.models import PeriodicTask

from .models.base import BaseSchedulerTask

logger = logging.getLogger(__name__)


def _get_all_subclasses(cls):
    result = []
    for sub in cls.__subclasses__():
        if not sub._meta.abstract:
            result.append(sub)
        result.extend(_get_all_subclasses(sub))
    return result


def get_scheduler_models():
    """回傳所有非 abstract 的 BaseSchedulerTask 子類。"""
    return _get_all_subclasses(BaseSchedulerTask)


def _pre_save_handler(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
            instance._old_execution_cycle = old.execution_cycle
            instance._old_status = old.status
        except sender.DoesNotExist:
            instance._old_execution_cycle = None
            instance._old_status = None
    else:
        instance._old_execution_cycle = None
        instance._old_status = None


def _post_save_handler(sender, instance, created, **kwargs):
    from .services.sync import sync_to_periodic_task

    sync_to_periodic_task(instance, created)


def _post_delete_handler(sender, instance, **kwargs):
    from .services.sync import delete_periodic_task

    delete_periodic_task(instance)


def _periodic_task_pre_delete_handler(sender, instance, **kwargs):
    """直接刪除仍被排程關聯的 PeriodicTask 時發出警告。

    排程的 task 外鍵為 SET_NULL：PeriodicTask 被刪除後排程本身仍在，
    但 task 變成 None，beat 不再執行，畫面上卻看不出異常。
    由排程刪除連帶刪除 PeriodicTask 時，排程已不存在，不會觸發警告。
    """
    for model in get_scheduler_models():
        detached = list(
            model.objects.filter(task_id=instance.pk).values_list("pk", flat=True)
        )
        if detached:
            logger.warning(
                "PeriodicTask %s (id=%s) 被刪除，%s %s 將失去排程而不再執行；"
                "可呼叫 resync_all(%s) 重建",
                instance.name,
                instance.pk,
                model._meta.label,
                detached,
                model.__name__,
            )


def register_signals():
    for subclass in get_scheduler_models():
        # 以 app_label.model_name 區分，避免不同 app 的同名 model 互相覆蓋 signal
        uid = f"schedule_kit.{subclass._meta.label_lower}"
        pre_save.connect(
            _pre_save_handler,
            sender=subclass,
            weak=False,
            dispatch_uid=f"{uid}.pre_save",
        )
        post_save.connect(
            _post_save_handler,
            sender=subclass,
            weak=False,
            dispatch_uid=f"{uid}.post_save",
        )
        post_delete.connect(
            _post_delete_handler,
            sender=subclass,
            weak=False,
            dispatch_uid=f"{uid}.post_delete",
        )
    pre_delete.connect(
        _periodic_task_pre_delete_handler,
        sender=PeriodicTask,
        weak=False,
        dispatch_uid="schedule_kit.periodictask.pre_delete",
    )


# The main project's ORM is not installed in child services. Its FK still needs
# the same cascade cleanup before deleting a shared PeriodicTask.
def _delete_main_records(sender, instance, using, **kwargs):
    from django.conf import settings
    from django.db import connections

    if not getattr(settings, "CELERY_SCHEDULER", {}).get(
        "WRITE_MAIN_EXECUTION_RECORDS", False
    ):
        return
    with connections[using].cursor() as cursor:
        cursor.execute(
            "DELETE FROM celery_skdl_executionrecord WHERE periodic_task_id = %s",
            [instance.pk],
        )


pre_delete.connect(
    _delete_main_records,
    sender=PeriodicTask,
    weak=False,
    dispatch_uid="schedule_kit.delete_main_records",
)
