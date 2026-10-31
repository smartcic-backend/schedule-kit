from django.db import transaction
from .models.execution import ExecutionRecord
from .messages import ExecutionMessage
from .recording import finish_record, is_foreign_record, logger, write_main_record


def update_record(
    record_id: int, success: bool, message: ExecutionMessage | str = ""
) -> None:
    """Complete a pending/running record from an async callback."""
    if not isinstance(success, bool):
        raise ValueError("success must be a bool")
    with transaction.atomic():
        record = (
            ExecutionRecord.objects.select_for_update().filter(pk=record_id).first()
        )
        if record is not None and is_foreign_record(record):
            # The local table may be shared: never complete another project's record.
            logger.warning(
                "update_record ignored record %s: it belongs to another execution source",
                record_id,
            )
        elif record is not None and record.status in ("running", "pending"):
            finish_record(record, "success" if success else "fail", message)
        elif record is not None:
            write_main_record(
                record
            )  # Retry a failed main projection without changing the terminal result.
