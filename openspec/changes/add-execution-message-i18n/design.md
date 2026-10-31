# Design

## Context

- 0.2.0 的紀錄流程：`@recorded_task` 先建立本地 running 紀錄，`finish_record()` 更新終態，再由 `write_main_record()` 在同一交易內以 raw SQL INSERT 主表並設定 `main_synced_at`（outbox）。maintenance 負責逾時、補送與保留清理。詳見 `mds/record_flow.md`。
- 主專案 oivsion360 的 `celery_skdl.0042` 新增三個可為 NULL 的欄位：`message_code` varchar(100)、`message_params` jsonb、`message_i18n` jsonb。主專案 serializer 已依 `get_language()` 從 `message_i18n` 挑選，依序回退到主語系、`en`、`message`。
- 本地表 `schedule_kit_executionrecord` 在共用 DB 中由所有安裝套件的專案共用；`task_model` 已是 `來源:app_label.Model` 格式，可作為來源判斷依據。
- 測試使用 SQLite（`tests/settings.py`），主表由 fixture 以 raw SQL 建立。

## Goals / Non-Goals

**Goals:**
- 寫入端產生多語系內容，主專案不需收錄子專案的翻譯。
- 不論主專案是否已套用 `0042`，套件都能部署。
- 修正共用本地表的跨專案干擾，且不需要新增 DB 欄位就能判斷來源。

**Non-Goals:**
- 不實作 RabbitMQ 傳輸，只定義介面。
- 不改主專案 schema（由 oivsion360 管理）。
- 不回填既有紀錄的多語系欄位（舊紀錄回退顯示 `message`，最多保留 60 天）。
- 不處理 alertv2 的升級，只在文件中說明。

## Decisions

### D1：寫入時產生各語系版本，不在讀取時翻譯
- 做法：`render_all_languages()` 對 `settings.LANGUAGES` 逐一進入 `translation.override(lang)`，執行 `gettext(msgid) % params`。
- 理由：主專案讀取時才翻譯的話，子專案的每句訊息都要同步到主專案的 `.po`，每次新增都得跨 repo 部署。快照只依賴寫入端自己的翻譯檔。
- 保留 `message_code` + `message_params`：日後若改由主專案集中翻譯，或要做失敗原因統計，可從代碼重新產生。
- 替代方案：依排程建立者的語系只存一種語言 → 查看者語系可能不同，語言會被固定在 DB，不採用。

### D2：`ExecutionMessage` 為不可變資料類別，msgid 以 `gettext_noop` 標記
- `ExecutionMessage(code: str, msgid: str, params: dict | None = None)`，建立時驗證代碼格式。
- 子專案定義訊息時寫成 `ExecutionMessage("messagecenter.x", gettext_noop("..."), {...})`，`makemessages` 才抓得到 msgid。
- 內建訊息集中在 `schedule_kit/messages.py` 的常數，例如 `TASK_RAISED`、`INVALID_RETURN`、`INVALID_SUCCESS`、`PENDING_TIMEOUT`、`INVALID_MESSAGE`。
- 翻譯的查找順序依 Django 預設：`LOCALE_PATHS`（專案）優先於 app 的 `locale/`，所以子專案可以覆寫套件的譯文。

### D3：套件內附翻譯檔
- 新增 `src/schedule_kit/locale/{en,zh_Hant}/LC_MESSAGES/django.po/.mo`，並在 `pyproject.toml` 設定 `[tool.setuptools.package-data]` 把 `locale/**/*.mo`、`*.po` 打包進 wheel。
- `.mo` 納入版控，安裝端不需要另外執行 `compilemessages`。

### D4：渲染失敗時降級，不影響任務結果
- 單一語系渲染時發生 `KeyError`、`TypeError` 或 `ValueError` → 該語系使用未代入參數的 msgid 原文。
- 參數不是 JSON 物件，或值不是純量 → 改用 `INVALID_MESSAGE`，並記錄 log（只記代碼，不記參數值）。

### D5：主表欄位偵測（向下相容）
- 透過 `connection.introspection.get_table_description()` 偵測主表是否有 `message_i18n`，結果在行程內快取 300 秒；主專案在 worker 運行中途套用 migration 時，最多 5 分鐘就會開始寫入新欄位。
- 偵測失敗（例如表不存在）時不快取，依原本流程失敗並重試。
- 沒有新欄位時只執行 0.2.0 的 INSERT，每個行程只記錄一次 warning。
- 替代方案：用設定開關（例如 `MAIN_RECORD_I18N=True`）→ 需要每個專案配合主專案部署切換，容易出錯，不採用。

### D6：傳輸層介面
- 新增 `transports.py`：`MainRecordTransport.publish(durable_record) -> None`，由 `write_main_record()` 在現有交易與 row lock 內呼叫；`DbTransport` 封裝原本的 `_insert_main_record`（含 D5）。
- `conf.get_execution_transport()` 依 `EXECUTION_TRANSPORT` 回傳實作，不支援的值拋出 `ImproperlyConfigured`。在 `scheduler_identity(None)` 的前置驗證中一併檢查，所以會在業務程式執行前失敗。
- 主表保留清理目前直接寫 SQL；本版仍放在 `DbTransport.cleanup()`，之後換成 RabbitMQ 時由主專案端負責。

### D7：來源隔離以 `task_model` 前綴判斷
- 新增 `recording.own_records(queryset)`：
  - 啟用共寫時：`task_model__startswith=f"{source}:"`。
  - 未啟用共寫時：排除含冒號的 `task_model`（他人來源）；有設定 `EXECUTION_SOURCE` 時，也包含自己的前綴。
- maintenance 的逾時、補送與兩種清理，以及 `update_record()`，都套用此過濾。
- migration `0005` 為 `task_model` 加上 `db_index=True`，讓前綴查詢不必掃全表。
- 替代方案：新增 `source` 欄位 → 需要回填既有資料，而 `task_model` 前綴在 0.2.0 已有保證，不採用。

### D8：本地模型與 API
- migration `0005`：新增三個可為 NULL 的欄位（與主表相同型別，JSON 欄位使用 Django `JSONField`），並為 `task_model` 加索引。
- `finish_record(record, status, message)`：在交易內一次更新 `message` 與三個多語系欄位；`str` 輸入時三個欄位寫入 null。
- `ExecutionRecordSerializer` 新增 `message_code`、`message_params`，在 `to_representation` 以 `resolve_message()` 依語系挑選 `message`；`resolve_message()` 的回退規則與主專案相同。

## Risks / Trade-offs

- [新增語言時，舊紀錄沒有該語系] → 依規則回退顯示英文；紀錄最多保留 60 天。
- [欄位偵測快取期間主專案剛完成 migration] → 最多 5 分鐘只寫舊欄位，不影響正確性，只是那段期間的紀錄沒有多語系版本。
- [來源過濾改變 maintenance 行為，可能有專案依賴「清理全部紀錄」] → 列為 BREAKING（行為修正），並在 `mds/integration.md` 寫明。
- [同一個 DB 中各專案的套件 migration 版本不同] → 文件規定共用 DB 的專案必須一起升級；`0005` 只新增可為 NULL 的欄位與索引，舊版程式仍可寫入。
- [`message_params` 被放入敏感資料] → 文件規定只能放可公開的值；套件只放例外類別名稱，不放例外內容。

## Migration Plan

1. 前提：主專案 oivsion360 先部署 `celery_skdl.0042`（不是必要條件，見 D5，但這樣才會顯示多語系）。
2. 合併 0.2.0 分支後，在本 change 的分支完成實作，發佈 tag `v0.3.0`。
3. 共用 DB 的子專案（alertv2、MessageCenter）升級套件並執行 `migrate schedule_kit`（`0005`）。
4. 回滾：`0005` 只新增欄位與索引，可以 reverse；回滾後 0.2.0 程式會忽略這些欄位。

## Open Questions

- alertv2 的 `alertv2_branch` 何時改回釘 `v0.3.0` tag，由 alertv2 負責人另行排程（不影響本 change 的規格與任務）。
