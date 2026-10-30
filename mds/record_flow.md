# ExecutionRecord 生命週期（0.2.0）

1. 依明確的 scheduler_model 或唯一 task_name 找到排程模型，再由整數 id 讀取排程。
2. 執行前建立 running 紀錄，填入模型、名稱、建立者及排程 task FK。
3. 執行業務函式並注入 record_id。同步允許本機建檔失敗時傳入 None；非同步需 require_record=True。
4. 回傳 (instance, True, message) 將紀錄設為 success，維持回傳紀錄 ID。
5. 回傳 False 記錄 fail 並拋出 CeleryKitError；格式錯誤同樣視為失敗。
6. 未捕捉例外記錄 fail，僅保存例外類別；紀錄寫入失敗不取代原例外。
7. 回傳 None 表示 pending；update_record() 或逾時清理決定終態。
8. 本機終態成功落地後才共寫。共用表 INSERT 與 main_synced_at 同交易，失敗可重試且不重複寫入；快速 callback 不被 pending 覆寫。

主專案共寫需 WRITE_MAIN_EXECUTION_RECORDS=True 與唯一 EXECUTION_SOURCE，並與主專案共用 DB、PeriodicTask 及使用者。
套件不管理主專案的 migration。詳見 [接入指引](integration.md)。

本機欄位 task_id 為整數排程 ID，celery_task_id 為 Celery UUID。
occurred_at 為開始時間；主專案對應欄位為 start_time。
本機保留 running/pending/success/fail，主專案只寫 success/fail 終態。

模型識別為來源加模型完整名稱；未同步終態不會被本機清理刪除。重複 callback 及 maintenance 可補送，須依接入指引設定 maintenance 排程。
