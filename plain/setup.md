# 設定與接入

> 套件設定與 Celery 本身的設定是分開的。套件負責兩條路——①「排程定義 → PeriodicTask」、
> ②「執行觀測」（執行紀錄）——並自動讀取 `CELERY_SCHEDULER`；
> Celery 基礎建設（broker、beat scheduler、app）由各服務自備。

---

## 設定介面

各微服務在自己的 `settings.py` 填入：

```python
CELERY_SCHEDULER = {
    "QUEUE_NAME": "myservice",         # Worker 監聽的 queue 名稱
    "TIMEZONE": "Asia/Taipei",         # 排程時區
    "SAFETY_MARGIN_SECONDS": 30,       # expire 計算的安全邊際（秒）
    "MIN_EXPIRE_SECONDS": 60,          # expire 下限
    "MAX_EXPIRE_SECONDS": 86400,       # expire 上限（1 天）
    # 執行紀錄保留上限（見 execution.md）
    "TASK_RECORD_KEEP_MAX_COUNT": 1000,
    "TASK_RECORD_KEEP_MAX_DAYS": 30,
}
```

> **為什麼套件設定和 Celery 設定分開**：
> `CELERY_BROKER_URL` 等是 Celery 原生設定，各服務本來就需要自己設，套件不介入。
> `CELERY_SCHEDULER` 是套件額外的參數，用獨立的 namespace 避免和 Celery 原生設定混在一起。

Broker URL 沿用 Celery 原有的 `CELERY_BROKER_URL`（環境變數），不重複設定。

---

## 設定責任範圍

### 套件負責（自動）

加入 `INSTALLED_APPS` 後，`AppConfig.ready()` 自動觸發：
- signal 自動掛載到所有 `BaseSchedulerTask` 子類
- 從 `CELERY_SCHEDULER` 讀取 queue name、timezone、expire 參數

只要 model 存檔，套件自動同步到 `PeriodicTask`，不需額外呼叫任何函式。

### 各服務負責（必須自備）

```python
# config/celery.py（各服務自己建）
app = Celery("myservice")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

```python
# settings.py（各服務必填）
CELERY_BROKER_URL     = "amqp://user:pass@rabbitmq:5672/"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TIMEZONE       = "Asia/Taipei"
```

> **為什麼各服務需要自己建 `config/celery.py`**：
> Celery app 是整個服務的核心實例，要掛在這個服務的 broker、用這個服務的設定。
> 套件只是 Django app，不應該持有 Celery app 實例，那是各服務自己的基礎建設。

> **為什麼用 `DatabaseScheduler`**：
> `django_celery_beat` 的 `DatabaseScheduler` 讓 Beat 從 DB 讀排程，
> 這樣套件寫進 `PeriodicTask` 的變更才能即時生效，不需要重啟 Beat。

### 設定責任總覽

| 項目 | 誰設定 | 自動？ |
|------|--------|--------|
| `INSTALLED_APPS` 加套件 | 各服務 | 加了就自動觸發 `ready()` |
| `CELERY_SCHEDULER = {...}` | 各服務 | 套件自動讀取 |
| `CELERY_BROKER_URL` | 各服務 | Celery 原生設定，各服務自填 |
| `CELERY_BEAT_SCHEDULER` | 各服務 | 各服務自填 |
| `config/celery.py` Celery app | 各服務 | 各服務自建 |
| signal 掛載 | **套件自動** | ✓ |
| PeriodicTask 同步 | **套件自動** | ✓ |
| expire_seconds 計算 | **套件自動** | ✓ |

---

## 各微服務接入步驟

1. `pip install schedule-kit`
2. 確認服務已有 `config/celery.py` 的 Celery app
3. 在 `settings.py` 填入 `CELERY_BROKER_URL`、`CELERY_BEAT_SCHEDULER`、`CELERY_TIMEZONE`
4. 在 `settings.py` 填入 `CELERY_SCHEDULER = {...}`
5. 加入 `INSTALLED_APPS = ["schedule_kit", "django_celery_beat", ...]`
6. 繼承 `BaseSchedulerTask` 建立 task model，加入業務欄位
7. 繼承 `BaseSchedulerSerializer` 建立 serializer，加入業務驗證
8. 自行定義 `@recorded_task(name=task_name)` 函式，實作業務邏輯
9. `manage.py migrate`

> 步驟 9 的 `migrate` 會自動建立 `schedule_kit_executionrecord` 和
> `django_celery_beat_periodictask` 等所需的表，不需要手動建立。

---

## 情境範例：AlertRule 排程

以「CPU 超過閾值送 mail」為例，說明各層分工：

```python
# Model：存什麼設定（業務欄位由各服務多重繼承帶入）
class AlertRuleTask(ProjectBaseModel, BaseSchedulerTask):
    task_name     = "alert_rule_task"
    cpu_threshold = models.FloatField()        # 業務欄位，套件不管
    target_host   = models.CharField(...)      # 業務欄位，套件不管

    def get_task_args(self) -> list:
        return [self.id]                       # Beat dispatch 時帶入的參數


# Serializer：驗證輸入（業務驗證各服務自己加）
class AlertRuleTaskSerializer(BaseSchedulerSerializer):
    class Meta:
        model  = AlertRuleTask
        fields = "__all__"

    def validate_cpu_threshold(self, value):
        if not (0 < value <= 100):
            raise serializers.ValidationError("閾值必須在 1～100 之間")
        return value


# Task：業務邏輯各服務自定；@recorded_task 自動寫執行紀錄
@recorded_task(name="alert_rule_task", queue="myservice")
def alert_rule_task(task_id: int):
    task = AlertRuleTask.objects.get(id=task_id)   # 用 id 從 DB 拿最新資料
    current_cpu = get_cpu_usage(task.target_host)
    over = current_cpu >= task.cpu_threshold
    return task, True, f"cpu={current_cpu} over={over}"  # (instance, success, message)
```

> `@recorded_task` 是套件提供的合體裝飾器，同時處理 Celery task 的註冊與執行紀錄的寫入。
> 不需要分開寫 `@record` + `@shared_task`。

整體流程：

```
AlertRuleTask.save()
  → signal → PeriodicTask 同步（套件）
    → Beat 到時間 → 把 task_id 推進 queue
      → Worker 執行 alert_rule_task(task_id)
        → 讀 Model 設定 → 量 CPU → 超閾值 → 送 mail（各服務邏輯）
          → 回傳 (instance, success, message) → 套件寫 ExecutionRecord
```
