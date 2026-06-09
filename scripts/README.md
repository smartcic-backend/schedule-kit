# scripts

對 Docker 環境進行觀測的輔助腳本，需要 `docker compose up -d` 先啟動服務。

## list_schedules.sh

列出所有排程的狀態、下次執行時間與最後執行結果。

```bash
./scripts/list_schedules.sh
```

輸出分三段：
1. 同步排程 SQL 明細（直連 DB）
2. 非同步排程 SQL 明細（直連 DB）
3. API 總覽：`next_run_time` + 最後一筆執行紀錄

可透過環境變數指定服務位址：

```bash
E2E_BASE_URL=http://staging.internal ./scripts/list_schedules.sh
```

## list_executions.sh

查詢執行紀錄，預設取最新 20 筆。

```bash
./scripts/list_executions.sh                   # 最新 20 筆
./scripts/list_executions.sh --task-id 5       # 指定排程
./scripts/list_executions.sh --status fail     # 指定狀態
./scripts/list_executions.sh --limit 50        # 調整筆數
./scripts/list_executions.sh --task-id 5 --status fail --limit 10  # 組合使用
```
