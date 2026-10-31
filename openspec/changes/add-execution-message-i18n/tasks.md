# Tasks

## 1. 前置與分支

- [x] 1.1 確認 0.2.0 分支 `feat/integer-ids-shared-execution-records` 已合併到 main，從最新 main 切出 `feat/execution-message-i18n`；驗證：`git log` 含 0.2.0 commit `813d512`，`pytest` 在新分支全數通過
- [x] 1.2 確認主專案 oivsion360 的 `celery_skdl.0042` 欄位定義（`message_code` varchar(100)、`message_params`／`message_i18n` jsonb，全部可為 NULL），並在 `tests/test_recording.py` 新增帶新欄位的主表 fixture `main_table_i18n`，保留原 `main_table` 作為舊 schema；驗證：兩個 fixture 都能建表與刪除

## 2. 執行訊息與多語系渲染（spec: execution-message-i18n）

- [x] 2.1 新增 `src/schedule_kit/messages.py`：`ExecutionMessage`（代碼格式驗證、不可變）、`render_all_languages()`（依 D1／D4，用 `translation.override` 逐語系渲染，結束後恢復原語系）、`resolve_message()`（回退規則與主專案相同）；驗證：新增 `tests/test_messages.py`，涵蓋合法／不合法代碼、兩種語系、缺譯文、缺參數、參數不可序列化、worker 語系不受影響
- [x] 2.2 定義內建訊息常數 `TASK_RAISED`、`INVALID_RETURN`、`INVALID_SUCCESS`、`PENDING_TIMEOUT`、`INVALID_MESSAGE`（msgid 用 `gettext_noop`）；驗證：`tests/test_messages.py` 確認每個常數都能在 en／zh-hant 下渲染
- [x] 2.3 建立 `src/schedule_kit/locale/{en,zh_Hant}/LC_MESSAGES/django.po`，執行 `makemessages`／`compilemessages` 產生 `.mo`，並在 `pyproject.toml` 加上 `[tool.setuptools.package-data]` 打包 `locale/**/*.po`、`*.mo`；驗證：`python -m build` 產出的 wheel 內含 `.mo`，`tests/settings.py` 加入 `LANGUAGES=[("en",...),("zh-hant",...)]` 後，zh-hant 渲染出中文

## 3. 本地模型、紀錄流程與 API（spec: execution-message-i18n）

- [x] 3.1 `models/execution.py` 新增 `message_code`、`message_params`、`message_i18n`（全部可為 NULL），並為 `task_model` 加 `db_index=True`；產生 `migrations/0005_executionrecord_message_i18n.py`；驗證：`python manage.py makemigrations --check` 無差異，migrate／reverse 0005 都成功
- [x] 3.2 `recording.finish_record()` 接受 `ExecutionMessage | str`，在同一個 UPDATE 中寫入 `message`（英文，截斷至 4000）與三個欄位；`str` 時三個欄位寫入 null；驗證：`tests/test_recording.py` 新增執行訊息完成與純文字完成兩個案例
- [x] 3.3 `decorators.recorded_task` 的例外、回傳格式錯誤、success 型別錯誤改用內建訊息（例外只放類別名稱）；task 回傳的第三個值可為 `ExecutionMessage`；驗證：既有 `test_exception_has_owner_and_does_not_leak_exception_message` 改為斷言 `message_code=schedule_kit.task_raised` 且所有欄位不含例外內容，並新增回傳 `ExecutionMessage` 的案例
- [x] 3.4 `api.update_record(record_id, success, message)` 接受 `ExecutionMessage | str`；`tasks/maintenance.py` 的逾時訊息改用 `PENDING_TIMEOUT`（參數 `{"status": ...}`）；驗證：`test_timeout_is_written_to_main` 斷言代碼與 zh-hant 內容，`test_pending_callback_failure_is_shared` 新增傳入 `ExecutionMessage` 的版本
- [x] 3.5 `serializers/execution.py` 新增 `message_code`、`message_params`，`message` 依請求語系呈現，不輸出 `message_i18n`；驗證：`tests/test_views.py` 以 `Accept-Language: zh-hant`／`en` 及舊紀錄（null）三種情況呼叫列表 API
- [x] 3.6 更新 `mds/record_flow.md`（訊息代碼、多語系產生、內建代碼表）；驗證：文件中的範例程式片段與 2.1 測試使用的 API 一致

## 4. 主表投影與傳輸層（spec: main-execution-record-projection）

- [x] 4.1 新增 `src/schedule_kit/transports.py`：`MainRecordTransport` 介面與 `DbTransport`（搬移 `_insert_main_record` 與主表清理）；`conf.py` 新增 `EXECUTION_TRANSPORT`（預設 `db`）與 `get_execution_transport()`；`write_main_record()` 改為呼叫 transport，交易與 row lock 範圍不變；驗證：既有 `test_recording.py` 投影相關案例（冪等、重試、marker 失敗回滾）全部通過
- [x] 4.2 `DbTransport` 依 D5 偵測主表欄位（快取 300 秒，偵測失敗不快取），有新欄位時寫入三個欄位，沒有時只寫舊欄位並記錄一次 warning；驗證：`main_table_i18n` 下主表三欄與本地相同；`main_table`（舊 schema）下投影成功、`main_synced_at` 已設定、warning 只出現一次
- [x] 4.3 不支援的 `EXECUTION_TRANSPORT` 在 `scheduler_identity(None)` 前置驗證時拋出 `ImproperlyConfigured`；驗證：新增測試，設定 `rbmq` 時業務函式未被呼叫，錯誤訊息列出支援的值
- [x] 4.4 更新 `mds/settings.md`（`EXECUTION_TRANSPORT`、欄位偵測行為）與 `mds/integration.md`「寫入主專案執行紀錄」一節（主專案 `0042` 相依、降級行為）；驗證：設定表與 `conf._DEFAULTS` 一致

## 5. 來源隔離（spec: execution-record-source-isolation）

- [x] 5.1 新增 `recording.own_records(queryset)`（依 D7），套用到 maintenance 的逾時、`retry_pending_main_records()`、天數與筆數清理；驗證：新增測試，表中同時有 `example-service:` 與 `other-service:` 紀錄，逾時、補送、清理只影響本來源，且沒有「來源不符」的 error log
- [x] 5.2 未啟用共寫時，清理只處理沒有來源前綴的紀錄（以及有設定時本專案前綴的紀錄）；驗證：新增測試，未啟用共寫時，他人來源的過期且未同步紀錄保留
- [x] 5.3 `update_record()` 遇到其他來源的紀錄時不更新，只記錄 warning；驗證：新增測試，紀錄狀態不變，回呼不拋例外
- [x] 5.4 在 `mds/integration.md` 新增「多專案共用資料庫」一節：同一個 DB 中所有專案必須使用同一版套件 migration、`EXECUTION_SOURCE` 不可重複、maintenance 只處理自己的紀錄（BREAKING 說明）；驗證：文件審閱通過

## 6. 發佈與整合驗證

- [x] 6.1 `pyproject.toml` 版本升為 `0.3.0`，README 安裝範例改為 `v0.3.0`，並新增 CHANGELOG 段落（含 BREAKING）；驗證：`pip install -e .` 後 `importlib.metadata.version("schedule-kit") == "0.3.0"`
- [x] 6.2 以 PostgreSQL 執行整合驗證（取代 docker compose e2e，經使用者同意）：`tests/test_postgres_projection.py` 在獨立的測試資料庫建立與 oivsion360 `0042` 相同結構的主表，驗證主表的 `message_i18n` 為含 en／zh-hant 的 jsonb、舊 schema 降級、缺表重試、來源隔離與 `0005` 欄位型別；驗證：`pytest` 全數通過，`pytest --ds=tests.pg_settings -m postgres` 對 PostgreSQL 17 通過
- [ ] 6.3 用 GitHub MCP 開 PR，說明主專案相依、BREAKING 行為修正與下游升級注意事項；PR 合併後發佈 tag `v0.3.0`

## Workflow follow-up

- 主專案 oivsion360 `feat/execution-record-message-i18n` 應先合併部署。
- 發佈 v0.3.0 後，再進行 MessageCenter 的 `adopt-schedule-kit` change。
- 通知 alertv2 負責人改釘 `v0.3.0` 並執行 `migrate schedule_kit`。
- 審查完成後 archive 本 change。
