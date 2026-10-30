# 從 UUID 升級為整數排程 ID

0.2.0 適合新子專案。既有 UUID 資料沒有通用且安全的自動轉換方式：不同子專案的排程、外鍵、外部回呼及業務資料都可能引用 UUID。
請勿把 UUID 截短、雜湊或強制轉型成整數。

## 遇到 SK-ID-UPGRADE-BLOCKED 時

此訊息表示 migration 在變更目標表之前發現既有資料而中止。訊息會列出資料表與筆數，不會列出資料內容。
Django 可能已完成前面的 migrations，所以「升級失敗」不代表整個資料庫都維持原狀。

1. 維持維護狀態，暫停 Beat、Worker、新任務派送、排程 CRUD 與外部 agent 回呼；排空或封存舊任務，避免 UUID 任務落到新版 worker。
2. 備份完整資料庫，記錄部署版本與 migration 狀態。以以下唯讀指令確認進度：

   ```bash
   python manage.py showmigrations schedule_kit
   python manage.py showmigrations
   python manage.py migrate --plan
   ```

3. 保留備份，先在還原的測試資料庫設計轉換流程。若要繼續提供舊服務，須讓舊程式連回與它相容的資料庫狀態，不能只降版程式。
4. 尚未變更 schema 的舊環境，可用舊版程式匯出，例如：

   ```bash
   python manage.py dumpdata schedule_kit.ExecutionRecord --output=execution-records-uuid.json
   python manage.py dumpdata django_celery_beat.PeriodicTask --output=periodic-tasks-uuid.json
   ```

   還須匯出各子專案的排程與引用 UUID 的業務表。請使用資料擁有者可完整讀取資料的匯出方式，並檢查筆數；上述 JSON 匯出不能取代完整資料庫備份。
   若 migration 已套用部分變更，請從備份還原的舊環境匯出，不要用新版整數 model 去讀舊 UUID 欄位。

## 需要保留既有資料：由專案設計轉換流程

以下是實作與驗收順序，不是可直接執行的通用資料 migration：

1. 為每個具體排程模型建立並保存 `(來源專案、模型、舊 UUID) → 新整數 ID` 對照。不同模型的整數可能相同，不能只按 ID 對照。
2. 在測試環境封存舊資料到受控備份表／檔案，確認可還原；本次套件 migration 僅允許目標表為空。讓目標表成為空表的操作屬正式資料變更，須由資料擁有者審核，不提供自動清空命令。
3. 為子專案具體排程模型與相關外鍵撰寫相容的 schema/data migrations；修改 abstract model 本身不會自動處理子專案資料表。
4. 若使用「升級前封存、升級後匯回」的 migrations，必須宣告與 `schedule_kit.0003_integer_task_id` 的先後依賴，避免升級前 guard 提早執行。不要改寫已發布 migration，也不要用 `--fake` 假裝已轉換。
5. 空表套用整數 schema 後，依對照匯回排程與歷史紀錄。正確處理整數序列，使下一筆新增 ID 大於已匯入 ID。
6. 更新 `PeriodicTask.args/kwargs` 中真正代表排程 ID 的欄位、業務外鍵及外部引用；不要對 JSON 內容做全域字串替換。匯出再匯回的 PeriodicTask 若 ID 改變，執行紀錄的關聯也須更新。
7. 保留歷史 `ExecutionRecord.id`（供外部 agent 的 record_id 回呼使用），或明確建立回呼對照。尚未完成的外部工作須先完成或安排相容回呼方案。Celery 的任務 UUID 不需改成整數。
8. 驗證筆數、外鍵、擁有者、ID 對照、整數序列、歷史查詢、排程觸發、成功／失敗與回呼，以及主專案共寫；完成一次回復演練後才安排正式切換。

只需要新子專案時，使用新建且無舊 UUID 資料的子專案表，可直接執行正常 migration。主專案共用表仍由主專案管理，不可清空或重建。

## 遇到 SK-ID-ROLLBACK-BLOCKED 時

整數版本已有資料，反向 migration 會在移除整數欄位之前中止。
須依已保存的對照與備份，設計並驗證資料及程式的一致回復；不能只執行反向 migrate 或改回 UUID model。

## 可交給維運的訊息

「此次升級已停止，既有資料未被本步驟轉型。請保留現場並備份，執行 showmigrations 檢查先前步驟，依本文件建立 UUID／整數對照與測試環境轉換計畫。請勿清空正式資料或使用 --fake。若不遷移舊專案，請維持與舊資料庫相容的版本。」

## 同步標記與來源識別

新增的 0004 migration 建立 main_synced_at。本機紀錄存在時，回滾會在移除此去重狀態前中止，避免回復後重送。若曾使用早期開發版共寫，升級前須核對主專案紀錄，建立來源加完整模型名稱的對照，並確認哪些本機紀錄已送達。不可未經核對就將所有 main_synced_at 留空並啟動補送，也不可只改 EXECUTION_SOURCE 來重新歸類既有紀錄。
