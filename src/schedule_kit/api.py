from django.utils import timezone
from .models.execution import ExecutionRecord


def update_record(record_id: int, success: bool, message: str = "") -> None:
    ExecutionRecord.objects.filter(pk=record_id).update(
        status="success" if success else "fail",
        end_time=timezone.now(),
        message=message,
    )
