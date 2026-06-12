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
    for status in ("pending", "running"):
        ExecutionRecord.objects.filter(
            status=status,
            occurred_at__lt=timeout_cutoff,
        ).update(
            status="fail",
            end_time=now,
            message=f"timeout: {status} exceeded configured limit",
        )

    # 超過天數上限的紀錄刪除
    cutoff_date = now - timedelta(days=get_keep_max_days())
    ExecutionRecord.objects.filter(occurred_at__lt=cutoff_date).delete()

    # 同一 task_id 超過筆數上限的刪除（保留最新的）
    max_count = get_keep_max_count()
    task_ids = list(
        ExecutionRecord.objects.values_list("task_id", flat=True).distinct()
    )
    for task_id in task_ids:
        keep_ids = list(
            ExecutionRecord.objects.filter(task_id=task_id)
            .order_by("-occurred_at")
            .values_list("id", flat=True)[:max_count]
        )
        ExecutionRecord.objects.filter(task_id=task_id).exclude(
            id__in=keep_ids
        ).delete()
