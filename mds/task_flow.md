# 同步與非同步任務（0.2.0）

同步函式以 @recorded_task(name=..., scheduler_model=...) 裝飾，接受整數 task_id 與 record_id，
回傳 (instance, True/False, message)。False 會拋出 CeleryKitError，Celery 狀態為 FAILURE。
同步紀錄建檔失敗時 record_id 可為 None，業務仍繼續。

非同步 dispatcher 必須加 require_record=True，確保派送前已有可回呼的紀錄 ID。
外部工作帶回此 record_id，透過 update_record(record_id, success, message) 完成紀錄。
成功派送回傳 (instance, None, message)，本機狀態為 pending。
Celery SUCCESS 只代表 dispatcher 完成，外部工作狀態仍以 ExecutionRecord 為準。

第一次 callback 決定終態；後續重複 callback 被忽略。
若 callback 比 dispatcher 返回更快，已完成的 success/fail 不會被 pending 覆寫。
逾時 running/pending 由 maintenance 標為 fail，並同步主專案。

主專案只接收終態；流程、設定與升級限制見 [接入指引](integration.md)。

主專案補送以本機終態為準，使用 main_synced_at 與同一資料庫交易去重。重複 callback 可補送但不改變第一次終態；maintenance 亦會重試並保留待送紀錄。模型使用 EXECUTION_SOURCE 加 app_label.ModelName 隔離。
