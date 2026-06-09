# BaseSchedulerTask 最基礎 Model 需求

> 這個 model **只管排程**，其他一律不碰（業務欄位、Email 通知、broker/queue 設定都不進來）。
> 排程用**單一欄位** `execution_cycle` 當代表，存原始字串；
> **格式判讀與轉成 Celery 看得懂的物件**一律由外部驗證與同步層負責，model 完全不解析。

---

## 設計原則

1. **單一排程欄位**：不再有 `schedule_type` / `crontab_display` / `interval_every` / `interval_period`，
   全部收斂成一個 `execution_cycle` 字串欄位。**必填**，不可為空（不加 `null` / `blank`）。

   > 過去多欄位的問題：`schedule_type` 決定要看哪個欄位，邏輯分散；
   > 改成單一字串後，model 只負責存，格式由 serializer 和 utils 處理，各層不重複工作。

2. **model 不解析格式**：model 只負責「存」（資料儲存）。合法性與轉換由外部驗證與同步層負責。

   > 如果 model 也解析格式，等於把 serializer 和 sync 的工作重複做一遍，
   > 未來格式規則改了就要改兩個地方。

3. **只管排程**：建立者、網域、通知等通通不在這層。

---

## 欄位清單

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `title` | `CharField(max_length=70, unique=True)` | ✓ | 排程名稱，全域唯一 |
| `description` | `TextField(blank=True, default="")` | | 排程描述 |
| `status` | `CharField(choices=STATUS, default="active")` | ✓ | `active` / `disabled` |
| `execution_cycle` | `CharField(max_length=128)` | ✓ **必填** | **排程的單一代表欄位**，存原始字串。不可為空（不加 `null` / `blank`），沒排程就不該有這筆排程 |
| `task` | `OneToOneField(PeriodicTask, on_delete=CASCADE, null=True, blank=True)` | | 同步產生的 PeriodicTask（套件自動維護，非使用者填） |
| `created_at` | `DateTimeField(auto_now_add=True)` | 自動 | 建立時間 |
| `updated_at` | `DateTimeField(auto_now=True)` | 自動 | 更新時間 |

> **`task` 欄位為什麼是 `OneToOneField`**：每一個排程定義對應到恰好一個 `PeriodicTask`，
> 不會有一個排程對應多個 `PeriodicTask` 的情況，OneToOne 比 FK 更精確表達這個關係，
> 也方便雙向查詢（`periodic_task.alertruletask` 可直接反查回業務 model）。
>
> **`null=True, blank=True`**：第一次 `save()` 時 `PeriodicTask` 還沒建立，
> signal 跑完後才會填入，所以允許暫時為空。

### class 屬性（非 DB 欄位）

| 屬性 | 說明 |
|------|------|
| `task_name: str` | 必須對應 `@recorded_task(name=...)`；子類覆寫 |

> `task_name` 不存進資料庫，它是 Python class-level 的常數。
> 套件的 sync service 在建立 `PeriodicTask` 時讀這個值，寫進 `PeriodicTask.task` 欄位。
> Beat dispatch 任務時靠這個字串在 Celery registry 裡找到對應的函式。
> 兩端（model 和 `@recorded_task`）字串必須完全一致，否則 Worker 會找不到函式。

---

## Choices 常數

```python
STATUS = [("active", _("active")), ("disabled", _("disabled"))]
```

> `status` 直接對應到 `PeriodicTask.enabled`：
> `active` → `enabled=True`（Beat 會 dispatch），`disabled` → `enabled=False`（Beat 跳過）。
> 使用者只需改 model 的 `status`，套件 signal 自動同步到 `PeriodicTask`。

（不再需要 `SCHEDULE_TYPE_CHOICES` / `INTERVAL_PERIOD_CHOICES`，型別由 `execution_cycle` 字串推斷。）

---

## 必要行為

### 1. `get_task_args() -> list`（抽象方法）

子類**必須**實作，回傳推進 queue 的參數。基礎類別預設 `raise NotImplementedError`。
典型實作只丟主鍵：

```python
def get_task_args(self) -> list:
    return [self.id]
```

> **為什麼只傳 id 不傳整個 instance**：Celery 把 args 序列化成 JSON 丟進 queue，
> Django model instance 無法 JSON 序列化。傳 id（整數）後，task 函式用 id 去 DB 查，
> 還能確保 task 執行時拿到的是當下最新的資料，而不是排程建立時的快照。

### 2. `__str__` 回傳 `self.title`

影響 Django Admin 列表顯示、debug log 印出的名稱、FK 下拉選單的文字。

### 3. `Meta`

```python
class Meta:
    abstract = True
```

> `abstract = True` 讓 Django 不替 `BaseSchedulerTask` 本身建表。
> 只有子類（例如 `AlertRuleTask`）繼承後，Django 才會建立對應的表，
> 並且包含所有繼承來的欄位加上子類自己的業務欄位。
> 多個服務各自繼承時，每個服務的 DB 都有自己獨立的表，資料完全隔離。

> 注意：model 不做 `clean()` 排程格式驗證。`execution_cycle` 的合法性與轉換由外部驗證與同步層負責。

---

## 明確排除（不進這個 model）

| 排除項 | 原因 |
|--------|------|
| `schedule_type` / `crontab_display` / `interval_every` / `interval_period` | 收斂成單一 `execution_cycle` 欄位，避免多欄位邏輯分散 |
| `created_by` / `domain` 等業務欄位 | 不屬於排程基礎建設，各服務自行帶入；套件不假設業務結構 |
| `EmailNotification`（`task_email_*`） | 通知是業務邏輯，不屬於排程 |
| 格式驗證 / 轉換邏輯 | model 不解析，由外部驗證與同步層處理，避免重複工作 |
| broker URL / queue name 設定 | 走 `CELERY_SCHEDULER` 與 Celery 原生設定，不硬寫在 model |

---

## 最小骨架

```python
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_celery_beat.models import PeriodicTask

STATUS = [("active", _("active")), ("disabled", _("disabled"))]


class BaseSchedulerTask(models.Model):
    task_name = "base_task"  # 子類覆寫，須對應 @recorded_task(name=...)

    title = models.CharField(max_length=70, unique=True, help_text=_("排程名稱"))
    description = models.TextField(blank=True, default="", help_text=_("排程描述"))
    status = models.CharField(
        max_length=8, choices=STATUS, default="active", help_text=_("排程狀態")
    )
    execution_cycle = models.CharField(
        max_length=128,
        help_text=_("排程字串，例如 `*/5 * * * *` 或 `@every 30s`"),
    )
    task = models.OneToOneField(
        PeriodicTask, on_delete=models.CASCADE, null=True, blank=True,
        related_name="%(class)s",
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text=_("建立時間"))
    updated_at = models.DateTimeField(auto_now=True, help_text=_("更新時間"))

    class Meta:
        abstract = True

    def get_task_args(self) -> list:
        raise NotImplementedError("Subclasses must implement get_task_args() method")

    def __str__(self):
        return self.title
```
