# 測試清單

> 依序執行，每個段落都通過後再進下一段。
> 指令預設在 docker compose 環境下執行；本機開發去掉 `docker compose exec web`。

---

## 0. 環境啟動

- [ ] `docker compose up --build` 無錯誤
- [ ] `docker compose exec web python manage.py migrate` 無錯誤
- [ ] `docker compose exec web python manage.py createsuperuser` 建立測試帳號
- [ ] 瀏覽器開 `http://localhost:8000/admin/`，登入成功
- [ ] Admin 左側可看到 **Periodic tasks**（django_celery_beat）和 **Alert rule tasks**（example）

---

## 1. 排程建立 → PeriodicTask 自動同步

**操作**：POST `/api/alert-rules/`

```json
{
  "title": "CPU 監控 - production",
  "execution_cycle": "*/5 * * * *",
  "cpu_threshold": 80,
  "target_host": "prod-server-01",
  "notify_email": "ops@example.com"
}
```

- [ ] 回傳 `201`，包含 `id`
- [ ] Admin → Periodic tasks 出現一筆 `alert_rule_task`，enabled = true
- [ ] Periodic task 的 crontab 欄位是 `*/5 * * * *`

---

## 2. Serializer 驗證

**不合法的 crontab**：`execution_cycle: "0/2 * * * *"`
- [ ] 回傳 `400`，錯誤訊息提示 `0/2` 不支援，請改用 `*/2`

**欄位數不對的 crontab**：`execution_cycle: "* * * *"`
- [ ] 回傳 `400`，錯誤訊息提示欄位數錯誤

**合法的 @every**：`execution_cycle: "@every 1h30m"`
- [ ] 回傳 `201`
- [ ] Admin → Periodic tasks 的 interval 顯示 5400 秒

**不合法的 @every**：`execution_cycle: "@every 1hour"`
- [ ] 回傳 `400`

**業務欄位驗證**：`cpu_threshold: 150`
- [ ] 回傳 `400`，錯誤訊息提示閾值必須在 1～100 之間

---

## 3. 排程更新 → PeriodicTask 同步

**操作**：PATCH `/api/alert-rules/{id}/`

```json
{ "execution_cycle": "0 * * * *" }
```

- [ ] 回傳 `200`
- [ ] Admin → Periodic tasks 該筆 crontab 已更新為 `0 * * * *`

**停用排程**：PATCH `{ "status": "disabled" }`
- [ ] Admin → Periodic tasks 該筆 enabled = false（Beat 不再 dispatch）

**重新啟用**：PATCH `{ "status": "active" }`
- [ ] Admin → Periodic tasks 該筆 enabled = true
- [ ] `next_run_time` 從 null 變回有值

---

## 4. 排程刪除

**操作**：DELETE `/api/alert-rules/{id}/`

- [ ] 回傳 `204`
- [ ] Admin → Periodic tasks 對應的 PeriodicTask 也消失

---

## 5. Worker 執行 + ExecutionRecord

> 需要 Worker container 正在跑。

**準備**：建立一個 `execution_cycle: "@every 30s"` 的排程，等待 Beat dispatch。

- [ ] `docker compose logs worker` 出現 `Task alert_rule_task received`
- [ ] GET `/api/alert-rules/executions/` 出現至少一筆紀錄
- [ ] 紀錄的 `status` 為 `success` 或 `fail`（不是 `running`）
- [ ] `start_time` 和 `end_time` 都有值
- [ ] `task_title` 對應到排程的 title

**模擬失敗**：讓 `_get_cpu_usage` 拋出例外（改 services.py 暫時 raise）
- [ ] ExecutionRecord 的 `status` 為 `fail`
- [ ] `message` 欄位包含例外訊息

---

## 6. 執行紀錄唯讀 API

- [ ] GET `/api/executions/` 回傳 `200`
- [ ] POST `/api/executions/` 回傳 `405`（不允許新增）
- [ ] PUT `/api/executions/{id}/` 回傳 `405`（不允許修改）
- [ ] DELETE `/api/executions/{id}/` 回傳 `405`（不允許刪除）

---

## 7. 執行紀錄 Filter

> 前置條件：至少有兩個不同 `task_id` 的排程，各自有 success 和 fail 的紀錄。

### 套件提供的基本 filter

**`?task_id={id}`**：查某個排程的所有執行紀錄
- [ ] 只回傳該 `task_id` 的紀錄，不夾雜其他排程

**`?periodic_task={id}`**：透過 PeriodicTask FK 查
- [ ] 只回傳對應 PeriodicTask 的紀錄

**`?status=success`**
- [ ] 只回傳 `status=success` 的紀錄

**`?status=fail`**
- [ ] 只回傳 `status=fail` 的紀錄

**`?status=pending`**（需有 async 任務執行中）
- [ ] 只回傳 `status=pending` 的紀錄

### 各服務擴充的 filter（AlertRuleExecutionFilterSet）

**`?start_time_after=2026-06-01T00:00:00`**
- [ ] 只回傳 `start_time >= 2026-06-01T00:00:00` 的紀錄

**`?start_time_before=2026-06-01T23:59:59`**
- [ ] 只回傳 `start_time <= 2026-06-01T23:59:59` 的紀錄

**組合查詢**：`?task_id={id}&status=fail&start_time_after=2026-06-01T00:00:00`
- [ ] 只回傳符合所有條件的紀錄

> `?task_id=` 和 `?status=` 的基本 filter 已有自動化測試（`test_views.py`）。`?periodic_task=`、`?start_time_after/before` 為手動驗證項目。

---

## 8. 非同步任務（mock-agent 三種情境）

### 環境架構

docker-compose 額外啟動一個 `mock-agent` 服務（port 8001），模擬外部 agent 的行為。

```
┌──────────────────────────┐  dispatch(record_id)   ┌─────────────────────┐
│  web + worker + beat     │ ─────────────────────→ │  mock-agent :8001   │
│  (Django + Celery)       │ ←───────────────────── │                     │
│                          │  callback(success/fail) │  依序三種回應行為   │
└──────────────────────────┘                         └─────────────────────┘
```

**mock-agent 回應順序**（每次收到 dispatch 依序執行）：

| 第幾次 | 行為 | 等待 |
|--------|------|------|
| 第一次 | 回調 `success=True` | 等 5 秒後回調 |
| 第二次 | 回調 `success=False` | 等 5 秒後回調 |
| 第三次 | 不回調 | 永遠不回應 |

**docker-compose.yml 需新增**：

```yaml
mock-agent:
  build: ./mock_agent
  ports:
    - "8001:8001"
```

**呼叫流程**：
1. `_dispatch_to_agent(task)` → POST `http://mock-agent:8001/dispatch`，帶入 `record_id` 和 callback URL
2. mock-agent 等待後 → POST 回主服務的 callback endpoint（例如 `/api/agent-callback/`）
3. callback endpoint 內部呼叫 `update_record(record_id, success, message)`

---

### 情境一：Agent 成功回調

- [ ] 建立 `execution_cycle: "@every 30s"` 的非同步排程，等 Beat dispatch
- [ ] `docker compose logs worker` 出現 `alert_rule_async_task received`
- [ ] **立刻**查 `GET /api/alert-rules/executions/` → 最新一筆 `status=pending`，`end_time` 為空
- [ ] 等待約 10 秒（mock-agent 5 秒處理 + 網路傳輸）
- [ ] 再次查詢 → `status=success`，`end_time` 有值

---

### 情境二：Agent 失敗回調

> 前置：情境一已跑完，mock-agent 進入第二次行為

- [ ] 等下一次 Beat dispatch（或手動觸發）
- [ ] 立刻查 → `status=pending`
- [ ] 等待約 10 秒
- [ ] 再次查詢 → `status=fail`，`message` 包含失敗原因，`end_time` 有值

---

### 情境三：Agent 不回應（timeout）

> 前置：情境二已跑完，mock-agent 進入第三次行為（永遠不回調）

- [ ] 等下一次 Beat dispatch
- [ ] 立刻查 → `status=pending`
- [ ] 等待約 10 秒 → 仍為 `pending`（確認 mock-agent 真的沒有回調）
- [ ] 手動觸發 maintenance task（or 等 maintenance 排程）
- [ ] 查詢 → `status=fail`，`message` 包含 timeout 相關說明

---

## 9. 執行紀錄清理

**設定短保留期**（修改 settings.py）：
```python
"TASK_RECORD_KEEP_MAX_COUNT": 3,
"TASK_RECORD_KEEP_MAX_DAYS": 1,
```

- [ ] 手動觸發 maintenance task 後，同一 `task_id` 只剩最新 3 筆
- [ ] 超過 1 天的紀錄被刪除
- [ ] `pending` 超過 `PENDING_TIMEOUT_HOURS` 的紀錄自動標為 `fail`
- [ ] `running` 超過 `PENDING_TIMEOUT_HOURS` 的紀錄也自動標為 `fail`（worker 異常中斷的情況）

---

## 10. 權限

**未登入**：
- [ ] GET `/api/alert-rules/` 回傳 `403`
- [ ] GET `/api/alert-rules/executions/` 回傳 `403`

**一般用戶**（非 staff）：
- [ ] GET `/api/alert-rules/executions/` 只看到自己建立的排程紀錄
- [ ] 看不到其他用戶的紀錄

**Staff 用戶**：
- [ ] GET `/api/executions/` 看到所有紀錄

> 權限過濾已有自動化測試（`test_views.py::test_regular_user_sees_only_own_records`、`test_staff_user_sees_all_records`）。
