import json
from django.utils import timezone
from celery import shared_task


def recorded_task(name: str, queue: str = None, **celery_kwargs):
    def decorator(func):
        _task_kwargs = {"name": name, **celery_kwargs}
        if queue is not None:
            _task_kwargs["queue"] = queue

        @shared_task(bind=True, **_task_kwargs)
        def wrapper(self, *args, **kwargs):
            from .models.execution import ExecutionRecord
            from django_celery_beat.models import PeriodicTask

            task_id_arg = args[0] if args else kwargs.get("task_id")
            occurred_at = timezone.now()

            pt = None
            try:
                pt = PeriodicTask.objects.filter(
                    task=name,
                    args=json.dumps([task_id_arg], default=str),
                ).first()
            except Exception:
                pass

            record = ExecutionRecord.objects.create(
                task_function=name,
                task_id=task_id_arg,
                celery_task_id=self.request.id or "",
                status="running",
                occurred_at=occurred_at,
                periodic_task=pt,
            )

            try:
                result = func(*args, record_id=record.id, **kwargs)
            except Exception as e:
                record.status = "fail"
                record.end_time = timezone.now()
                record.message = str(e)
                record.save()
                raise

            end_time = timezone.now()

            if not (isinstance(result, tuple) and len(result) == 3):
                record.status = "fail"
                record.end_time = end_time
                record.message = (
                    f"@recorded_task: {name} 必須回傳 (instance, success, message)"
                )
                record.save()
                return record.id

            instance, success, message = result

            record.task_title = str(instance) if instance else ""
            record.task_model = type(instance).__name__ if instance else ""
            record.task_id = instance.pk if instance else task_id_arg
            record.task_created_by_id = getattr(
                getattr(instance, "created_by", None), "id", None
            )
            record.message = message or ""
            record.end_time = end_time

            if success is None:
                record.status = "pending"
            elif success:
                record.status = "success"
            else:
                record.status = "fail"

            record.save()
            return record.id

        return wrapper
    return decorator
