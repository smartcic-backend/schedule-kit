# Spec Delta

## Purpose

確保多個子專案與主專案共用同一個資料庫與套件本地表時，各專案的維護作業只處理自己來源的執行紀錄，不誤判逾時、不誤刪或重送他人紀錄。

## ADDED Requirements

### Requirement: 逾時處理只針對本專案來源
啟用共寫時，maintenance 標記 pending／running 逾時，SHALL 只處理 `task_model` 以本專案 `EXECUTION_SOURCE` 加冒號開頭的本地紀錄。

#### Scenario: 其他專案的 pending 紀錄不受影響
- **WHEN** `alertv2` 的 maintenance 執行，表中有 `messagecenter:` 開頭且已逾時的 pending 紀錄
- **THEN** 該紀錄維持 pending，不被標記為失敗

### Requirement: 補送只針對本專案來源
啟用共寫時，maintenance 補送未同步終態 SHALL 只挑選本專案來源的紀錄，MUST NOT 對其他來源的紀錄嘗試投影或記錄錯誤。

#### Scenario: 其他專案的未同步紀錄
- **WHEN** maintenance 執行，表中有其他來源的未同步終態紀錄
- **THEN** 這些紀錄不被處理，也不產生「來源不符」的錯誤 log

### Requirement: 保留清理只針對本專案來源
啟用共寫時，依天數與筆數的本地保留清理 SHALL 只刪除本專案來源且已同步的紀錄。未啟用共寫時，清理範圍 MUST 限定在 `task_model` 不含來源前綴的紀錄，以及以本專案 `EXECUTION_SOURCE` 開頭的紀錄（有設定時）。

#### Scenario: 未啟用共寫的專案不刪除他人紀錄
- **WHEN** 未啟用共寫的專案執行 maintenance，表中有其他來源、已超過保留天數且尚未同步的紀錄
- **THEN** 這些紀錄不被刪除

#### Scenario: 本專案過期紀錄正常清理
- **WHEN** 啟用共寫的專案執行 maintenance，表中有本專案來源、已同步且超過保留天數的紀錄
- **THEN** 這些紀錄被刪除

### Requirement: 回呼更新不跨來源
`update_record()` 收到的紀錄若屬於其他來源，系統 SHALL 不更新該紀錄並記錄一次警告，MUST NOT 拋出例外中斷回呼流程。

#### Scenario: 回呼帶入其他專案的紀錄 ID
- **WHEN** 本專案的回呼以其他來源紀錄的 ID 呼叫 `update_record()`
- **THEN** 紀錄狀態不變，回呼正常結束，log 出現警告
