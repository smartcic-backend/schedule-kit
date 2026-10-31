# Spec Delta

## Purpose

讓排程執行訊息以穩定代碼加參數表達，並在寫入時產生所有支援語系的版本，使主專案與套件 API 能依查看者語系呈現，而不需收錄各子專案的翻譯檔。

## ADDED Requirements

### Requirement: 執行訊息以代碼、英文原文與參數表達
系統 SHALL 允許任務以「訊息代碼 + 英文 msgid + 參數」描述執行結果。代碼 MUST 為 1–100 字元，僅含英數字、點、底線或連字號，並以專案或套件名稱為前綴（例如 `schedule_kit.`、`messagecenter.`）。msgid MUST 為英文。

#### Scenario: 建立合法的執行訊息
- **WHEN** 任務以代碼 `messagecenter.dashboard.delivery_failed`、msgid `Dashboard report delivery failed`、參數 `{"recipient_count": 5}` 建立執行訊息
- **THEN** 系統接受該訊息，並保留代碼、msgid 與參數

#### Scenario: 代碼格式不合法
- **WHEN** 任務以含空白或超過 100 字元的代碼建立執行訊息
- **THEN** 系統拒絕建立並拋出明確的設定錯誤，不寫入任何紀錄

### Requirement: 寫入時產生所有支援語系的訊息
當執行紀錄以執行訊息完成時，系統 SHALL 對 `settings.LANGUAGES` 中的每個語系，以該語系的翻譯渲染 msgid 並代入參數，結果以語系代碼為 key 存入 `message_i18n`；英文渲染結果 MUST 同時存入 `message`。

#### Scenario: 兩種語系都有翻譯
- **WHEN** `LANGUAGES` 為 `en`、`zh-hant`，且 msgid 在 zh_Hant 翻譯檔中有譯文
- **THEN** `message_i18n` 為 `{"en": "<英文>", "zh-hant": "<中文>"}`，`message` 為英文版本

#### Scenario: 某語系沒有譯文
- **WHEN** msgid 在 zh_Hant 翻譯檔中沒有譯文
- **THEN** `message_i18n["zh-hant"]` 為英文原文，紀錄仍正常完成

#### Scenario: 渲染不受 worker 當前語系影響
- **WHEN** worker 當前啟用的語系為 `zh-hant` 時完成紀錄
- **THEN** `message` 仍為英文版本，且渲染完成後 worker 的語系恢復原狀

### Requirement: 參數必須安全且可序列化
執行訊息的參數 SHALL 為 JSON 物件，值僅限字串、數字、布林或 null。渲染失敗（缺少參數、型別錯誤）MUST NOT 讓紀錄寫入失敗或改變任務結果。

#### Scenario: 參數無法序列化
- **WHEN** 任務傳入的參數包含無法 JSON 序列化的物件
- **THEN** 系統改以內建代碼 `schedule_kit.invalid_message` 記錄，任務的成功或失敗結果不變

#### Scenario: msgid 引用了不存在的參數
- **WHEN** msgid 含 `%(count)d`，但參數中沒有 `count`
- **THEN** 該語系退回未代入參數的 msgid 原文，紀錄仍正常完成

### Requirement: 純文字訊息向下相容
任務回傳、回呼更新與完成紀錄時，系統 SHALL 繼續接受純文字訊息。純文字訊息 MUST 只寫入 `message`，`message_code`、`message_params`、`message_i18n` 保持 null，行為與 0.2.0 相同。

#### Scenario: 舊任務回傳純文字
- **WHEN** 任務回傳 `(instance, True, "ok")`
- **THEN** 紀錄為 success，`message` 為 `ok`，三個多語系欄位為 null

### Requirement: 套件內建訊息使用代碼
套件自身產生的訊息（任務拋出未捕捉例外、回傳格式錯誤、success 型別錯誤、pending／running 逾時、參數不合法）SHALL 使用 `schedule_kit.` 前綴的內建代碼，並提供 en 與 zh_Hant 翻譯。例外訊息 MUST 只包含例外類別名稱，不得包含例外內容。

#### Scenario: 任務拋出例外
- **WHEN** 任務拋出 `ValueError("password=secret")`
- **THEN** 紀錄為 fail，`message_code` 為 `schedule_kit.task_raised`，`message_params` 為 `{"exception": "ValueError"}`，任何欄位都不含 `password=secret`

#### Scenario: pending 逾時
- **WHEN** maintenance 將超過 `PENDING_TIMEOUT_HOURS` 的 pending 紀錄標為失敗
- **THEN** `message_code` 為 `schedule_kit.pending_timeout`，`message_i18n` 含 en 與 zh-hant 版本

### Requirement: 套件執行紀錄 API 依請求語系呈現訊息
套件提供的執行紀錄 API SHALL 依當前請求語系從 `message_i18n` 挑選 `message`，依序回退到主語系、`en`，最後回退到原 `message`。API MUST 輸出 `message_code`、`message_params`，MUST NOT 輸出 `message_i18n` 原始內容。

#### Scenario: 繁體中文請求
- **WHEN** 請求語系為 `zh-hant`，紀錄的 `message_i18n` 含 `zh-hant`
- **THEN** 回應的 `message` 為中文版本，且回應中沒有 `message_i18n`

#### Scenario: 舊紀錄沒有多語系內容
- **WHEN** 紀錄的 `message_i18n` 為 null
- **THEN** 回應的 `message` 為原始 `message`
