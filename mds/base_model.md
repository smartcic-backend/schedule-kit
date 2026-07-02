# BaseSchedulerTask

> 套件的抽象基礎 model，各服務繼承它來定義自己的排程業務 model。
> 位置：`src/schedule_kit/models/base.py`

---

## 欄位

| 欄位 | 型別 | 說明 |
|------|------|------|
| `id` | `UUIDField(primary_key=True, default=uuid4)` | 主鍵。統一使用 UUID，跨環境匯出入不會發生 ID 衝突 |
| `name` | `CharField(max_length=70, unique=True)` | 排程名稱，全域唯一 |
| `description` | `TextField(blank=True, default="")` | 排程描述 |
| `enable` | `BooleanField(default=True)` | 是否啟用排程；`True` 啟用、`False` 停用 |
| `execution_cycle` | `CharField(max_length=128)` | 排程字串，必填。接受 5 欄位 crontab（`*/5 * * * *`）或 `@every <duration>`（`@every 30m`） |
| `timezone` | `CharField(max_length=64, default="UTC")` | 排程時區，須為合法的 IANA 時區名稱 |
| `task` | `OneToOneField(PeriodicTask, null=True, blank=True, on_delete=CASCADE, related_name="%(class)s")` | 對應的 django-celery-beat PeriodicTask，由套件 signal 自動維護 |
| `created_by` | `FK(AUTH_USER_MODEL, null=True, on_delete=SET_NULL, db_constraint=False)` | 建立者，刪除使用者時設為 null；`db_constraint=False` 允許跨 DB 或軟刪除情境 |
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

## enable 與 PeriodicTask 的關係

```
model.enable = True   →  PeriodicTask.enabled = True   → Beat 正常 dispatch
model.enable = False  →  PeriodicTask.enabled = False  → Beat 跳過
```

同步由套件 signal 自動處理，服務層只需改 `enable` 欄位。

---

## EmailNotification mixin

`EmailNotification` 是一個獨立的 abstract mixin，與 `BaseSchedulerTask` 組合使用，為子類加上 email 通知欄位。

```python
from schedule_kit.models import EmailNotification

class AlertRuleTask(BaseSchedulerTask, EmailNotification):
    ...
```

### 欄位

| 欄位 | 型別 | 說明 |
|------|------|------|
| `task_email_enabled` | `BooleanField(default=False)` | 是否啟用 email 通知 |
| `task_email_to` | `JSONField(default=list, blank=True)` | 收件人清單；使用 JSONField 而非 postgres ArrayField，保持資料庫無關性 |
| `task_success_send_email` | `BooleanField(default=False)` | 成功時是否也寄信（預設只在失敗時寄） |

> `EmailNotification` 本身不含任何業務邏輯，寄信動作由 task 函式或 signal 負責。

---

## 相關程式位置

| 職責 | 位置 |
|------|------|
| `BaseSchedulerTask` 定義 | `src/schedule_kit/models/base.py` |
| `EmailNotification` 定義 | `src/schedule_kit/models/base.py` |
| 公開匯出（`__all__`） | `src/schedule_kit/models/__init__.py` |
| signal → PeriodicTask 同步 | `src/schedule_kit/services/sync.py` |
| `execution_cycle` 格式驗證 | `src/schedule_kit/utils/cron.py` |
| 繼承範例 | `example/models.py` |
