> 本文件對應開發中的 0.3.0；tag 尚未發佈時請以 `pip install -e .` 驗證。

# 接入指引

> 從零開始把 schedule-kit 整合進新 Django 服務的逐步說明。
> 完整可運行的程式碼見 [`example/`](../example/) 目錄。

---

## 步驟一：安裝

```bash
pip install "schedule-kit @ git+https://github.com/smartcic-backend/schedule-kit.git@v0.3.1"
```

或在 `pyproject.toml` 裡加入：

```toml
[tool.poetry.dependencies]
schedule-kit = {git = "https://github.com/smartcic-backend/schedule-kit.git", tag = "v0.3.1"}
```

> 建議釘定版本（`tag = "v0.3.1"`），避免每次建置抓到不同 commit 造成不可重現建置。升版時改為對應的新 tag。

---

## 步驟二：Django 設定

### INSTALLED_APPS

```python
INSTALLED_APPS = [
    ...
    "django_celery_beat",  # PeriodicTask model 的來源
    "schedule_kit",        # AppConfig.ready() 掛載 signal，讀取 CELERY_SCHEDULER
    ...
]
```

> 順序無強制要求，但 `django_celery_beat` 必須在 `schedule_kit` 之前，或至少同時存在。

### CELERY_BEAT_SCHEDULER（必填）

Beat 必須使用資料庫排程器，套件寫入 `PeriodicTask` 後才能即時生效：

```python
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
```

> 若沒設這行，Beat 從靜態 `beat_schedule` 讀排程，`sync_to_periodic_task` 建立的任務完全不會被執行。

### CELERY_SCHEDULER（建議設定）

```python
CELERY_SCHEDULER = {
    # Worker 監聽的 queue 名稱，必須與啟動 worker 時的 -Q 參數一致
    # 預設 "celery"，不設定則任何 worker 都可能消費此服務的任務
    "QUEUE_NAME": "myservice",
}
```

其他選填參數見 [`settings.md`](./settings.md)。

---

## 步驟三：執行 Migration

套件本身帶有一張 `ExecutionRecord` 表，初次接入需建立：

```bash
python manage.py migrate
```

---

## 步驟四：定義 Model

繼承 `BaseSchedulerTask`，加上業務欄位，並實作兩個必要項目：

```python
from schedule_kit.models import BaseSchedulerTask

class ReportTask(BaseSchedulerTask):
    # 1. task_name 必須與 @recorded_task(name=...) 完全一致
    task_name = "report_task"

    # 業務欄位（自由定義）
    target_email = models.EmailField()
    report_type  = models.CharField(max_length=50)

    # 2. 回傳 Celery args，task 函式會收到這些值
    def get_task_args(self) -> list:
        return [self.id]   # 整數排程 ID
```

`BaseSchedulerTask` 已提供的欄位：`id`（自動遞增整數 PK）、`title`（唯一名稱）、`status`（`active`/`disabled`）、`execution_cycle`、`timezone`、`task`（FK → PeriodicTask）、`created_by`、`created_at`、`updated_at`。詳見 [`base_model.md`](./base_model.md)。

接著建立 migration：

```bash
python manage.py makemigrations
python manage.py migrate
```

---

## 步驟五：定義 Serializer

繼承 `BaseSchedulerSerializer`，它負責驗證 `execution_cycle`、`timezone`，並提供 `next_run_time`、`last_run_at`、`total_run_count` 唯讀欄位：

```python
from schedule_kit.serializers import BaseSchedulerSerializer
from .models import ReportTask

class ReportTaskSerializer(BaseSchedulerSerializer):
    class Meta:
        model  = ReportTask
        fields = "__all__"
```

若需要 Email 通知欄位驗證，組合 `EmailNotificationSerializer`：

```python
from schedule_kit.serializers import BaseSchedulerSerializer, EmailNotificationSerializer

class ReportTaskSerializer(BaseSchedulerSerializer, EmailNotificationSerializer):
    class Meta:
        model  = ReportTask
        fields = "__all__"
```

`timezone` 欄位未傳入時，預設帶入 `request.user.timezone`（User model 須有此屬性），再 fallback 到 `"UTC"`。

---

## 步驟六：定義 Task 函式

用 `@recorded_task` 裝飾，套件自動建立 `ExecutionRecord` 並追蹤執行結果：

```python
from schedule_kit.decorators import recorded_task
from .models import ReportTask

@recorded_task(name="report_task", queue="myservice")
def report_task(task_id: str, record_id: int = 0):
    task = ReportTask.objects.get(id=task_id)
    success, message = run_report(task)
    return task, success, message   # 固定回傳 (instance, success, message)
```

| 回傳值 | 說明 |
|--------|------|
| `instance` | 排程 model 實例（用來填 ExecutionRecord 的 task_title 等） |
| `success` | `True` → success，`False` → fail，`None` → pending（非同步用） |
| `message` | 結果或錯誤訊息 |

> `name` 必須與 model 的 `task_name` 完全一致，否則 Beat dispatch 時找不到函式。
> `queue` 必須與 `CELERY_SCHEDULER["QUEUE_NAME"]` 一致，否則其他服務的 worker 可能消費到這個任務。

非同步任務的完整流程見 [`task_flow.md`](./task_flow.md)。

---

## 步驟七：整合 View / API

### 方式 A：使用 ModelViewSet（signal 自動同步）

Model 的 `post_save` / `post_delete` signal 已由套件掛載，`save()` 與 `delete()` 時自動同步 PeriodicTask，View 層不需額外呼叫：

```python
from rest_framework import viewsets
from .models import ReportTask
from .serializers import ReportTaskSerializer

class ReportTaskViewSet(viewsets.ModelViewSet):
    queryset = ReportTask.objects.all()
    serializer_class = ReportTaskSerializer

    def perform_create(self, serializer):
        # created_by 由 View 注入，client 無法偽造
        serializer.save(created_by=self.request.user)
    # update / destroy 不需要額外處理，signal 自動同步
```

### 方式 B：使用自訂 View（手動同步）

若不使用 ModelViewSet 或需要在特定時機控制同步，手動呼叫 sync 函式：

```python
from schedule_kit.services.sync import sync_to_periodic_task, delete_periodic_task
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from .models import ReportTask
from .serializers import ReportTaskSerializer

class ReportTaskListView(ListCreateAPIView):
    queryset = ReportTask.objects.all()
    serializer_class = ReportTaskSerializer

    def perform_create(self, serializer):
        rule = serializer.save(created_by=self.request.user)
        sync_to_periodic_task(rule, created=True)

class ReportTaskDetailView(RetrieveUpdateDestroyAPIView):
    queryset = ReportTask.objects.all()
    serializer_class = ReportTaskSerializer

    def perform_update(self, serializer):
        rule = serializer.save()
        sync_to_periodic_task(rule, created=False)

    def perform_destroy(self, instance):
        delete_periodic_task(instance)
        instance.delete()
```

> 方式 A（signal）和方式 B（手動）不會衝突，但手動呼叫時 signal 也會觸發，等於執行兩次同步——無副作用，只是多一次 DB write。若想避免，可在 signal 中判斷是否已同步，或統一只用一種方式。

---

## 步驟八：全量重新同步

批次匯入資料或系統狀態不一致時，用 `resync_all` 一次對齊：

```python
from schedule_kit.services.sync import resync_all
from .models import ReportTask

result = resync_all(ReportTask)
# {"synced": 12, "removed": 1}
```

典型使用場景：
- `POST /import/` 批次寫入後
- 主系統呼叫 datasource 異動後（如 alertv2 的 `worker/reload/` endpoint）
- 系統異常或 DB 還原後恢復一致性

---

## 常見錯誤

### task_name 與 @recorded_task(name=...) 不一致

```python
# ❌ 錯誤：名稱不同，Beat dispatch 時找不到函式
class ReportTask(BaseSchedulerTask):
    task_name = "report_task"

@recorded_task(name="my_report_task")   # 不同！
def report_task(...):
    ...

# ✅ 正確：兩者完全一致
class ReportTask(BaseSchedulerTask):
    task_name = "report_task"

@recorded_task(name="report_task")
def report_task(...):
    ...
```

### CELERY_BEAT_SCHEDULER 未設定為 DatabaseScheduler

```python
# ❌ 未設定：Beat 用靜態設定，動態 PeriodicTask 不會被執行
# settings.py 裡沒有 CELERY_BEAT_SCHEDULER

# ✅ 正確
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
```

### QUEUE_NAME 與 worker 啟動的 queue 不符

```bash
# ❌ worker 只監聽 celery queue，但 QUEUE_NAME 設 "myservice"
celery -A config worker -Q celery

# ✅ 一致
# settings.py
CELERY_SCHEDULER = {"QUEUE_NAME": "myservice"}

# worker 啟動
celery -A config worker -Q myservice
```

若不設定 `QUEUE_NAME`（預設 `"celery"`），此服務的任務會進預設 queue，其他服務的 worker 也可能消費到，造成跨服務干擾。

### 排程 ID 型別

0.2.0 起排程 ID 為自動遞增整數，`get_task_args()` 回傳 `[self.id]`。
Celery 的 `self.request.id` 仍是 UUID，兩者不可混用。

### schedule_kit 未在 INSTALLED_APPS

```python
# ❌ AppConfig.ready() 不會執行，signal 不掛載，管理指令無法使用
INSTALLED_APPS = ["django_celery_beat", ...]

# ✅ 加入 schedule_kit
INSTALLED_APPS = ["django_celery_beat", "schedule_kit", ...]
```


## 寫入主專案執行紀錄（0.2.0）

新子專案需與主專案使用同一個資料庫及同一組 `django_celery_beat` 資料表，
由主專案先完成 `celery_skdl_executionrecord` 的 migration。套件只寫入與刪除關聯紀錄，
不建立、不修改主專案 schema。子專案設定：

```python
CELERY_SCHEDULER = {
    "QUEUE_NAME": "myservice",
    "WRITE_MAIN_EXECUTION_RECORDS": True,
    "EXECUTION_SOURCE": "myservice",  # 跨子專案唯一且固定的識別名稱
}
```

使用 `@recorded_task(name="report_task", scheduler_model=ReportTask)`。
`BaseSchedulerTask` 子類可依唯一 `task_name` 自動推導；多模型共用 task 名稱時須顯式指定。
排程建立時必須填入主專案同一使用者表的 `created_by`，否則無法建立主專案的擁有者紀錄。
同步成功／失敗、未捕捉例外、非同步回呼及逾時結果會寫入主專案，
其 `result/start_time` 對應套件 `status/occurred_at`，且直接使用排程的 `task_id` 關聯 PeriodicTask。
主專案可以沿用現有 API 查詢；本機紀錄仍供 callback 使用。

同步任務的紀錄寫入異常不改變業務結果；Celery 紀錄會將業務 False 視為 FAILURE。
回傳格式錯誤也會拋出例外，成功則維持回傳本機紀錄 ID。
若本機建檔失敗，同步函式收到 `record_id=None` 且仍會執行，但不直接共寫，避免在沒有持久化識別時產生無法去重的紀錄；此情況須依錯誤 log 處理。非同步 dispatcher **必須**設定
`@recorded_task(..., require_record=True)`，無法建立可回呼紀錄時不派送工作。
callback 應呼叫 `update_record()`；重複回呼只處理第一次終態，快速回呼不會被 pending 覆寫。

主專案寫入失敗時，本機終態會保留，main_synced_at 留空。重複 callback 或 maintenance 會重試；共用表 INSERT 與本機同步標記在同一交易，避免重複寫入。未同步終態不會被本機保留政策刪除。
刪除 PeriodicTask 時主專案關聯紀錄一起刪除，本機歷史紀錄則保留並設為 SET_NULL。
共用表每次寫入後依主專案同名 Django 設定 TASK_RECORD_KEEP_MAX_COUNT／TASK_RECORD_KEEP_MAX_DAYS 清理，預設 1000 筆／60 天；兩專案設定須一致。兩種紀錄均按模型名稱加 ID 分組。
提供的業務 message 須由呼叫端去除敏感資訊，套件截斷至 4000 字元；
未捕捉例外的紀錄只寫例外類別，不儲存原始錯誤內容。

### 多語系訊息與主專案 `0042`（0.3.0）

任務以 `ExecutionMessage` 回傳訊息時（見 [record_flow.md](record_flow.md#執行訊息代碼與多語系030)），
寫入主表時會一併寫入 `message_code`、`message_params`、`message_i18n`，主專案依查看者語系從 `message_i18n` 挑選顯示，
不需要收錄子專案的翻譯檔。`message` 一律為英文版本。

- 相依：主專案 oivsion360 須套用 `celery_skdl.0042`（新增上述三個可為 NULL 的欄位），才會顯示多語系。
- 降級：主表還沒有這些欄位時，套件自動只寫 0.2.0 的欄位，投影仍成功並標記已同步，worker 行程記錄一次 warning；
  因此套件與主專案的部署順序不受限制。欄位偵測結果快取 300 秒，細節見 [settings.md](settings.md#主表多語系欄位偵測030)。
- 寫入方式由 `EXECUTION_TRANSPORT` 決定，目前只支援 `db`。
- `message_params` 會寫入主表，只能放可公開的值。

## 從 UUID 版本升級

此版本為不相容更新，適用新子專案。既有 UUID 排程不能直接改型別。
套件新增 migration 會在有既有執行紀錄時中止，不會刪除或猜測 UUID 對應。
舊專案須先備份與匯出，建立 UUID→整數對照，再遷移排程、相關外鍵、
PeriodicTask args 與歷史紀錄；請依各專案 schema 撰寫並驗證資料 migration。
套件的 abstract model 不會自動修改既有子專案資料表。example 的升級同樣僅允許空排程表。
不要直接重置正式資料庫或改寫已套用的 migration。

遇到升級／回滾中止訊息，請依 [整數 ID 升級指引](upgrade_integer_ids.md) 處理；包含檢查、備份、封存匯回與驗收順序。


### 來源隔離與補送

`EXECUTION_SOURCE` 必須是部署間固定、跨子專案唯一的名稱（1–80 個英數字、點、底線或連字號）。
啟用共寫卻未提供有效來源時，任務會在執行業務前明確報錯。
本機及主專案的 `task_model` 保存 `來源:app_label.ModelName`，
例如 `billing:reports.ReportTask`，避免不同專案或不同 app 的同名模型、相同整數 ID 互相清理。
不可為同一專案任意更換來源名稱；舊版只有類別名稱的紀錄須由擁有者確認來源及模型後遷移。

請將 maintenance 加入專案既有 Beat schedule（queue 須與 worker 監聽一致），例如：

```python
CELERY_BEAT_SCHEDULE = {
    "schedule-kit-maintenance": {
        "task": "schedule_kit.cleanup_execution_records",
        "schedule": 300.0,
        "options": {"queue": "myservice"},
    },
}
```

此工作先處理逾時與待同步終態，再清理已完成同步的本機紀錄。
未完成本機終態更新時不會寫入主專案；業務結果／原始例外仍保留，回呼重試可再次完成更新。
主專案與本機同步標記須位於同一資料庫；不要以 DB router 把兩者分開。
若使用尚未發布的早期 0.2.0 測試版本，升級前須核對已共寫的紀錄再補同步標記，
不能將所有舊資料直接視為未送達，否則可能重送。正式切換前請核對來源映射與同步狀態。

## 多專案共用資料庫（0.3.0）

主專案與多個子專案（例如 alertv2、MessageCenter）使用同一個 DB 時，也會共用套件的本地表
`schedule_kit_executionrecord`。須遵守：

- **同一版 migration**：同一個 DB 中所有安裝 schedule-kit 的專案必須升級到同一版套件，並執行 `migrate schedule_kit`。
  `0005` 只新增可為 NULL 的欄位與 `task_model` 索引，舊版程式仍可寫入，但不要讓各專案長期停在不同版本。
- **`EXECUTION_SOURCE` 不可重複**：每個專案使用固定且唯一的來源名稱；本地紀錄的 `task_model` 為 `來源:app_label.Model`，
  是判斷紀錄歸屬的唯一依據。
- **maintenance 只處理自己的紀錄**（**BREAKING**，行為修正）：
  - 啟用共寫時，逾時標記、補送主表與天數／筆數清理，只處理 `task_model` 以 `<EXECUTION_SOURCE>:` 開頭的紀錄。
  - 未啟用共寫時，只處理沒有來源前綴的紀錄，以及（有設定 `EXECUTION_SOURCE` 時）本專案前綴的紀錄。
  - 0.2.0 會處理整張表，可能把其他專案的 pending 紀錄標為逾時、刪除其他專案未同步的紀錄，或對其他來源的紀錄記錄「來源不符」錯誤。
    若有專案依賴「清理全部紀錄」，升級後須由各專案自己的 maintenance 處理。
  - 啟用共寫時，沒有來源前綴的紀錄（例如找不到排程、`task_model` 為空的紀錄）不屬於任何專案的 maintenance 範圍。
- **回呼不跨來源**：`update_record()` 收到其他來源的紀錄 ID 時不更新紀錄，只記錄 warning，回呼流程不會中斷。
