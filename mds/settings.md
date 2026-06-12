# 設定參考

> 套件從 Django `settings.py` 的 `CELERY_SCHEDULER` 字典讀取所有參數。
> 位置：`src/schedule_kit/conf.py`

---

## CELERY_SCHEDULER

```python
# settings.py
CELERY_SCHEDULER = {
    "QUEUE_NAME":                "myservice",
    "SAFETY_MARGIN_SECONDS":     30,
    "MIN_EXPIRE_SECONDS":        60,
    "MAX_EXPIRE_SECONDS":        86400,
    "TASK_RECORD_KEEP_MAX_COUNT": 1000,
    "TASK_RECORD_KEEP_MAX_DAYS":  30,
    "PENDING_TIMEOUT_HOURS":     24,
}
```

### 參數說明

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `QUEUE_NAME` | `"celery"` | Worker 監聽的 queue 名稱，同步時寫入 `PeriodicTask` |
| `SAFETY_MARGIN_SECONDS` | `30` | expire 計算的安全邊際（秒），加到估算的執行週期上 |
| `MIN_EXPIRE_SECONDS` | `60` | expire 下限，避免高頻任務 expire 過短 |
| `MAX_EXPIRE_SECONDS` | `86400` | expire 上限（1 天），避免低頻任務 expire 過長 |
| `TASK_RECORD_KEEP_MAX_COUNT` | `1000` | 同一 `task_id` 最多保留幾筆 ExecutionRecord |
| `TASK_RECORD_KEEP_MAX_DAYS` | `30` | ExecutionRecord 最多保留幾天 |
| `PENDING_TIMEOUT_HOURS` | `24` | `pending` / `running` 狀態超過幾小時，maintenance task 自動標為 `fail` |

---

## expire_seconds 計算邏輯

```
expire = clamp(estimated_interval - SAFETY_MARGIN_SECONDS,
               MIN_EXPIRE_SECONDS,
               MAX_EXPIRE_SECONDS)
```

`estimated_interval` 由 `execution_cycle` 字串推算（見 `src/schedule_kit/utils/schedule.py`）。

---

## ExecutionRecord 清理邏輯

兩個條件獨立運作，任一滿足就刪除：

- **天數**：`start_time` 超過 `TASK_RECORD_KEEP_MAX_DAYS` 天的紀錄
- **筆數**：同一 `task_id` 超過 `TASK_RECORD_KEEP_MAX_COUNT` 筆時，刪最舊的

清理由套件的 maintenance task 執行（`src/schedule_kit/tasks/maintenance.py`），不需各服務自行實作。

---

## 必要的 Django / Celery 設定

這些不在 `CELERY_SCHEDULER`，但套件正常運作必須有：

```python
# settings.py
INSTALLED_APPS = [
    "schedule_kit",
    "django_celery_beat",
    ...
]

CELERY_BROKER_URL     = "amqp://user:pass@rabbitmq:5672/"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TIMEZONE       = "Asia/Taipei"
```

```python
# config/celery.py（各服務自建）
app = Celery("myservice")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

> `CELERY_SCHEDULER` 是套件的 namespace，與 Celery 原生設定（`CELERY_BROKER_URL` 等）分開，互不干擾。
