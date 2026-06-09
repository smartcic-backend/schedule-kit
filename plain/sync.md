# 同步流程與規則（套件內部）

> Model 存檔的瞬間，套件透過 signal 自動把排程同步到 `PeriodicTask`，Beat 再從那裡讀取。
> 整段對使用者透明，不需要呼叫任何函式。
>
> 使用者只需要 `.save()`，套件負責讓 Beat 知道「什麼任務、何時跑、帶什麼參數」。

---

## 同步流程

```
Model.save()
  → post_save signal（AppConfig.ready() 自動掛載所有子類）
    → 驗證 / 解析 execution_cycle 格式
      → 建立 CrontabSchedule 或 IntervalSchedule
        → 建立或更新 PeriodicTask（含 task name、args、queue、enabled）
          → Celery Beat 讀取並派發到 queue
            → Worker 執行 @recorded_task 函式
```

- signal 掛載：`AppConfig.ready()` 動態掛到所有 `BaseSchedulerTask` 子類（`post_save` / `post_delete`）。

  > `AppConfig.ready()` 是 Django 應用程式啟動時的鉤子，在這裡掛 signal 確保
  > 所有子類都能被覆蓋到，使用者不需要在自己的 app 裡手動連接 signal。

- `status`（active / disabled）對應到 `PeriodicTask.enabled`。
- 任務參數來自 model 的 `get_task_args()`。

### 職責分工（驗證 vs 解析 vs 同步）

| 層 | 職責 |
|----|------|
| serializer（[serializer.md](./serializer.md)） | 只判定 `execution_cycle` 合不合法，不合法就 `raise` |
| `utils/cron.py` | 把 `execution_cycle` **解析成** `CrontabSchedule` / `IntervalSchedule` |
| **sync service（本檔）** | 拿 `utils/cron.py` 的解析結果**建立 / 更新 PeriodicTask**，不重新解析字串 |

---

## 同步規則

### 建立時設定 `start_time`，後續更新不重設

Beat 計算「下次執行時間」是從 `start_time` 開始往後推算排程。
如果每次 `.save()` 都把 `start_time` 重設成現在，Beat 的計算基準就會跑掉。

> **30 年回溯問題**：若 `start_time` 沒設（預設為 epoch 或很久以前的時間），
> Beat 啟動時會發現「從 start_time 到現在中間有幾千次沒跑的排程」，
> 嘗試一口氣補跑，造成任務爆炸性堆積。正確做法是建立時設為現在，往後只往未來算。

### 停用 → 啟用時補上 `last_run_at = now`

如果不補，Beat 會從「上次跑的時間」往後算，可能發現「停用期間累積了很多次沒跑的」，
一啟用就瞬間補跑大量任務。補上 `last_run_at = now` 讓 Beat 從現在開始計算，跳過停用期間。

### 排程定義變更時重設 `last_run_at`

`execution_cycle` 改了（例如從 `*/5 * * * *` 改成 `0 * * * *`），
舊的 `last_run_at` 是按舊排程跑的，拿舊基準套新排程可能立刻補觸發或延遲很久才跑。
重設為現在讓新排程從當下開始計算。

### 動態計算 `expire_seconds`（防 backlog）

Beat 把任務推進 queue 後，任務要等 Worker 閒下來才能執行。
如果 Worker 很忙、queue 裡積了很多任務，等到輪到這個任務時可能已經過了好幾個排程週期。

`expire_seconds` 設定任務在 queue 裡最多等多久，超過就自動作廢，
避免過期的任務還在跑（例如 5 分鐘一次的任務積壓到下一個週期才跑，結果兩次重疊執行）。

> expire 相關參數（`SAFETY_MARGIN_SECONDS`、`MIN_EXPIRE_SECONDS`、`MAX_EXPIRE_SECONDS`）
> 從 `CELERY_SCHEDULER` 設定讀取，見 [setup.md](./setup.md)。
>
> 計算邏輯：根據 `execution_cycle` 估算排程週期長度，乘以係數後夾在 min/max 之間，
> 確保短週期任務的 expire 不會太長（導致一直重疊），長週期任務的 expire 不會太短（導致還沒跑就作廢）。
