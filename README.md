# schedule-kit

Django Celery 排程管理套件，標準化各微服務的排程建立、同步與執行觀測。

## 安裝

**從 GitHub 安裝：**

```bash
pip install git+https://github.com/smartcic-backend/schedule-kit.git
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
| `id` | `UUIDField` | 主鍵。套件標準：所有排程 model 統一使用 UUID（識別碼不重複使用，跨環境匯出入不會發生 ID 衝突） |
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
| `created_by` | 未指定時預設帶入當前請求的使用者 |
| `timezone` | 未指定時預設帶入請求使用者的時區設定（`user.timezone`）；使用者未設定或無 request context 時為 `UTC`。值須為合法的 IANA 時區名稱 |

---

### ExecutionRecord

每次排程執行後自動寫入的紀錄，用來觀測背景任務有沒有跑、結果如何。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `task_title` | `CharField` | 排程名稱 |
| `task_function` | `CharField` | Celery task name |
| `task_model` | `CharField` | 排程 model 的類別名稱 |
| `task_id` | `UUIDField` | 排程 model 的 PK（取不到時為空） |
| `task_created_by_id` | `IntegerField` | 建立者 ID（取不到時為空） |
| `celery_task_id` | `CharField` | Celery 非同步任務 ID（`AsyncResult` 用，有 index） |
| `status` | `CharField` | `running` / `pending` / `success` / `fail` |
| `start_time` | `DateTimeField` | 開始時間 |
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

# 用任務名稱觸發（--args 為 JSON 陣列，排程 model PK 為 UUID）
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

## 範例

完整的接入方式見 [`example/`](./example/) 目錄。

---

## 測試

單元測試、整合測試與端對端測試的執行方式見 [`tests/`](./tests/) 目錄。
