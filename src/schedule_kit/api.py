from django.db import transaction
from .models.execution import ExecutionRecord
from .recording import finish_record, write_main_record


def update_record(record_id: int, success: bool, message: str = "") -> None:
    if not isinstance(success, bool):
        raise ValueError("success must be a bool")
    with transaction.atomic():
        record = (
            ExecutionRecord.objects.select_for_update().filter(pk=record_id).first()
        )
        if record is not None and record.status in ("running", "pending"):
            finish_record(record, "success" if success else "fail", message)
        elif record is not None:
            write_main_record(
                record
            )  # Retry a failed main projection without changing the terminal result.
