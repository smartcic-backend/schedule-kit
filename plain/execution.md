# 執行觀測：執行紀錄

> 套件核心的第二條路（見 [plain.md](./plain.md)）：讓背景排程任務的結果「被看見」。
> 以排程為單位、給人看、可對外查詢的執行歷史。
>
> 排程任務在背景無人看管地跑，沒有執行觀測就只能靠日誌或人工確認，
> 這個機制讓每次執行的結果自動被記錄下來，可以從 API 查詢。

---

## 一、執行紀錄 ExecutionRecord

### 目的

排程任務在背景無人看管地跑，最大風險是**靜默失敗**。ExecutionRecord 回答：

1. 這個排程到底有沒有跑？
2. 跑成功還失敗？為什麼失敗？
3. 上次什麼時候跑的？歷史紀錄？

> 與 Celery 原生 result backend 的差別：Celery 記的是「task UUID」結果，
> 以 task 執行實例為單位，格式是機器用的原始 return value。
> ExecutionRecord 以**排程**為單位、連回 PeriodicTask、帶人看得懂的欄位、可對外查詢。
> 兩者互補，不互相取代。

### 收斂為單一 model

合併現有 `ExecutionRecord` + `CelerySchedulerExecution` 為**一份** `ExecutionRecord`。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `task_title` | `CharField` | 任務名稱（自排程 model 的 `title` 推導） |
| `task_function` | `CharField` | 執行函數名（開發排查用） |
| `task_model` | `CharField` | 具體任務類別名（開發排查用） |
| `task_id` | `IntegerField` | 具體任務 ID |
| `task_created_by_id` | `IntegerField(null=True)` | 建立者 ID，**可選**（取不到留空） |
| `status` | `CharField(choices)` | `running` / `pending` / `success` / `fail` |
| `start_time` | `DateTimeField` | 開始時間 |
| `end_time` | `DateTimeField` | 結束時間 |
| `message` | `TextField` | 備註 / 錯誤訊息 |
| `periodic_task` | `FK(PeriodicTask, null=True)` | 連回排程 |

> **`task_id` 為什麼不用 FK**：`ExecutionRecord` 是套件的表，
> 但 `AlertRuleTask` 是各服務自己的表，套件不能建立跨服務的 FK。
> 用 `IntegerField` 存 id，查詢時由各服務自行 join。
>
> **`periodic_task` 為什麼 `null=True`**：如果排程被刪除，歷史紀錄應該保留，
> 設 `null=True` 讓 FK 變成 nullable，排程刪除後這筆紀錄還在，`periodic_task` 變 null。

```python
EXEC_STATUS = [
    ("running", "running"),   # 同步任務執行中
    ("pending", "pending"),   # async 任務已回傳、等外部 agent 回調
    ("success", "success"),
    ("fail", "fail"),
]
```

> `running` 與 `pending` 都是過渡狀態，最終一定要轉為 `success` 或 `fail`。
> 兩者的 timeout 閾值可分開設定（`running` 通常秒~分鐘；`pending` 可能小時級）。
>
> **狀態流轉**：
> - 同步任務：`running` → `success` 或 `fail`
> - 非同步任務：`pending` → `success` 或 `fail`（由 `update_record` 更新）

### 自動清理（保留上限）

存檔後修剪，避免無限成長：

- 超過 `TASK_RECORD_KEEP_MAX_DAYS` 天的刪除
- 同一 `task_id` 筆數超過 `TASK_RECORD_KEEP_MAX_COUNT` 時，刪最舊的

> 兩個條件獨立運作：天數上限保護磁碟空間，筆數上限保護高頻任務不會佔用過多空間。
> 例如每秒跑一次的任務，若只有天數上限，30 天會累積 260 萬筆。

> 兩個參數移入 `CELERY_SCHEDULER` 設定（見 [setup.md](./setup.md)）。
> 實際清理由套件自帶的 maintenance task 執行（見下方 infra task）。

---

## 二、`@recorded_task` 裝飾器

### 為什麼不用 `@record` + `@shared_task` 分開

```python
# 這樣寫不會有效果：
@record
@shared_task(name="alert_rule_task", queue="...")
def alert_rule_task(task_id):
    ...
```

`@shared_task` 套用時就把函式以 task name 登錄進 Celery registry。
Worker 從 queue 收到任務後查 registry，找到的是沒有 `@record` 的原始函式。
`@record` 只有直接呼叫 `alert_rule_task()` 時才有效，透過 queue dispatch 時完全跳過。

**解法：`@recorded_task` 合體裝飾器**，同時處理 Celery 註冊和執行紀錄：

```python
@recorded_task(name="alert_rule_task", queue="myservice")
def alert_rule_task(task_id):
    task = AlertRuleTask.objects.get(id=task_id)
    ...
    return task, True, "done"
```

### 契約：`(instance, success, message)`

task 函式回傳「**排程 model 實例 + 成敗 + 訊息**」，其餘欄位由裝飾器自動推導：

裝飾器自動處理：

- **`title` / `task_id` / `task_model`**：從 `instance` 推導
- **`created_by`**：以 `getattr(instance, "created_by", None)` 取，**取不到留空**（不強制）
- **`start_time` / `end_time`**：裝飾器自動量
- **`periodic_task`**：以 task name + args 連回 `PeriodicTask`
- **`status`**：task 開始時寫 `running`；依回傳值設 `success` / `fail`

### 非同步任務：pending → 後續更新（走薄 API）

有些 task 只是把工作丟給外部 agent 就 return，真正成敗稍後才回來。處理方式：

- task 回傳 `(instance, None, message)`：`success=None` 代表非同步，`@recorded_task` 寫 `status="pending"`。
- 裝飾器回傳該筆 record 的 id，服務自行保管。
- agent 回來後，服務呼叫套件提供的薄 API：

  ```python
  update_record(record_id, success=True, message="...")   # → status 改 success/fail，同時更新 end_time
  ```

- **套件不碰** UUID 比對 / RabbitMQ 回拋對應——「哪個回拋對應哪筆 record_id」由各服務自理。

> **`pending` 沒有更新怎麼辦**：如果 agent 掛掉或邏輯有 bug，`update_record` 永遠不會被呼叫，
> 這筆紀錄就停在 `pending`。infra maintenance task 應設定 timeout：
> 超過 N 小時仍為 `pending` 的紀錄自動標為 `fail`。

---

## 三、唯讀查詢 API

執行紀錄對外**只讀**（不可從 API 新增/修改），供 UI 列出某排程的執行歷史。

**套件留「安全共用料」，權限與查詢擴充交各服務**：

| 由套件提供 | 由各服務做 |
|------------|-----------|
| 唯讀 serializer（欄位形狀） | 覆寫 `get_queryset` 做權限過濾 |
| `BaseExecutionRecordFilterSet`（見下方） | 繼承並加上業務需要的查詢欄位 |
| 不含權限的 base 唯讀 ViewSet（list-only） | 指定自己的 `filterset_class` |

### Filterset 設計

**套件只提供排程觀測必要的三個 filter**：

```python
# schedule_kit/filters.py（套件內部）
import django_filters
from .models import ExecutionRecord

class BaseExecutionRecordFilterSet(django_filters.FilterSet):
    class Meta:
        model = ExecutionRecord
        fields = {
            "task_id":        ["exact"],   # 查某個排程的所有執行紀錄
            "periodic_task":  ["exact"],   # 透過 PeriodicTask FK 查
            "status":         ["exact"],   # running / pending / success / fail
        }
```

| filter | 用途 | 屬於 |
|--------|------|------|
| `task_id` | 某個排程的所有執行歷史 | 排程觀測核心 |
| `periodic_task` | 透過 PeriodicTask 查 | 排程觀測核心 |
| `status` | 看成功 / 失敗 / 進行中 | 排程觀測核心 |
| `start_time`、`end_time` 範圍 | 時間區間查詢 | UI 需求，各服務自己加 |
| `message` 搜尋 | 錯誤訊息關鍵字 | UI 需求，各服務自己加 |

> `start_time` / `end_time` / `message` 不放進套件：這些是 UI 查詢需求，
> 各服務需要的範圍和查法不同（有的要精確比對、有的要 contains），
> 套件假設太多反而限制彈性。

**各服務繼承後加上自己需要的欄位**：

```python
# 各服務的 filters.py
import django_filters
from schedule_kit.filters import BaseExecutionRecordFilterSet

class AlertRuleExecutionFilterSet(BaseExecutionRecordFilterSet):
    start_time_after  = django_filters.DateTimeFilter(field_name="start_time", lookup_expr="gte")
    start_time_before = django_filters.DateTimeFilter(field_name="start_time", lookup_expr="lte")

    class Meta(BaseExecutionRecordFilterSet.Meta):
        pass
```

**ViewSet 指定 filterset**：

```python
# 各服務的 views.py
class MyExecutionRecordViewSet(BaseExecutionRecordViewSet):
    filterset_class = AlertRuleExecutionFilterSet   # 換成自己的 filterset

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        return qs if u.is_staff else qs.filter(task_created_by_id=u.id)
```

> 不覆寫 `filterset_class` 時，ViewSet 預設使用套件的 `BaseExecutionRecordFilterSet`，
> 只有 `task_id`、`periodic_task`、`status` 三個 filter 可用。

---

## 四、套件自帶 infra task

執行紀錄進套件後，連帶這些 **infra `@shared_task` 由套件提供**（非各服務自定）：

- 執行紀錄清理 task（依 `TASK_RECORD_KEEP_MAX_*` 修剪）

> 原則：**業務 task 各服務自定，infra task 套件提供**。
> 清理任務是套件的內部維護工作，各服務不需要也不應該自己實作。
