> 本文件對應開發中的 0.2.0；tag 尚未發佈時請以 `pip install -e .` 驗證。

# schedule-kit

Django Celery 排程管理套件，標準化各微服務的排程建立、同步與執行觀測。

## 安裝

**從 GitHub 安裝（釘定版本）：**

```bash
pip install "schedule-kit @ git+https://github.com/smartcic-backend/schedule-kit.git@v0.2.0"
```

或在 `pyproject.toml` 裡加入：

```toml
[tool.poetry.dependencies]
schedule-kit = {git = "https://github.com/smartcic-backend/schedule-kit.git", tag = "v0.2.0"}
```

## 依賴

- Python >= 3.10
- Django >= 4.2
- djangorestframework >= 3.14
- celery >= 5.3
- django-celery-beat >= 2.5
- django-filter >= 23.0

---

## 功能說明

### BaseSchedulerTask

排程 model 的抽象基底類別，繼承後加入業務欄位即可使用。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `id` | `AutoField` | 自動遞增整數主鍵；以模型名稱加 ID 識別排程，匯出入需處理 ID 對照 |
| `title` | `CharField(70)` | 排程名稱，全域唯一 |
| `description` | `TextField` | 排程描述 |
| `status` | `CharField` | `active` / `disabled` |
| `execution_cycle` | `CharField(128)` | 排程字串（見下方格式說明） |
| `timezone` | `CharField(64)` | 排程時區，預設 `UTC` |
| `task` | `OneToOneField` | 關聯的 `PeriodicTask`（套件自動維護） |
| `created_by` | `FK(AUTH_USER_MODEL)` | 建立者（可為空，刪除使用者時設為 null） |
| `created_at` | `DateTimeField` | 建立時間 |
| `updated_at` | `DateTimeField` | 更新時間 |

子類必須實作 `get_task_args() -> list`，回傳 Beat dispatch 時帶入的參數。
子類必須定義 `task_name: str`，與 `@recorded_task(name=...)` 的值一致。

#### execution_cycle 格式

支援 **crontab**（`*/5 * * * *`）和 **@every**（`@every 30s`）兩種格式。詳見 [`mds/execution_cycle.md`](./mds/execution_cycle.md)。

---

### EmailNotification（選用 mixin）

需要「任務執行後寄送 Email 通知」欄位時，與 `BaseSchedulerTask` 組合使用：

```python
class MyTask(BaseSchedulerTask, EmailNotification):
    ...
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| `task_email_enabled` | `BooleanField` | 是否啟用 Email 通知，預設 `False` |
| `task_email_to` | `JSONField` | 收件者 Email 清單 |
| `task_success_send_email` | `BooleanField` | 成功時是否也寄送（預設僅失敗時寄送） |

serializer 端搭配 `EmailNotificationSerializer`（驗證啟用通知時必須提供收件者、Email 格式）：

```python
class MyTaskSerializer(BaseSchedulerSerializer, EmailNotificationSerializer):
    ...
```

> 注意：套件只提供欄位與驗證，實際寄信邏輯由任務自行實作。

---

### BaseSchedulerSerializer 輸出欄位

除了 model 欄位外，serializer 額外提供：

| 欄位 | 說明 |
|------|------|
| `next_run_time` | 下次執行時間（停用或無排程時為 null） |
| `last_run_at` | 上次執行時間（唯讀，來自 `PeriodicTask`） |
| `total_run_count` | 總執行次數（唯讀，來自 `PeriodicTask`） |
| `created_by` | 唯讀，由 view 的 `perform_create` 透過 `serializer.save(created_by=request.user)` 注入；client 無法直接設定或修改 |
| `timezone` | 未指定時預設帶入請求使用者的時區設定（`user.timezone`）；使用者未設定或無 request context 時為 `UTC`。值須為合法的 IANA 時區名稱 |

---

### ExecutionRecord

每次排程執行後自動寫入的紀錄，用來觀測背景任務有沒有跑、結果如何。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `task_title` | `CharField` | 排程名稱 |
| `task_function` | `CharField` | Celery task name |
| `task_model` | `CharField` | 來源專案加模型完整名稱，例如 myservice:reports.ReportTask |
| `task_id` | `IntegerField` | 排程 model 的 PK（取不到時為空） |
| `task_created_by_id` | `IntegerField` | 建立者 ID（取不到時為空） |
| `celery_task_id` | `CharField` | Celery 非同步任務 ID（`AsyncResult` 用，有 index） |
| `status` | `CharField` | `running` / `pending` / `success` / `fail` |
| `occurred_at` | `DateTimeField` | 開始時間 |
| `end_time` | `DateTimeField` | 結束時間（pending 時為空） |
| `message` | `TextField` | 結果訊息或錯誤訊息 |
| `periodic_task` | `FK(PeriodicTask)` | 關聯排程（排程刪除後保留歷史，FK 變 null） |

#### status 流轉

- **同步任務**：`running` → `success` / `fail`
- **非同步任務**：`pending` → `success` / `fail`（由 `update_record()` 更新）
- 超過 `PENDING_TIMEOUT_HOURS` 仍為 `pending` 的紀錄，由 maintenance task 自動標為 `fail`

---

### @recorded_task — 接入執行紀錄的 decorator

任務函式必須用 `@recorded_task` 裝飾，套件才能自動建立 `ExecutionRecord` 並追蹤執行結果：

```python
from schedule_kit.decorators import recorded_task

@recorded_task(name="alert_rule_task", queue="myservice")
def alert_rule_task(task_id: str, record_id: int = 0):
    task = AlertRuleTask.objects.get(id=task_id)
    success, message = AlertRuleService.run(task)
    return task, success, message
```

#### 參數

| 參數 | 說明 |
|------|------|
| `name` | Celery task name，必須與 `task_name` 完全一致 |
| `queue` | 指定 queue（可選，不填則由 worker 預設 queue 處理） |

#### 回傳契約

任務函式必須回傳 `(instance, success, message)` tuple：

| 值 | 說明 |
|----|------|
| `instance` | 排程 model 實例（用來填 `task_title`、`task_model`、`task_created_by_id`） |
| `success` | `True` → `success`、`False` → `fail`、`None` → `pending`（非同步等回調用） |
| `message` | 結果或錯誤訊息字串 |

> 套件會自動注入 `record_id: int` 參數，非同步任務可用它在回調時更新紀錄狀態。
> 若函式拋出例外或回傳格式不符，紀錄自動標為 `fail`。

---

### resync_all — 全量重新同步

排程 model 與 `PeriodicTask` 的同步平時由 signals 自動處理（單筆 save / delete）。
當兩者可能已不一致時，使用 `resync_all` 一次全量對齊：

```python
from schedule_kit.services import resync_all

result = resync_all(MyTask)
# {"synced": 12, "removed": 1}
```

執行內容（依序）：

1. **移除孤兒 PeriodicTask**：`task` 名稱屬於此 model、但已無任何 instance 關聯的殘留排程
2. **補正所有 instance**：重建缺失的 PeriodicTask、修正被外部停用或設定漂移的排程

適用情境：

- 批次匯入資料後，確保所有排程正確建立
- 透過 API 或手動直接修改過 `PeriodicTask`（例如暫停功能）後恢復一致性
- 系統異常或資料庫還原後的狀態恢復

---

### 設定參數（CELERY_SCHEDULER）

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `QUEUE_NAME` | `"celery"` | Worker 監聽的 queue 名稱 |
| `SAFETY_MARGIN_SECONDS` | `30` | expire 計算的安全邊際（秒） |
| `MIN_EXPIRE_SECONDS` | `60` | expire 下限（秒） |
| `MAX_EXPIRE_SECONDS` | `86400` | expire 上限（秒） |
| `TASK_RECORD_KEEP_MAX_COUNT` | `1000` | 同一排程最多保留幾筆執行紀錄 |
| `TASK_RECORD_KEEP_MAX_DAYS` | `30` | 執行紀錄保留天數上限 |
| `PENDING_TIMEOUT_HOURS` | `24` | pending 超過幾小時自動標為 fail |

---

### Management Commands

裝好套件（`INSTALLED_APPS` 加入 `schedule_kit`）後，以下指令直接可用，不需在專案端另建 command：

#### trigger_task — 手動觸發排程任務

```bash
# 列出 beat_schedule / Beat 資料庫中的所有排程
python manage.py trigger_task --list
python manage.py trigger_task --list-all

# 用任務名稱觸發（--args 為 JSON 陣列，排程 model PK 為整數）
python manage.py trigger_task --args '["a1b2c3d4-0000-0000-0000-000000000001"]' alert_rule_task

# 用排程名稱觸發（自動帶入該排程的參數與 queue）
python manage.py trigger_task --schedule-name '每日報表'

# 覆蓋參數或 queue
python manage.py trigger_task --schedule-name '每日報表' --args '["a1b2c3d4-0000-0000-0000-000000000005"]'
python manage.py trigger_task --args '["a1b2c3d4-0000-0000-0000-000000000001"]' --queue other_queue alert_rule_task
```

`--list-all` 的「參數詳情」會把 args 第一個值當作排程 model 的 PK，自動從
`BaseSchedulerTask` 子類（依 `task_name` 對應）查出該筆排程的標題與狀態。

#### check_celery_status — 檢查 Worker / Beat 健康狀態

```bash
python manage.py check_celery_status                  # 全部檢查
python manage.py check_celery_status --check worker   # 只檢查 Worker（需 broker 連線）
python manage.py check_celery_status --check beat     # 只檢查 Beat 資料庫
python manage.py check_celery_status --format simple  # 精簡輸出
```

Worker 檢查涵蓋連線、統計、活躍/已排程/已註冊任務；Beat 檢查列出所有
`PeriodicTask` 與下次執行時間（時區換算與套件 API 的 `next_run_time` 一致）。

---

## 接入新專案

逐步整合指引（INSTALLED_APPS、必填設定、model / serializer / task / view 各層接入方式、常見錯誤）見 [`mds/integration.md`](./mds/integration.md)。

## 範例

完整可運行的接入範例見 [`example/`](./example/) 目錄。

---

## 測試

單元測試、整合測試與端對端測試的執行方式見 [`tests/`](./tests/) 目錄。


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

## 從 UUID 版本升級

此版本為不相容更新，適用新子專案。既有 UUID 排程不能直接改型別。
套件新增 migration 會在有既有執行紀錄時中止，不會刪除或猜測 UUID 對應。
舊專案須先備份與匯出，建立 UUID→整數對照，再遷移排程、相關外鍵、
PeriodicTask args 與歷史紀錄；請依各專案 schema 撰寫並驗證資料 migration。
套件的 abstract model 不會自動修改既有子專案資料表。example 的升級同樣僅允許空排程表。
不要直接重置正式資料庫或改寫已套用的 migration。

遇到升級／回滾中止訊息，請依 [整數 ID 升級指引](mds/upgrade_integer_ids.md) 處理；包含檢查、備份、封存匯回與驗收順序。


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
