# ExecutionRecord 生命週期（0.3.0）

1. 依明確的 scheduler_model 或唯一 task_name 找到排程模型，再由整數 id 讀取排程。
2. 執行前建立 running 紀錄，填入模型、名稱、建立者及排程 task FK。
3. 執行業務函式並注入 record_id。同步允許本機建檔失敗時傳入 None；非同步需 require_record=True。
4. 回傳 (instance, True, message) 將紀錄設為 success，維持回傳紀錄 ID。
5. 回傳 False 記錄 fail 並拋出 CeleryKitError；格式錯誤同樣視為失敗。
6. 未捕捉例外記錄 fail，訊息為內建代碼 `schedule_kit.task_raised`，參數只保存例外類別名稱；紀錄寫入失敗不取代原例外。
7. 回傳 None 表示 pending；update_record() 或逾時清理決定終態。
8. 本機終態成功落地後才共寫。共用表 INSERT 與 main_synced_at 同交易，失敗可重試且不重複寫入；快速 callback 不被 pending 覆寫。

主專案共寫需 WRITE_MAIN_EXECUTION_RECORDS=True 與唯一 EXECUTION_SOURCE，並與主專案共用 DB、PeriodicTask 及使用者。
套件不管理主專案的 migration。詳見 [接入指引](integration.md)。

本機欄位 task_id 為整數排程 ID，celery_task_id 為 Celery UUID。
occurred_at 為開始時間；主專案對應欄位為 start_time。
本機保留 running/pending/success/fail，主專案只寫 success/fail 終態。

模型識別為來源加模型完整名稱；未同步終態不會被本機清理刪除。重複 callback 及 maintenance 可補送，須依接入指引設定 maintenance 排程。

## 執行訊息代碼與多語系（0.3.0）

任務回傳的 `message`、`update_record()` 與 `finish_record()` 的 `message` 可以是純文字，或 `ExecutionMessage`（訊息代碼 + 英文 msgid + 參數）：

```python
from django.utils.translation import gettext_noop
from schedule_kit.messages import ExecutionMessage

# msgid 以 gettext_noop 標記，makemessages 才抓得到；代碼以專案名稱為前綴
DELIVERY_FAILED = ExecutionMessage(
    "messagecenter.dashboard.delivery_failed",
    gettext_noop("Dashboard report delivery failed for %(recipient_count)d recipients"),
)


@recorded_task(name="messagecenter.dashboard_mail", scheduler_model=DashboardTask)
def dashboard_mail(task_id, record_id=None):
    ...
    return task, False, DELIVERY_FAILED.with_params(recipient_count=5)
```

完成紀錄時，套件依 `settings.LANGUAGES` 逐語系（`translation.override`）渲染 msgid 並代入參數，結束後恢復 worker 原本的語系：

| 欄位 | 內容 |
| --- | --- |
| `message` | 英文版本（截斷至 4000 字元），作為 fallback 與文字過濾用 |
| `message_code` | 訊息代碼 |
| `message_params` | 參數（JSON 物件，值只能是字串、數字、布林或 null） |
| `message_i18n` | `{"en": "...", "zh-hant": "..."}`，key 為小寫、`-` 分隔的語系代碼 |

- 純文字訊息維持 0.2.0 行為：只寫 `message`，三個欄位為 null。
- 代碼須為 1–100 字元的英數字、`.`、`_`、`-`，並含專案前綴（例如 `messagecenter.`）；不合法時建立訊息即拋出 `ImproperlyConfigured`。
  建議在模組層級定義訊息常數，錯誤會在 import 時就出現，不會產生紀錄；若在任務執行中才建立不合法的訊息，該例外會依一般例外處理，紀錄為 `schedule_kit.task_raised`（`exception` 為 `ImproperlyConfigured`）。
- 某語系沒有譯文時使用英文 msgid；msgid 引用了不存在的參數時，該語系退回未代入參數的 msgid 原文。
- 參數不是 JSON 物件、含非純量值或無法序列化時，改記錄為 `schedule_kit.invalid_message`（log 只記原代碼，不記參數值），任務結果不變。
- `message_params` 會寫入主專案共用表，只能放可公開的值。
- 子專案的 `LOCALE_PATHS` 優先於套件的 `locale/`，可覆寫內建訊息的譯文。

讀取時以 `resolve_message(record, language=None)` 依語系挑選，回退順序與主專案相同：完整語系 → 主語系 → `en` → `message`。套件的執行紀錄 API 回傳依請求語系（需要 `LocaleMiddleware`）挑選的 `message`，以及 `message_code`、`message_params`，不輸出 `message_i18n`。

### 內建訊息代碼

| 常數 | 代碼 | 參數 | 英文 msgid |
| --- | --- | --- | --- |
| `TASK_RAISED` | `schedule_kit.task_raised` | `exception`（例外類別名稱） | `Task raised %(exception)s` |
| `INVALID_RETURN` | `schedule_kit.invalid_return` | — | `Task must return (instance, success, message)` |
| `INVALID_SUCCESS` | `schedule_kit.invalid_success` | — | `Task success must be bool or None` |
| `PENDING_TIMEOUT` | `schedule_kit.pending_timeout` | `status`（`pending`／`running`） | `timeout: %(status)s exceeded configured limit` |
| `INVALID_MESSAGE` | `schedule_kit.invalid_message` | — | `Task returned an invalid execution message` |

內建訊息附 en 與 zh_Hant 翻譯（`schedule_kit/locale`，`.mo` 隨套件發佈）。
