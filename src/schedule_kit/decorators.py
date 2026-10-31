import inspect
from functools import wraps
from celery import shared_task
from django.apps import apps
from django.db import transaction
from django.utils import timezone
from .exceptions import CeleryKitError
from .messages import INVALID_RETURN, INVALID_SUCCESS, TASK_RAISED
from .recording import finish_record, logger, scheduler_identity


def _resolve_scheduler(name, model, task_id):
    from .models import BaseSchedulerTask

    if isinstance(model, str):
        model = apps.get_model(model)
    if model is None:
        matches = [
            m
            for m in apps.get_models()
            if issubclass(m, BaseSchedulerTask) and m.task_name == name
        ]
        model = matches[0] if len(matches) == 1 else None
    if model is None or task_id is None:
        return None
    try:
        with transaction.atomic():
            return model.objects.filter(pk=task_id).first()
    except Exception as exc:
        logger.error("Scheduler lookup failed: %s", type(exc).__name__)
        return None


def recorded_task(
    name: str,
    queue: str = None,
    *,
    scheduler_model=None,
    require_record: bool = False,
    **celery_kwargs,
):
    """Async dispatchers must set require_record=True: callbacks need a durable ID.

    The task returns ``(instance, success, message)``; ``message`` may be plain text
    or a ``schedule_kit.messages.ExecutionMessage``.
    """

    def decorator(func):
        options = {"name": name, **celery_kwargs}
        if queue is not None:
            options["queue"] = queue

        @shared_task(bind=True, **options)
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            from .models import ExecutionRecord

            bound = inspect.signature(func).bind_partial(*args, **kwargs)
            first_parameter = next(iter(inspect.signature(func).parameters), None)
            task_id = bound.arguments.get(first_parameter)
            scheduler_identity(
                None
            )  # Validate shared-project namespace before executing business code.
            scheduler = _resolve_scheduler(name, scheduler_model, task_id)
            record = ExecutionRecord(
                task_function=name,
                task_id=task_id,
                celery_task_id=self.request.id or "",
                occurred_at=timezone.now(),
                status="running",
                task_title=str(scheduler) if scheduler is not None else "",
                task_model=scheduler_identity(scheduler),
                task_created_by_id=getattr(scheduler, "created_by_id", None),
                periodic_task_id=getattr(scheduler, "task_id", None),
            )
            try:
                with transaction.atomic():
                    record.save(force_insert=True)
            except Exception as exc:
                record.pk = None
                logger.error(
                    "Local execution record creation failed: %s", type(exc).__name__
                )
                if require_record:
                    raise CeleryKitError(
                        "A durable execution record is required for this task"
                    ) from None
            try:
                result = func(*args, record_id=record.pk, **kwargs)
            except Exception as exc:
                # Class name only: exception text may contain secrets.
                finish_record(
                    record,
                    "fail",
                    TASK_RAISED.with_params(exception=type(exc).__name__),
                )
                raise
            if not (isinstance(result, tuple) and len(result) == 3):
                finish_record(record, "fail", INVALID_RETURN)
                raise CeleryKitError("Invalid scheduled task return value")
            instance, success, message = result
            if success is not None and not isinstance(success, bool):
                finish_record(record, "fail", INVALID_SUCCESS)
                raise CeleryKitError("Invalid scheduled task success value")
            if instance is not None:
                record.task_title = str(instance)
                record.task_model = scheduler_identity(instance)
                record.task_id = instance.pk
                record.task_created_by_id = getattr(instance, "created_by_id", None)
                record.periodic_task_id = getattr(instance, "task_id", None)
                if record.pk is not None:
                    try:
                        with transaction.atomic():
                            ExecutionRecord.objects.filter(pk=record.pk).update(
                                task_title=record.task_title,
                                task_model=record.task_model,
                                task_id=record.task_id,
                                task_created_by_id=record.task_created_by_id,
                                periodic_task_id=record.periodic_task_id,
                            )
                    except Exception as exc:
                        logger.error(
                            "Execution metadata update failed: %s", type(exc).__name__
                        )
            finish_record(
                record,
                "pending" if success is None else "success" if success else "fail",
                message,
            )
            if success is False:
                raise CeleryKitError("Scheduled task reported failure")
            return record.pk

        return wrapper

    return decorator
