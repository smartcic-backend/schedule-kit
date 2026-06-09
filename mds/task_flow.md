# 非同步任務執行流程

> 說明 `@recorded_task` 如何處理兩種任務模式，以及非同步任務的 `record_id` 傳遞機制。

---

## 同步任務流程

任務函式跑完就知道結果，`running → success/fail` 一次完成。

```
Celery Beat
    │
    │ dispatch("alert_rule_task", args=[task_id])
    ▼
wrapper(self, task_id)                          ← @shared_task(bind=True) 自動生成
    │
    ├─ PeriodicTask.objects.filter(task=name, args=[task_id]).first()
    │  取得對應的 PeriodicTask 實例
    │
    ├─ ExecutionRecord.objects.create(
    │      status="running",
    │      celery_task_id=self.request.id       ← Celery worker UUID，供除錯用
    │  )  →  record.id = 42
    │
    │ func(task_id, record_id=42)               ← 直接注入 record_id
    ▼
alert_rule_task(task_id, record_id=42)
    │
    ├─ AlertRuleTask.objects.get(id=task_id)
    └─ AlertRuleService.check_and_notify(task)  → (success, message)
       return (task, success, message)
    │
    ▼
wrapper 收到 (task, success, message)
    │
    └─ record.status = "success" or "fail"
       record.end_time = now()
       record.save()
```

---

## 非同步任務流程

任務函式只負責派發工作，真正結果由外部 agent 回調補上。
`running → pending`，再由 callback 更新成 `success/fail`。

### 第一段：派發

```
Celery Beat
    │
    │ dispatch("alert_rule_async_task", args=[task_id])
    ▼
wrapper(self, task_id)
    │
    ├─ ExecutionRecord.objects.create(
    │      status="running",
    │      celery_task_id=self.request.id
    │  )  →  record.id = 42
    │
    │ func(task_id, record_id=42)               ← 直接注入 record_id，不需反查
    ▼
alert_rule_async_task(task_id, record_id=42)
    │
    └─ AlertRuleService.dispatch_to_agent(task, record_id=42)
           │
           └─ HTTP POST agent_url  { record_id: 42, callback_url: "..." }
       return (task, None, "dispatched record_id=42")
    │
    ▼
wrapper 收到 success=None
    │
    └─ record.status = "pending"
       record.save()
```

### 第二段：回調（非同步，時間不定）

```
外部 Agent
    │
    │ POST /api/agent-callback/  { record_id: 42, success: true, message: "..." }
    ▼
agent_callback(request)                         ← example/views.py
    │
    └─ AlertRuleService.handle_agent_callback(record_id=42, success=True, message)
           │
           └─ update_record(record_id=42, success=True, message)
                  │
                  └─ ExecutionRecord.objects.filter(pk=42).update(
                         status="success",
                         end_time=now(),
                         message=message
                     )
```

---

## record_id 傳遞方式的演進

| 版本 | 方式 | 問題 |
|------|------|------|
| 舊版 | `ExecutionRecord.objects.filter(task_id=task_id).latest("start_time")` | 並發時可能拿到別的 worker 建立的那筆 |
| 現版 | decorator 建立 record 後直接 inject `record_id=record.id` 給函式 | 確定對應，無 race condition |

---

## 狀態流轉

```
同步任務：  running ──────────────────────→ success / fail
非同步任務：running → pending ─(callback)─→ success / fail
```

> `pending` 若長時間未更新，maintenance task 會自動標為 `fail`（依 `CELERY_SCHEDULER` 設定的 timeout）。

---

## 相關程式位置

| 職責 | 位置 |
|------|------|
| `wrapper` / record 建立 / record_id 注入 | `src/schedule_kit/decorators.py` |
| `update_record` | `src/schedule_kit/api.py` |
| `ExecutionRecord` model | `src/schedule_kit/models/execution.py` |
| 同步任務範例 | `example/tasks.py → alert_rule_task` |
| 非同步任務範例 | `example/tasks.py → alert_rule_async_task` |
| Callback endpoint | `example/views.py → agent_callback` |
| Agent dispatch / callback 處理 | `example/services.py → AlertRuleService` |
