from datetime import timedelta

from django.utils import timezone as tz

# 本函式的 tz.now() 與 Celery schedule 內部 nowfun() 是兩次獨立的讀時鐘，
# 相差數百微秒，使 now + remaining 落在真正觸發時刻前一點點；
# 若直接截斷 microsecond 會早整整一秒。加上此邊界推過整秒邊界後再截斷。
_CLOCK_SKEW_MARGIN = timedelta(seconds=0.1)


def _remaining_from(periodic_task, anchor):
    """anchor 之後下一次觸發的剩餘時間（timedelta）；無 crontab/interval 排程時回傳 None。"""
    pt = periodic_task

    if pt.crontab:
        # remaining_delta 用 nowfun() 取得 crontab timezone 的「現在」，
        # 但 anchor 是 UTC → .day/.hour 與 nowfun() 的 .day/.hour 不同，
        # 導致日期判斷走錯分支，最終 ffwd(hour=8) apply 在 UTC 上而非 crontab 時區。
        # 將 anchor 預先轉成 crontab timezone，兩者的 .day/.hour 就能正確比較。
        anchor_in_tz = anchor.astimezone(pt.crontab.timezone)
        return pt.crontab.schedule.remaining_estimate(anchor_in_tz)

    if pt.interval:
        # interval 是純時間長度運算，沒有牆上時鐘語意，不需轉時區。
        return pt.interval.schedule.remaining_estimate(anchor)

    return None


def get_next_run_time(periodic_task):
    """Return the next scheduled run time for a PeriodicTask, or None if disabled/unset.

    回傳 aware datetime，時區固定為 UTC（與 timezone.now() 一致），不做在地化轉換。
    保證回傳值不早於「現在」。
    """
    pt = periodic_task
    if pt is None or not pt.enabled:
        return None

    now = tz.now()
    last_run = pt.last_run_at or pt.start_time or now

    remaining = _remaining_from(pt, last_run)
    if remaining is None:
        return None

    result = now + remaining + _CLOCK_SKEW_MARGIN

    # last_run_at 過期（Beat 停擺、或任務建立後長期未被執行）時，依 last_run 推算出的
    # 槽位早已過去，remaining 為負 → result 落在過去。這種任務實際上是 overdue：
    # Beat 恢復後會立刻執行並把 last_run_at 設為當下。改以「現在」為錨點重算，
    # 得到的正是 Beat 追上進度後的下一次觸發時間，且必定在未來。
    if result <= now:
        remaining = _remaining_from(pt, now)
        result = now + remaining + _CLOCK_SKEW_MARGIN

    return result.replace(microsecond=0)
