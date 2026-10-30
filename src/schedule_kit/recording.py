"""Durable terminal records with atomic, idempotent main-project projection."""

import logging
import re
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def shared_recording_enabled():
    return getattr(settings, "CELERY_SCHEDULER", {}).get(
        "WRITE_MAIN_EXECUTION_RECORDS", False
    )


def scheduler_identity(instance):
    config = getattr(settings, "CELERY_SCHEDULER", {})
    source = config.get("EXECUTION_SOURCE", "")
    if shared_recording_enabled() and (
        not isinstance(source, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", source)
    ):
        raise ImproperlyConfigured(
            "CELERY_SCHEDULER.EXECUTION_SOURCE must be a stable, globally unique project name "
            "(1-80 letters/digits/._-) when WRITE_MAIN_EXECUTION_RECORDS=True."
        )
    label = instance._meta.label if instance is not None else ""
    identity = f"{source}:{label}" if source and label else label
    if len(identity) > 255:
        raise ImproperlyConfigured(
            "Execution source and model label exceed the task_model limit of 255 characters"
        )
    return identity


def write_main_record(record):
    from .models import ExecutionRecord

    if not shared_recording_enabled():
        return
    if record.pk is None:
        logger.error(
            "Main execution record deferred: no durable local execution record"
        )
        return
    try:
        with transaction.atomic():
            # The row lock, main INSERT and sync marker share one database transaction.
            # A callback/retry cannot publish this execution twice.
            durable = ExecutionRecord.objects.select_for_update().get(pk=record.pk)
            if (
                durable.status not in ("success", "fail")
                or durable.main_synced_at is not None
            ):
                return
            if (
                durable.task_id is None
                or not durable.task_model
                or durable.task_created_by_id is None
            ):
                logger.error(
                    "Main execution record deferred: scheduler identity is incomplete"
                )
                return
            source = getattr(settings, "CELERY_SCHEDULER", {}).get(
                "EXECUTION_SOURCE", ""
            )
            if not source or not durable.task_model.startswith(source + ":"):
                logger.error(
                    "Main execution record deferred: execution source does not match stored identity"
                )
                return
            _insert_main_record(durable)
            durable.main_synced_at = timezone.now()
            durable.save(update_fields=["main_synced_at"])
            record = durable
    except Exception as exc:
        # Roll back the main INSERT as well if persisting the marker fails.
        logger.error("Main execution record write failed: %s", type(exc).__name__)
        return
    try:
        # Same per-scheduler policy as the owner; cleanup cannot undo the insert.
        count = max(0, int(getattr(settings, "TASK_RECORD_KEEP_MAX_COUNT", 1000)))
        days = max(0, int(getattr(settings, "TASK_RECORD_KEEP_MAX_DAYS", 60)))
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM celery_skdl_executionrecord WHERE task_model = %s "
                    "AND task_id = %s AND start_time < %s",
                    [
                        record.task_model,
                        record.task_id,
                        timezone.now() - timedelta(days=days),
                    ],
                )
                cursor.execute(
                    "DELETE FROM celery_skdl_executionrecord WHERE id IN ("
                    "SELECT id FROM celery_skdl_executionrecord WHERE task_model = %s "
                    "AND task_id = %s ORDER BY start_time DESC, id DESC LIMIT 2147483647 OFFSET %s)",
                    [record.task_model, record.task_id, count],
                )
    except Exception as exc:
        logger.error("Main execution record cleanup failed: %s", type(exc).__name__)


def finish_record(record, status, message):
    from .models import ExecutionRecord

    if record.pk is None:
        logger.error(
            "Execution completion not persisted: no durable local execution record"
        )
        return
    try:
        with transaction.atomic():
            ExecutionRecord.objects.filter(
                pk=record.pk, status__in=("running", "pending")
            ).update(
                status=status,
                end_time=timezone.now(),
                message=str(message or "")[:4000],
            )
    except Exception as exc:
        # Never publish an outcome that was not durably recorded locally.
        logger.error("Local execution record update failed: %s", type(exc).__name__)
        return
    # Reload under lock inside the publisher: a fast callback may already have
    # committed a different terminal result. Publish that stored result only.
    write_main_record(record)


def retry_pending_main_records():
    from .models import ExecutionRecord

    if shared_recording_enabled():
        pending_ids = (
            ExecutionRecord.objects.filter(
                status__in=("success", "fail"), main_synced_at=None
            )
            .values_list("pk", flat=True)
            .iterator()
        )
        for record_id in pending_ids:
            write_main_record(ExecutionRecord(pk=record_id))


def _insert_main_record(durable):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO celery_skdl_executionrecord "
            "(task_title, task_function, task_model, task_id, task_created_by_id, "
            "result, start_time, end_time, message, periodic_task_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                durable.task_title[:255],
                durable.task_function[:255],
                durable.task_model,
                durable.task_id,
                durable.task_created_by_id,
                durable.status,
                durable.occurred_at,
                durable.end_time,
                durable.message[:4000],
                durable.periodic_task_id,
            ],
        )
