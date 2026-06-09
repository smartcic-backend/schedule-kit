# execution_cycle 格式

> `execution_cycle` 是排程的單一代表欄位，存原始字串。
> 格式驗證與轉換由 `src/schedule_kit/utils/cron.py` 負責。

支援兩種格式：**crontab** 和 **@every**。

---

## crontab

5 個欄位，空白分隔：`分 時 日 月 星期`

| 欄位 | 範圍 | 說明 |
|------|------|------|
| minute | `0-59` | 分鐘 |
| hour | `0-23` | 小時 |
| day_of_month | `1-31` | 每月幾號 |
| month_of_year | `1-12` | 月份，也接受 `jan`-`dec` |
| day_of_week | `0-6`（0=週日，6=週六） | 星期，支援命名值 `mon`-`sun` 及其範圍 |

各欄位支援的語法：

| 語法 | 範例 | 說明 |
|------|------|------|
| `*` | `*` | 每個值 |
| 單一值 | `5` | 指定值 |
| 逗號清單 | `1,3,5` | 多個指定值 |
| 範圍 | `1-5` | 連續範圍 |
| 步進 | `*/15` | 每隔 15 |
| 範圍步進 | `1-5/2` | 範圍內每隔 2 |
| 命名日 | `mon` `tue` `wed` `thu` `fri` `sat` `sun` | day_of_week 可用 |
| 命名月 | `jan` `feb` `mar` `apr` `may` `jun` `jul` `aug` `sep` `oct` `nov` `dec` | month_of_year 可用 |

常用範例：

```
*/5 * * * *              每 5 分鐘
0 * * * *                每小時整點
0 8 * * *                每天 08:00
0 8 * * mon-fri          週一到週五 08:00
0 8 * * 1                每週一 08:00
0 0 1 * *                每月 1 號午夜
0 0 1 jan *              每年 1 月 1 日午夜
0 9,17 * * mon-fri       週一到週五 09:00 與 17:00
*/30 8-17 * * mon-fri    週間工作時段每 30 分鐘
```

> **不支援** `0/2` 這類從非零起始的步進語法（Vixie cron 擴充），請改用 `*/2`。
> 存檔時會自動擋下並回傳明確錯誤訊息。

---

## @every

格式：`@every <duration>`，觸發間隔相對於上次執行完成後計算。

| 單位 | 代號 | 等於秒數 |
|------|------|---------|
| 週 | `w` | 604800 |
| 天 | `d` | 86400 |
| 小時 | `h` | 3600 |
| 分鐘 | `m` | 60 |
| 秒 | `s` | 1 |

可複合使用（各段相加）：

```
@every 30s      每 30 秒
@every 5m       每 5 分鐘
@every 1h30m    每 1.5 小時（= 5400 秒）
@every 1d12h    每 36 小時
@every 2w       每 2 週
```

---

## crontab vs @every

| | crontab | @every |
|---|---|---|
| 觸發依據 | 對齊時鐘 | 距上次完成後計時 |
| 範例 | `*/5 * * * *` 在 :00、:05、:10 整分觸發 | `@every 5m` 從上次跑完後 5 分鐘觸發 |
| 長時間任務 | 不受任務執行時間影響 | 執行時間長會產生漂移 |
| 適用情境 | 需要對齊整點或特定時間 | 只需固定間隔、不在意對齊 |

---

## 相關程式位置

| 職責 | 位置 |
|------|------|
| `is_every` / `parse_every_seconds` / `validate_crontab` | `src/schedule_kit/utils/cron.py` |
| `get_or_create_schedule`（轉成 CrontabSchedule / IntervalSchedule） | `src/schedule_kit/utils/cron.py` |
| `estimate_period_seconds`（估算週期，用於 expire 計算） | `src/schedule_kit/utils/cron.py` |
| serializer 的 `validate_execution_cycle` | `src/schedule_kit/serializers/base.py` |
