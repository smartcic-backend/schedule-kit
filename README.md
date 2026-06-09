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
| `title` | `CharField(70)` | 排程名稱，全域唯一 |
| `description` | `TextField` | 排程描述 |
| `status` | `CharField` | `active` / `disabled` |
| `execution_cycle` | `CharField(128)` | 排程字串（見下方格式說明） |
| `timezone` | `CharField(64)` | 排程時區，預設 `UTC` |
| `task` | `OneToOneField` | 關聯的 `PeriodicTask`（套件自動維護） |
| `created_at` | `DateTimeField` | 建立時間 |
| `updated_at` | `DateTimeField` | 更新時間 |

子類必須實作 `get_task_args() -> list`，回傳 Beat dispatch 時帶入的參數。
子類必須定義 `task_name: str`，與 `@recorded_task(name=...)` 的值一致。

#### execution_cycle 格式

支援 **crontab**（`*/5 * * * *`）和 **@every**（`@every 30s`）兩種格式。詳見 [`mds/execution_cycle.md`](./mds/execution_cycle.md)。

---

### ExecutionRecord

每次排程執行後自動寫入的紀錄，用來觀測背景任務有沒有跑、結果如何。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `task_title` | `CharField` | 排程名稱 |
| `task_function` | `CharField` | Celery task name |
| `task_model` | `CharField` | 排程 model 的類別名稱 |
| `task_id` | `IntegerField` | 排程 model 的 PK |
| `task_created_by_id` | `IntegerField` | 建立者 ID（取不到時為空） |
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

### 設定參數（CELERY_SCHEDULER）

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `QUEUE_NAME` | `"celery"` | Worker 監聽的 queue 名稱 |
| `TIMEZONE` | `"UTC"` | 新建排程的預設時區 |
| `SAFETY_MARGIN_SECONDS` | `30` | expire 計算的安全邊際（秒） |
| `MIN_EXPIRE_SECONDS` | `60` | expire 下限（秒） |
| `MAX_EXPIRE_SECONDS` | `86400` | expire 上限（秒） |
| `TASK_RECORD_KEEP_MAX_COUNT` | `1000` | 同一排程最多保留幾筆執行紀錄 |
| `TASK_RECORD_KEEP_MAX_DAYS` | `30` | 執行紀錄保留天數上限 |
| `PENDING_TIMEOUT_HOURS` | `24` | pending 超過幾小時自動標為 fail |

---

## 範例

完整的接入方式見 [`example/`](./example/) 目錄。

---

## 測試

單元測試、整合測試與端對端測試的執行方式見 [`tests/`](./tests/) 目錄。
