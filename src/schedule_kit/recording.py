"""Durable terminal records with atomic, idempotent main-project projection."""

import logging
import re
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .conf import get_execution_transport

logger = logging.getLogger(__name__)


def shared_recording_enabled():
    return getattr(settings, "CELERY_SCHEDULER", {}).get(
        "WRITE_MAIN_EXECUTION_RECORDS", False
    )


def _execution_source():
    return getattr(settings, "CELERY_SCHEDULER", {}).get("EXECUTION_SOURCE", "")


def own_records(queryset):
    """Limit ExecutionRecords to this project's source (the local table may be shared).

    Shared recording: only `task_model` starting with "<EXECUTION_SOURCE>:".
    Otherwise: records without a source prefix, plus this project's prefix if set.
    """
    source = _execution_source()
    # LIKE-based startswith is case-insensitive on SQLite. Match the same source
    # spelling as Python's startswith in callback and main-projection checks.
    source_filter = Q(task_model__regex=rf"^{re.escape(str(source))}:")
    if shared_recording_enabled():
        return queryset.filter(source_filter)
    own = ~Q(task_model__contains=":")
    if source:
        own |= source_filter
    return queryset.filter(own)


def is_foreign_record(record) -> bool:
    """True when the record carries another project's source prefix."""
    source = _execution_source()
    return ":" in record.task_model and not (
        source and record.task_model.startswith(f"{source}:")
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
    if shared_recording_enabled():
        get_execution_transport()  # Fail before business code on an unknown transport.
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
        transport = get_execution_transport()
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
            transport.publish(durable)
            durable.main_synced_at = timezone.now()
            durable.save(update_fields=["main_synced_at"])
            record = durable
    except Exception as exc:
        # Roll back the main INSERT as well if persisting the marker fails.
        logger.error("Main execution record write failed: %s", type(exc).__name__)
        return
    try:
        transport.cleanup(record)
    except Exception as exc:
        logger.error("Main execution record cleanup failed: %s", type(exc).__name__)


def finish_record(record, status, message):
    """Persist the terminal status; `message` is an ExecutionMessage or plain text."""
    from .messages import message_fields
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
                **message_fields(message),
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
            own_records(
                ExecutionRecord.objects.filter(
                    status__in=("success", "fail"), main_synced_at=None
                )
            )
            .values_list("pk", flat=True)
            .iterator()
        )
        for record_id in pending_ids:
            write_main_record(ExecutionRecord(pk=record_id))

