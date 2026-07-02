from django.db.models.signals import post_delete, post_save, pre_save
from .models.base import BaseSchedulerTask


def _get_all_subclasses(cls):
    result = []
    for sub in cls.__subclasses__():
        if not sub._meta.abstract:
            result.append(sub)
        result.extend(_get_all_subclasses(sub))
    return result


def _pre_save_handler(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
            instance._old_execution_cycle = old.execution_cycle
            instance._old_enable = old.enable
        except sender.DoesNotExist:
            instance._old_execution_cycle = None
            instance._old_enable = None
    else:
        instance._old_execution_cycle = None
        instance._old_enable = None


def _post_save_handler(sender, instance, created, **kwargs):
    from .services.sync import sync_to_periodic_task
    sync_to_periodic_task(instance, created)


def _post_delete_handler(sender, instance, **kwargs):
    from .services.sync import delete_periodic_task
    delete_periodic_task(instance)


def register_signals():
    for subclass in _get_all_subclasses(BaseSchedulerTask):
        uid = f"schedule_kit.{subclass.__name__}"
        pre_save.connect(_pre_save_handler, sender=subclass, weak=False,
                         dispatch_uid=f"{uid}.pre_save")
        post_save.connect(_post_save_handler, sender=subclass, weak=False,
                          dispatch_uid=f"{uid}.post_save")
        post_delete.connect(_post_delete_handler, sender=subclass, weak=False,
                            dispatch_uid=f"{uid}.post_delete")
