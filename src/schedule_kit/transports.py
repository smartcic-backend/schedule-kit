"""How durable terminal records are projected to the main project's execution table.

`write_main_record()` calls ``publish()`` inside its transaction and row lock, so a
transport must either finish its write in that transaction or raise. Only ``db`` is
implemented; a broker-based transport can be added without changing callers.
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

MAIN_TABLE = "celery_skdl_executionrecord"
I18N_COLUMNS = ("message_code", "message_params", "message_i18n")
COLUMN_CACHE_SECONDS = 300

# (expires_at monotonic, has_i18n_columns); only successful detections are cached.
_main_columns_cache = None
_legacy_schema_warned = False


def reset_main_columns_cache():
    global _main_columns_cache, _legacy_schema_warned
    _main_columns_cache = None
    _legacy_schema_warned = False


class MainRecordTransport(ABC):
    @abstractmethod
    def publish(self, durable) -> None:
        """Write one terminal record; raise to roll back the caller's sync marker."""

    def cleanup(self, record) -> None:
        """Apply retention for `record`'s scheduler on the main side (optional)."""


def _forget_main_columns():
    global _main_columns_cache
    _main_columns_cache = None


def _main_table_has_i18n_columns() -> bool:
    global _main_columns_cache
    now = time.monotonic()
    if _main_columns_cache is not None and _main_columns_cache[0] > now:
        return _main_columns_cache[1]
    # Raises if the table is missing; nothing is cached so the next attempt re-checks.
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(
                cursor, MAIN_TABLE
            )
        }
    if not columns:
        raise DatabaseError(f"Main execution table {MAIN_TABLE} was not found")
    has_i18n = all(name in columns for name in I18N_COLUMNS)
    _main_columns_cache = (now + COLUMN_CACHE_SECONDS, has_i18n)
    return has_i18n


class DbTransport(MainRecordTransport):
    """INSERT directly into the main project's table in the shared database."""

    def publish(self, durable) -> None:
        columns = [
            "task_title", "task_function", "task_model", "task_id",
            "task_created_by_id", "result", "start_time", "end_time", "message",
            "periodic_task_id",
        ]
        values = [
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
        ]
        placeholders = ["%s"] * len(columns)
        with_i18n = _main_table_has_i18n_columns()
        if with_i18n:
            json_placeholder = "%s::jsonb" if connection.vendor == "postgresql" else "%s"
            columns += list(I18N_COLUMNS)
            values += [
                durable.message_code,
                _json(durable.message_params),
                _json(durable.message_i18n),
            ]
            placeholders += ["%s", json_placeholder, json_placeholder]
        else:
            _warn_legacy_schema_once()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {MAIN_TABLE} ({', '.join(columns)}) "
                    f"VALUES ({', '.join(placeholders)})",
                    values,
                )
        except Exception:
            if with_i18n:
                # The columns may have been removed (e.g. 0042 rolled back): re-detect
                # on the next retry instead of failing until the cache expires.
                _forget_main_columns()
            raise

    def cleanup(self, record) -> None:
        # Same per-scheduler policy as the owner; cleanup cannot undo the insert.
        count = max(0, int(getattr(settings, "TASK_RECORD_KEEP_MAX_COUNT", 1000)))
        days = max(0, int(getattr(settings, "TASK_RECORD_KEEP_MAX_DAYS", 60)))
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {MAIN_TABLE} WHERE task_model = %s "
                    "AND task_id = %s AND start_time < %s",
                    [
                        record.task_model,
                        record.task_id,
                        timezone.now() - timedelta(days=days),
                    ],
                )
                cursor.execute(
                    f"DELETE FROM {MAIN_TABLE} WHERE id IN ("
                    f"SELECT id FROM {MAIN_TABLE} WHERE task_model = %s "
                    "AND task_id = %s ORDER BY start_time DESC, id DESC LIMIT 2147483647 OFFSET %s)",
                    [record.task_model, record.task_id, count],
                )


def _json(value):
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _warn_legacy_schema_once():
    global _legacy_schema_warned
    if not _legacy_schema_warned:
        _legacy_schema_warned = True
        logger.warning(
            "Main execution table has no message_code/message_params/message_i18n "
            "columns (oivsion360 celery_skdl.0042 not applied); writing legacy columns only"
        )


TRANSPORTS = {"db": DbTransport}
