import uuid

import pytest
from datetime import timedelta
from django.utils import timezone
from schedule_kit.models import ExecutionRecord
from schedule_kit.tasks.maintenance import cleanup_execution_records


def U(n: int) -> uuid.UUID:
    """測試用固定 UUID，方便以小整數區分不同排程。"""
    return uuid.UUID(int=n)


def make_record(task_id=U(1), status="success", days_ago=0):
    return ExecutionRecord.objects.create(
        task_function="test_task",
        task_id=task_id,
        status=status,
        occurred_at=timezone.now() - timedelta(days=days_ago, seconds=1),
    )


@pytest.mark.django_db
def test_cleanup_removes_over_count_limit():
    # 建立 15 筆，超過測試設定的 max_count=10
    for i in range(15):
        make_record(task_id=U(1))

    cleanup_execution_records()

    assert ExecutionRecord.objects.filter(task_id=U(1)).count() == 10


@pytest.mark.django_db
def test_cleanup_keeps_newest_records():
    now = timezone.now()
    for i in range(12):
        ExecutionRecord.objects.create(
            task_function="test_task",
            task_id=U(2),
            status="success",
            occurred_at=now - timedelta(minutes=i),
            message=f"record {i}",
        )

    cleanup_execution_records()

    remaining = list(
        ExecutionRecord.objects.filter(task_id=U(2))
        .order_by("-occurred_at")
        .values_list("message", flat=True)
    )
    assert len(remaining) == 10
    assert "record 0" in remaining  # 最新的應該保留


@pytest.mark.django_db
def test_cleanup_removes_old_records():
    make_record(task_id=U(3), days_ago=8)   # 超過 7 天上限
    make_record(task_id=U(3), days_ago=1)   # 在限制內

    cleanup_execution_records()

    assert ExecutionRecord.objects.filter(task_id=U(3)).count() == 1


@pytest.mark.django_db
def test_cleanup_marks_stale_pending_as_fail():
    # 建立超時的 pending（2 小時前，超過測試設定的 1 小時）
    r = make_record(task_id=U(4), status="pending")
    r.occurred_at = timezone.now() - timedelta(hours=2)
    r.save(update_fields=["occurred_at"])

    cleanup_execution_records()

    r.refresh_from_db()
    assert r.status == "fail"
    assert "timeout" in r.message


@pytest.mark.django_db
def test_cleanup_leaves_recent_pending_alone():
    r = make_record(task_id=U(5), status="pending")  # 剛建立的 pending

    cleanup_execution_records()

    r.refresh_from_db()
    assert r.status == "pending"


@pytest.mark.django_db
def test_cleanup_marks_stale_running_as_fail():
    r = make_record(task_id=U(6), status="running")
    r.occurred_at = timezone.now() - timedelta(hours=2)
    r.save(update_fields=["occurred_at"])

    cleanup_execution_records()

    r.refresh_from_db()
    assert r.status == "fail"
    assert "timeout" in r.message
