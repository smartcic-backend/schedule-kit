from django.conf import settings

_DEFAULTS = {
    "QUEUE_NAME": "celery",
    "TIMEZONE": "UTC",
    "SAFETY_MARGIN_SECONDS": 30,
    "MIN_EXPIRE_SECONDS": 60,
    "MAX_EXPIRE_SECONDS": 86400,
    "TASK_RECORD_KEEP_MAX_COUNT": 1000,
    "TASK_RECORD_KEEP_MAX_DAYS": 30,
    "PENDING_TIMEOUT_HOURS": 24,
}


def _get(key):
    config = getattr(settings, "CELERY_SCHEDULER", {})
    return config.get(key, _DEFAULTS[key])


def get_queue_name() -> str:
    return _get("QUEUE_NAME")

def get_timezone() -> str:
    return _get("TIMEZONE")

def get_safety_margin() -> int:
    return _get("SAFETY_MARGIN_SECONDS")

def get_min_expire() -> int:
    return _get("MIN_EXPIRE_SECONDS")

def get_max_expire() -> int:
    return _get("MAX_EXPIRE_SECONDS")

def get_keep_max_count() -> int:
    return _get("TASK_RECORD_KEEP_MAX_COUNT")

def get_keep_max_days() -> int:
    return _get("TASK_RECORD_KEEP_MAX_DAYS")

def get_pending_timeout_hours() -> int:
    return _get("PENDING_TIMEOUT_HOURS")
