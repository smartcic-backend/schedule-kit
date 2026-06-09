from datetime import timedelta

from django.utils import timezone as tz


def get_next_run_time(periodic_task):
    """Return the next scheduled run time for a PeriodicTask, or None if disabled/unset."""
    pt = periodic_task
    if pt is None or not pt.enabled:
        return None

    now = tz.now()
    last_run = pt.last_run_at or pt.start_time or now

    if pt.crontab:
        # remaining_delta 用 nowfun() 取得 crontab timezone 的「現在」，
        # 但 last_run_at 是 UTC → .day/.hour 與 nowfun() 的 .day/.hour 不同，
        # 導致日期判斷走錯分支，最終 ffwd(hour=8) apply 在 UTC 上而非 crontab 時區。
        # 將 last_run 預先轉成 crontab timezone，兩者的 .day/.hour 就能正確比較。
        sched = pt.crontab.schedule
        last_run_in_tz = last_run.astimezone(pt.crontab.timezone)
        remaining = sched.remaining_estimate(last_run_in_tz)
    elif pt.interval:
        sched = pt.interval.schedule
        remaining = sched.remaining_estimate(last_run)
    else:
        return None

    result = now + remaining + timedelta(seconds=0.1)
    return result.replace(microsecond=0)
