# Proposal

## Why

主專案 oivsion360 的 `celery_skdl_executionrecord` 已新增 `message_code`、`message_params`、`message_i18n` 三個可為 NULL 的欄位（migration `0042`，分支 `feat/execution-record-message-i18n`），並會依請求語系從 `message_i18n` 挑選訊息顯示。但 schedule-kit 目前只寫入純文字 `message`。紀錄在 Celery worker 中產生，worker 語系固定為 `LANGUAGE_CODE`，所以存進主表的都是英文，畫面無法依查看者的語系顯示。

此外，多個子專案（alertv2、即將導入的 MessageCenter）與主專案共用同一個 DB（`smartcicdb`），並會共用套件的本地表 `schedule_kit_executionrecord`。目前 maintenance、補送、逾時處理都沒有依 `EXECUTION_SOURCE` 過濾，會處理或刪除其他專案的紀錄。這個問題必須在更多子專案導入前修正。

## What Changes

- 新增 `ExecutionMessage`（訊息代碼 + 英文 msgid + 參數）與 `render_all_languages()`：寫入時依 `settings.LANGUAGES` 在每個語系下渲染，產生 `message_i18n`；英文版本寫入 `message` 作為 fallback。
- 套件內建通用訊息目錄（任務例外、回傳格式錯誤、pending 逾時等），附 `schedule_kit/locale/{en,zh_Hant}` 翻譯檔；套件內部原本寫死的英文訊息全部改用代碼。
- `@recorded_task` 的 task 回傳值、`update_record()`、`finish_record()` 的 message 可以是 `ExecutionMessage` 或 `str`（`str` 維持舊行為，向下相容）。
- 本地 `ExecutionRecord` 新增 `message_code`、`message_params`、`message_i18n` 三個欄位（套件 migration `0005`）；套件的執行紀錄 API 依請求語系呈現 `message`。
- 寫入主表時一併寫入三個新欄位；如果主表還沒有這些欄位（主專案尚未套用 `0042`），自動只寫舊欄位，部署順序不受限制。
- 抽出主表傳輸層介面 `MainRecordTransport`，本版只實作 `db`，由 `CELERY_SCHEDULER.EXECUTION_TRANSPORT` 選擇；之後可擴充 RabbitMQ 而不改呼叫端。
- **BREAKING（行為修正）**：共寫模式下，本地紀錄的 maintenance（逾時、補送、保留清理）只處理 `task_model` 以本專案 `EXECUTION_SOURCE:` 開頭的紀錄；未啟用共寫時，維持處理全部紀錄。
- 版本號升為 `0.3.0`，更新 `mds/record_flow.md`、`mds/settings.md`、`mds/integration.md`、README。

## Capabilities

### New Capabilities
- `execution-message-i18n`：執行訊息的代碼化與多語系渲染（`ExecutionMessage`、內建訊息目錄、`render_all_languages`、本地 API 依語系呈現）。
- `main-execution-record-projection`：本地終態紀錄投影到主專案共用表的行為（新欄位寫入、舊 schema 相容、傳輸層介面、冪等與重試）。
- `execution-record-source-isolation`：多專案共用 DB 時，本地紀錄維護作業依 `EXECUTION_SOURCE` 隔離。

### Modified Capabilities
（無：schedule-kit 尚無既有 spec。）

## Impact

- 程式：`src/schedule_kit/recording.py`、`decorators.py`、`api.py`、`conf.py`、`models/execution.py`、`serializers/execution.py`、`tasks/maintenance.py`；新增 `messages.py`、`transports.py`、`locale/`、`migrations/0005_*`。
- 相依：主專案 oivsion360 須套用 `celery_skdl.0042`，才能顯示多語系（未套用時寫入端會自動降級）。
- 文件：`mds/record_flow.md`、`mds/settings.md`、`mds/integration.md`、README（版本 0.3.0）。
- 下游：alertv2（目前釘在 `alertv2_branch`）與 MessageCenter 須升級到 0.3.0。同一個 DB 中的所有專案必須使用同一版 schedule-kit migration。
- 前提：本 change 建立在 0.2.0（分支 `feat/integer-ids-shared-execution-records`，整數 ID 與可重試主表寫入）之上，需先合併該分支。
