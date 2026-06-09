# 測試說明

## 單元 / 整合測試

使用 SQLite in-memory，不需要啟動 Docker 或外部服務。

**安裝開發依賴：**

```bash
pip install -e ".[dev]"
```

**執行：**

```bash
pytest                        # 全部
pytest tests/test_sync.py     # 單一檔案
```

| 檔案 | 涵蓋內容 |
|------|---------|
| `test_sync.py` | PeriodicTask 建立、更新、刪除、timezone、schedule 切換 |
| `test_serializer.py` | execution_cycle 格式驗證、next_run_time 計算 |
| `test_views.py` | API 列表、篩選、權限 |
| `test_cron.py` | crontab / @every 解析與驗證邏輯 |
| `test_maintenance.py` | 舊紀錄清理、pending 逾時標記 |

---

## 端對端測試（E2E）

對真實運行的服務打 HTTP 請求，驗證完整流程（排程建立 → Beat 觸發 → Worker 執行 → ExecutionRecord 寫入）。

**前置：啟動所有服務**

```bash
docker compose up -d
```

服務就緒後（通常 30 秒內），執行 e2e 測試：

```bash
pytest tests/e2e/ -m e2e -v
```

預設打 `http://localhost:8000`，可透過環境變數覆蓋：

```bash
E2E_BASE_URL=http://my-staging.internal pytest tests/e2e/ -m e2e
```

| 檔案 | 涵蓋內容 |
|------|---------|
| `e2e/test_crud.py` | AlertRuleTask CRUD、停用後 next_run_time 為 null、格式驗證 |
| `e2e/test_execution.py` | Beat 觸發後 ExecutionRecord 建立、status 收斂至 success/fail |
| `e2e/test_async.py` | 非同步任務三種 mock-agent 行為：pending→success、pending→fail、不回調留 pending |
