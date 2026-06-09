# Scheduler Package 設計計畫

> 本檔只記**大方向**。細節拆到各自的文件，見下方〔文件索引〕。

## 目標

將排程管理（建立、更新、刪除、啟用/停用）抽成獨立套件，
讓所有微服務共用相同的實作標準，避免各自實作造成的不一致。

---

## 現況問題

| 問題 | 說明 |
|------|------|
| 各服務各自實作 | 排程建立邏輯散落在不同 app，無統一介面 |
| 驗證不一致 | 部分服務未驗證 crontab 格式，`0/2 * * * *` 可存入但永遠不執行 |
| 與 Django 強耦合 | signal、model、serializer 綁在專案內，難以跨服務共用 |
| 設定硬寫 | broker URL、queue name、timezone 分散在各處 |

> 「驗證不一致」的危險在於靜默錯誤：`0/2` 語法存進 DB 不會報錯，
> 但 Celery 永遠不執行，排程看起來建立成功卻從來沒跑過，很難察覺。

---

## 核心理解：各層的職責

- **Celery Beat 只管「何時丟」**：從 `PeriodicTask` 讀排程，時間到了把 task name + args
  推進 queue，完全不關心業務邏輯（不知道 CPU 閾值、要不要送 mail）。
- **Model 管「存什麼設定」**：排程設定的儲存層，存檔瞬間 signal 自動同步到 `PeriodicTask`，
  本身不執行任務。
- **Serializer 管「能不能存、怎麼存」**：輸入的驗證與格式判讀層。
- **Task 函式管「實際跑什麼」**：`@shared_task` 是真正的業務邏輯，各服務自定，套件不介入。

> 各層職責清楚分開的好處：改排程格式驗證只動 Serializer，
> 改同步邏輯只動 sync service，業務邏輯不受影響。

---

## 套件邊界

```
套件負責                          各服務自己負責
────────────────────────────      ────────────────────────────
BaseSchedulerTask                 業務欄位（cpu_threshold 等）
crontab / @every 驗證             業務 @shared_task 函式內容
execution_cycle → Celery 轉換     業務邏輯（送 mail、判斷閾值）
post_save signal 自動同步         Model 的業務欄位驗證
PeriodicTask CRUD                 各服務的 View / URL 設定
expire_seconds 動態計算
執行紀錄（per-排程、可查詢）
@recorded_task 裝飾器（自動寫紀錄）
infra 維護任務（清理）
```

> 邊界劃分的原則：**排程基礎建設歸套件，業務邏輯歸各服務**。
> 套件不知道也不在乎 CPU 閾值是什麼、要不要送 mail。

套件標準化兩條路：
1. **排程定義 → PeriodicTask**（定義何時跑）
2. **執行觀測**：執行紀錄（看背景任務有沒有跑、跑得如何）

業務邏輯完全不碰，各微服務可獨立擴充。

---

## 套件架構

```
schedule_kit/
├── conf.py                  # 設定讀取（支援 Django settings namespace）
├── apps.py                  # AppConfig，ready() 時自動註冊 signals
├── models/
│   ├── base.py              # BaseSchedulerTask（abstract model）
│   └── execution.py         # ExecutionRecord（執行紀錄）
├── serializers/
│   ├── base.py              # BaseSchedulerSerializer（validate + @every 轉換）
│   └── execution.py         # 執行紀錄唯讀 serializer
├── views/
│   └── execution.py         # 執行紀錄唯讀 ViewSet（可對外查詢）
├── services/
│   └── sync.py              # PeriodicTask 同步邏輯
├── decorators.py            # @recorded_task（自動寫執行紀錄的合體裝飾器）
├── tasks/
│   └── maintenance.py       # 執行紀錄清理等 infra task
├── signals.py               # post_save / post_delete 動態註冊
├── utils/
│   └── cron.py              # 格式驗證、解析、interval 估算、next_run 計算
└── exceptions.py            # 套件專屬 exception
```

> `apps.py` 的 `ready()` 是整個 signal 機制的起點：Django 啟動時自動掃描所有
> `BaseSchedulerTask` 子類並掛上 signal，使用者不需要手動連接任何東西。

---

## 文件索引

| 文件 | 內容 |
|------|------|
| [base_model.md](./base_model.md) | 最基礎 model 需要哪些欄位與行為（單一 `execution_cycle` 欄位） |
| [serializer.md](./serializer.md) | 序列化要檢查什麼、支援格式、`@every` 轉換 |
| [sync.md](./sync.md) | 同步流程與規則（signal → PeriodicTask） |
| [setup.md](./setup.md) | 設定介面、設定責任範圍、接入步驟、AlertRule 範例 |
| [execution.md](./execution.md) | 執行觀測：執行紀錄、`@recorded_task` 契約、唯讀 API、infra task |

---
