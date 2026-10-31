# Spec Delta

## Purpose

定義本地終態執行紀錄投影到主專案共用表 `celery_skdl_executionrecord` 的契約，包含多語系欄位寫入、與舊版主表 schema 的相容，以及可抽換的傳輸方式。

## ADDED Requirements

### Requirement: 投影時寫入多語系欄位
啟用共寫且主表具備 `message_code`、`message_params`、`message_i18n` 欄位時，系統 SHALL 將本地紀錄的三個欄位連同既有欄位一起寫入主表。`message` MUST 為英文版本且截斷至 4000 字元。

#### Scenario: 以執行訊息完成並寫入主表
- **WHEN** 任務以執行訊息成功完成，且主表已套用 oivsion360 `celery_skdl.0042`
- **THEN** 主表新增一筆 `result=success` 的紀錄，三個多語系欄位與本地紀錄相同

#### Scenario: 純文字訊息寫入主表
- **WHEN** 任務以純文字訊息完成
- **THEN** 主表紀錄的三個多語系欄位為 null

### Requirement: 主表沒有新欄位時自動降級
當主表尚未具備多語系欄位時，系統 SHALL 只寫入 0.2.0 的既有欄位，投影 MUST 成功並標記為已同步。每個 worker 行程 MUST 只記錄一次降級警告。

#### Scenario: 主專案尚未套用 migration
- **WHEN** 主表沒有 `message_i18n` 欄位，任務以執行訊息完成
- **THEN** 主表新增紀錄，`message` 為英文版本，本地紀錄標記為已同步，log 出現一次降級警告

### Requirement: 投影維持冪等與可重試
多語系欄位的加入 MUST NOT 改變 0.2.0 的投影保證：本地終態成功落地後才投影；主表 INSERT 與本地同步標記在同一交易；失敗時本地終態保留，並由重複回呼或 maintenance 重試，不重複寫入。

#### Scenario: 主表寫入失敗後重試
- **WHEN** 第一次主表 INSERT 失敗，之後 maintenance 重試成功
- **THEN** 主表只有一筆該執行的紀錄，且多語系欄位完整

### Requirement: 傳輸方式可設定
系統 SHALL 由 `CELERY_SCHEDULER.EXECUTION_TRANSPORT` 決定投影方式，預設且本版唯一支援的值為 `db`。設定為不支援的值時，系統 MUST 在任務執行業務程式前拋出設定錯誤。

#### Scenario: 未設定傳輸方式
- **WHEN** 未設定 `EXECUTION_TRANSPORT`
- **THEN** 系統以 `db` 方式直接寫入主表，行為與 0.2.0 相同

#### Scenario: 設定不支援的傳輸方式
- **WHEN** `EXECUTION_TRANSPORT` 設為 `rbmq`
- **THEN** 啟用共寫的任務在執行業務程式前失敗，錯誤訊息列出支援的值
