# 接入指引

> 從零開始把 schedule-kit 整合進新 Django 服務的逐步說明。
> 完整可運行的程式碼見 [`example/`](../example/) 目錄。

---

## 步驟一：安裝

```bash
pip install "schedule-kit @ git+https://github.com/smartcic-backend/schedule-kit.git@v0.1.1"
```

或在 `pyproject.toml` 裡加入：

```toml
[tool.poetry.dependencies]
schedule-kit = {git = "https://github.com/smartcic-backend/schedule-kit.git", tag = "v0.1.1"}
```

> 建議釘定版本（`tag = "v0.1.1"`），避免每次建置抓到不同 commit 造成不可重現建置。升版時改為對應的新 tag。

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
        return [str(self.id)]   # 必須是 str，不能傳 UUID 物件
```

`BaseSchedulerTask` 已提供的欄位：`id`（UUID PK）、`name`（唯一名稱）、`enable`（`BooleanField`，預設 `True`）、`execution_cycle`、`timezone`、`task`（FK → PeriodicTask）、`created_by`、`created_at`、`updated_at`。詳見 [`base_model.md`](./base_model.md)。

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

### get_task_args() 回傳 UUID 物件

```python
# ❌ UUID 物件無法 JSON 序列化
def get_task_args(self) -> list:
    return [self.id]

# ✅ 轉成 str
def get_task_args(self) -> list:
    return [str(self.id)]
```

### schedule_kit 未在 INSTALLED_APPS

```python
# ❌ AppConfig.ready() 不會執行，signal 不掛載，管理指令無法使用
INSTALLED_APPS = ["django_celery_beat", ...]

# ✅ 加入 schedule_kit
INSTALLED_APPS = ["django_celery_beat", "schedule_kit", ...]
```
