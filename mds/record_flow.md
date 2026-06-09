# ExecutionRecord 生命週期

> 說明一筆 `ExecutionRecord` 從建立到終態的完整流程，以及各欄位在哪個階段被寫入。

---

## 欄位寫入時機

| 欄位 | 建立時 (`create`) | 函式回傳後 (`save`) | `update_record` |
|------|:-----------------:|:-------------------:|:---------------:|
| `task_function` | ✓ | — | — |
| `task_id` | ✓（暫用 arg） | ✓（從 instance.pk 更正） | — |
| `celery_task_id` | ✓ | — | — |
| `status` | `"running"` | `success` / `fail` / `pending` | `success` / `fail` |
| `start_time` | ✓ | — | — |
| `periodic_task` | ✓（查 PeriodicTask） | — | — |
| `task_title` | — | ✓（`str(instance)`） | — |
| `task_model` | — | ✓（`type(instance).__name__`） | — |
| `task_created_by_id` | — | ✓（`instance.created_by.id`，取不到留 null） | — |
| `message` | — | ✓ | ✓ |
| `end_time` | — | ✓ | ✓ |

> `task_id` 在建立時先用 arg 占位，函式成功回傳後再以 `instance.pk` 更正，
> 確保最終記的是 model 層的真實 id，而非 caller 可能傳錯的值。

---

## 正常路徑：同步任務

```
wrapper(self, task_id_arg)
    │
    ├─ pt = PeriodicTask.objects.filter(task=name, args=[task_id_arg]).first()
    │
    ├─ record = ExecutionRecord.objects.create(
    │      task_function = name,
    │      task_id       = task_id_arg,   # 暫值
    │      celery_task_id= self.request.id,
    │      status        = "running",
    │      start_time    = now(),
    │      periodic_task = pt,
    │  )
    │
    │  func(*args, record_id=record.id)
    ▼
func 回傳 (instance, True, "done")
    │
    ├─ record.task_title        = str(instance)
    ├─ record.task_model        = "AlertRuleTask"
    ├─ record.task_id           = instance.pk       # 更正
    ├─ record.task_created_by_id= instance.created_by.id  # 或 null
    ├─ record.message           = "done"
    ├─ record.end_time          = now()
    └─ record.status            = "success"
       record.save()
```

---

## 正常路徑：非同步任務

函式回傳 `(instance, None, message)`，`success=None` 代表結果由外部回調補上。

```
func 回傳 (instance, None, "dispatched record_id=42")
    │
    ├─ record.task_title  = str(instance)
    ├─ record.message     = "dispatched record_id=42"
    ├─ record.end_time    = now()          # 函式結束時間，非最終完成時間
    └─ record.status      = "pending"
       record.save()

    ── 時間不定後 ──

update_record(record_id=42, success=True, message="agent ok")
    │
    └─ ExecutionRecord.objects.filter(pk=42).update(
           status   = "success",
           end_time = now(),               # 實際完成時間
           message  = "agent ok",
       )
```

> `pending` 狀態下，`end_time` 會被寫兩次：
> 第一次是函式執行完（dispatch 完成），第二次是 `update_record` 時（真正結束）。
> 最終 `end_time` 以 `update_record` 為準。

---

## 例外路徑：task 拋例外

函式執行中拋例外，wrapper 的 `except` 捕捉並立即儲存 `fail`，然後 re-raise。

```
func(*args, record_id=record.id)
    │ ← 例外
    ▼
except Exception as e:
    record.status   = "fail"
    record.end_time = now()
    record.message  = str(e)
    record.save()
    raise               ← Celery retry / 上層仍可處理
```

---

## 例外路徑：回傳格式錯誤

函式沒有拋例外，但回傳值不是 `(instance, success, message)` 三元素 tuple：

```
result = func(...)      # 例如回傳 True 或 None
    │
    ├─ isinstance(result, tuple) and len(result) == 3  → False
    │
    └─ record.status  = "fail"
       record.end_time= now()
       record.message = "@recorded_task: {name} 必須回傳 (instance, success, message)"
       record.save()
       return record.id
```

> 格式錯誤不 raise，讓 Celery 視為任務成功完成（不重試），
> 但 `ExecutionRecord` 標為 `fail` 以便排查。

---

## 狀態流轉總覽

```
                 ┌──── task 拋例外
                 │
create ──→ running ──→ success    (同步，成功)
                 │
                 ├──→ fail        (同步，失敗 / 例外 / 格式錯誤)
                 │
                 └──→ pending ──→ success    (非同步，callback 成功)
                              └──→ fail      (非同步，callback 失敗 / timeout)
```

> `pending` 沒有收到 callback 時，maintenance task 按 `CELERY_SCHEDULER` 設定的
> timeout 自動標為 `fail`（見 `tasks/maintenance.py`）。

---

## 相關程式位置

| 職責 | 位置 |
|------|------|
| record 建立 / 欄位填寫 / status 判斷 | `src/schedule_kit/decorators.py` |
| `ExecutionRecord` model | `src/schedule_kit/models/execution.py` |
| `update_record` | `src/schedule_kit/api.py` |
| pending timeout 清理 | `src/schedule_kit/tasks/maintenance.py` |
| 唯讀查詢 API | `src/schedule_kit/views/execution.py` |
