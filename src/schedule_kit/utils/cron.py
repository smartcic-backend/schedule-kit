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

# 欄位順序與主專案 oivsion360 一致：分 時 星期 日 月
# （不是標準 cron 的「分 時 日 月 星期」）。
CRONTAB_FIELDS = ('minute', 'hour', 'day_of_week', 'day_of_month', 'month_of_year')


def split_crontab(expr: str) -> dict:
    """把 crontab 字串依 CRONTAB_FIELDS 順序拆成 celery crontab 參數。"""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(
            f"crontab 必須是 5 個欄位（分 時 星期 日 月），收到 {len(fields)} 個：{expr!r}"
        )
    return dict(zip(CRONTAB_FIELDS, fields))


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
    fields = split_crontab(expr)
    try:
        crontab(**fields)
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

    schedule, _ = CrontabSchedule.objects.get_or_create(
        **split_crontab(expr),
        timezone=timezone,
    )
    return schedule, 'crontab'
