import re
from celery.schedules import crontab

_UNIT_SECONDS = {
    'w': 604800,
    'd': 86400,
    'h': 3600,
    'm': 60,
    's': 1,
}
_EVERY_PATTERN = re.compile(r'^(\d+[wdhms])+$')
_SEGMENT_PATTERN = re.compile(r'(\d+)([wdhms])')


def is_every(expr: str) -> bool:
    return expr.startswith("@every ")


def parse_every_seconds(expr: str) -> int:
    duration = expr[len("@every "):].strip()
    if not duration or not _EVERY_PATTERN.match(duration):
        raise ValueError(
            f"@every 格式無效：{expr!r}，範例：`@every 30s`、`@every 1h30m`"
        )
    total = sum(int(n) * _UNIT_SECONDS[u] for n, u in _SEGMENT_PATTERN.findall(duration))
    if total <= 0:
        raise ValueError(f"@every 時間必須 > 0：{expr!r}")
    return total


def validate_crontab(expr: str) -> None:
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(
            f"crontab 必須是 5 個欄位，收到 {len(fields)} 個：{expr!r}"
        )
    minute, hour, dom, month, dow = fields
    try:
        crontab(minute=minute, hour=hour,
                day_of_month=dom, month_of_year=month, day_of_week=dow)
    except Exception:
        raise ValueError(
            f"crontab 格式不符合 Celery 規範：{expr!r}"
            "（例如 `0/2` 不支援，請改用 `*/2`）"
        )


def estimate_period_seconds(expr: str) -> int:
    if is_every(expr):
        return parse_every_seconds(expr)
    fields = expr.split()
    minute, hour = fields[0], fields[1]
    if minute == '*':
        return 60
    if minute.startswith('*/'):
        return int(minute[2:]) * 60
    if hour == '*':
        return 3600
    if hour.startswith('*/'):
        return int(hour[2:]) * 3600
    return 86400


def get_or_create_schedule(expr: str, timezone: str = "UTC"):
    from django_celery_beat.models import CrontabSchedule, IntervalSchedule

    if is_every(expr):
        seconds = parse_every_seconds(expr)
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=seconds,
            period=IntervalSchedule.SECONDS,
        )
        return schedule, 'interval'

    fields = expr.split()
    minute, hour, dom, month, dow = fields
    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute=minute,
        hour=hour,
        day_of_month=dom,
        month_of_year=month,
        day_of_week=dow,
        timezone=timezone,
    )
    return schedule, 'crontab'
