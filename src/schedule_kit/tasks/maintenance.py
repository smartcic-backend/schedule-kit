from datetime import timedelta
from celery import shared_task
from django.utils import timezone

from ..models.execution import ExecutionRecord
from ..conf import get_keep_max_count, get_keep_max_days, get_pending_timeout_hours


@shared_task(name="schedule_kit.cleanup_execution_records")
def cleanup_execution_records():
    now = timezone.now()
    timeout_cutoff = now - timedelta(hours=get_pending_timeout_hours())

    # 超時的 pending / running → fail
    from ..api import update_record

    for record in ExecutionRecord.objects.filter(
        status__in=("pending", "running"), occurred_at__lt=timeout_cutoff
    ).iterator():
        update_record(
            record.pk, False, f"timeout: {record.status} exceeded configured limit"
        )

    from ..recording import retry_pending_main_records, shared_recording_enabled

    retry_pending_main_records()
    # Unsynced terminal outcomes are a durable retry queue, not retention candidates.
    eligible = ExecutionRecord.objects.filter(status__in=("success", "fail"))
    if shared_recording_enabled():
        eligible = eligible.filter(main_synced_at__isnull=False)

    # 超過天數上限的紀錄刪除
    cutoff_date = now - timedelta(days=get_keep_max_days())
    eligible.filter(occurred_at__lt=cutoff_date).delete()

    # 同一 task_id 超過筆數上限的刪除（保留最新的）
    max_count = get_keep_max_count()
    groups = list(eligible.order_by().values_list("task_model", "task_id").distinct())
    for task_model, task_id in groups:
        records = eligible.filter(task_model=task_model, task_id=task_id)
        keep_ids = list(
            records.order_by("-occurred_at", "-id").values_list("id", flat=True)[
                :max_count
            ]
        )
        records.exclude(id__in=keep_ids).delete()
