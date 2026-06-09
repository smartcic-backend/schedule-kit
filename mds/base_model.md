# BaseSchedulerTask

> 套件的抽象基礎 model，各服務繼承它來定義自己的排程業務 model。
> 位置：`src/schedule_kit/models/base.py`

---

## 欄位

| 欄位 | 型別 | 說明 |
|------|------|------|
| `title` | `CharField(max_length=70, unique=True)` | 排程名稱，全域唯一 |
| `description` | `TextField(blank=True, default="")` | 排程描述 |
| `status` | `CharField(choices=STATUS, default="active")` | `active` / `disabled` |
| `execution_cycle` | `CharField(max_length=128)` | 排程字串，必填。接受 5 欄位 crontab（`*/5 * * * *`）或 `@every <duration>`（`@every 30m`） |
| `task` | `OneToOneField(PeriodicTask, null=True, blank=True)` | 對應的 django-celery-beat PeriodicTask，由套件 signal 自動維護 |
| `created_at` | `DateTimeField(auto_now_add=True)` | 建立時間 |
| `updated_at` | `DateTimeField(auto_now=True)` | 更新時間 |

### class 屬性（非 DB 欄位）

| 屬性 | 說明 |
|------|------|
| `task_name: str` | 預設 `"base_task"`，子類必須覆寫。須與 `@recorded_task(name=...)` 完全一致 |

---

## Meta

```python
class Meta:
    abstract = True
```

Django 不替 `BaseSchedulerTask` 建表，只有子類繼承後才建立各自的表。

---

## 抽象方法

### `get_task_args() -> list`

子類必須實作，回傳 Celery task 的 args。

```python
# 典型實作
def get_task_args(self) -> list:
    return [self.id]
```

> Celery args 序列化為 JSON，只能傳 int/str 等基本型別，不能傳 model instance。
> Task 函式收到 id 後自行查 DB，確保執行時拿到最新資料。

---

## 繼承範例

```python
from schedule_kit.models.base import BaseSchedulerTask

class AlertRuleTask(BaseSchedulerTask):
    task_name = "alert_rule_task"   # 對應 @recorded_task(name="alert_rule_task")

    # 業務欄位（套件不預設）
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    target_url = models.URLField()

    def get_task_args(self) -> list:
        return [self.id]
```

---

## status 與 PeriodicTask 的關係

```
model.status = "active"    →  PeriodicTask.enabled = True   → Beat 正常 dispatch
model.status = "disabled"  →  PeriodicTask.enabled = False  → Beat 跳過
```

同步由套件 signal 自動處理，服務層只需改 `status` 欄位。

---

## 相關程式位置

| 職責 | 位置 |
|------|------|
| `BaseSchedulerTask` 定義 | `src/schedule_kit/models/base.py` |
| signal → PeriodicTask 同步 | `src/schedule_kit/services/sync.py` |
| `execution_cycle` 格式驗證 | `src/schedule_kit/utils/cron.py` |
| 繼承範例 | `example/models.py` |
