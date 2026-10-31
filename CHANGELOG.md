# Changelog

## 0.3.1

### BREAKING（修正）
- crontab 型 `execution_cycle` 的欄位順序改為「分 時 星期 日 月」，與主專案 oivsion360 的 `crontab_display`
  及既有子專案（MessageCenter）一致。0.3.0 以前依標準 cron「分 時 日 月 星期」解讀。
  - 第 3～5 欄相同（例如 `0 8 * * *`、`*/5 * * * *`）的排程不受影響。
  - 其他排程升級前須把 `execution_cycle` 改寫成新順序（`日 月 星期` → `星期 日 月`），
    再執行 `resync_all()` 重建 CrontabSchedule。
- 新增 `utils.cron.split_crontab()`，`validate_crontab()`／`get_or_create_schedule()` 皆透過它解析。

## 0.3.0

前提：建立在 0.2.0（整數排程 ID、可重試的主表寫入）之上。

### Added
- `schedule_kit.messages.ExecutionMessage`（訊息代碼 + 英文 msgid + 參數）。完成紀錄時依 `settings.LANGUAGES` 逐語系渲染，
  寫入 `message_i18n`；`message` 固定為英文版本。任務回傳值、`update_record()`、`finish_record()` 都接受 `ExecutionMessage` 或純文字。
- 內建訊息代碼 `schedule_kit.task_raised`、`invalid_return`、`invalid_success`、`pending_timeout`、`invalid_message`，
  附 en／zh_Hant 翻譯（`.mo` 隨套件發佈）。
- 本地 `ExecutionRecord` 新增 `message_code`、`message_params`、`message_i18n`，並為 `task_model` 加索引（migration `0005`）。
- 套件的執行紀錄 API 依請求語系呈現 `message`，並輸出 `message_code`、`message_params`（不輸出 `message_i18n`）。
- 寫入主表時一併寫入三個多語系欄位；主表尚未套用 oivsion360 `celery_skdl.0042` 時自動只寫舊欄位（每個行程一次 warning）。
- `CELERY_SCHEDULER.EXECUTION_TRANSPORT`（預設且目前唯一支援 `db`）與 `MainRecordTransport` 介面；不支援的值在任務執行業務程式前拋出 `ImproperlyConfigured`。
- `recording.own_records(queryset)`：依 `EXECUTION_SOURCE` 過濾本專案的本地紀錄。

### Changed
- 套件產生的訊息改用內建代碼。未捕捉例外的訊息由 `Task raised <類別>` 改為代碼 `schedule_kit.task_raised`，參數只含例外類別名稱；
  英文 `message` 內容與 0.2.0 相同。

### BREAKING（行為修正）
- 多個專案共用同一個 DB 時，maintenance 的逾時處理、補送主表與天數／筆數清理只處理本專案來源的紀錄：
  啟用共寫時為 `task_model` 以 `<EXECUTION_SOURCE>:` 開頭；未啟用共寫時為沒有來源前綴的紀錄，以及本專案前綴的紀錄（有設定時）。
  0.2.0 會處理整張表。
- `update_record()` 收到其他來源的紀錄時不更新，只記錄 warning。
- 同一個 DB 中所有專案必須升級到同一版套件並執行 `migrate schedule_kit`。

### 升級
1. 主專案 oivsion360 部署 `celery_skdl.0042`（非必要，但這樣主專案才會顯示多語系）。
2. 共用 DB 的所有子專案（alertv2、MessageCenter）升級到 `v0.3.0` 並執行 `python manage.py migrate schedule_kit`。
3. 要讓套件 API 依語系呈現訊息，Django 設定須有 `LANGUAGES` 與 `django.middleware.locale.LocaleMiddleware`。
4. 回滾：`0005` 只新增可為 NULL 的欄位與索引，可以 reverse（會移除多語系欄位內容）。
