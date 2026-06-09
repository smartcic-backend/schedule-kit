# Serializer 驗證細節

> Serializer 是輸入的**驗證層**：確認 `execution_cycle` 合法後才讓 model 存檔。
> model 不解析格式（見 [base_model.md](./base_model.md)）。
>
> 使用者送進來的字串在這裡被檢查，不合法直接擋下來並回傳清楚的錯誤訊息，
> 確保存進 DB 的 `execution_cycle` 一定是 Celery 能執行的格式。

---

## 職責分工（驗證 vs 解析 vs 同步）

格式相關的工作切成三段，各自單一職責、不重複解析：

| 層 | 職責 | 不做 |
|----|------|------|
| **serializer**（本檔） | 只判定「合不合法」，不合法就 `raise ValidationError` | 不產生 Celery 物件 |
| **`utils/cron.py`** | 把 `execution_cycle` **解析成 Celery 排程物件**（`CrontabSchedule` / `IntervalSchedule`）；提供 `@every` → 秒數換算 | 不碰 DRF、不碰 PeriodicTask |
| **sync service**（[sync.md](./sync.md)） | 拿 `utils/cron.py` 的解析結果**建立 / 更新 PeriodicTask** | 不重新解析字串 |

> serializer 與 `utils/cron.py` 可共用同一份底層判讀（例如 serializer 的合法性檢查
> 直接呼叫 `utils/cron.py` 的 parse 並捕捉例外），避免兩套規則漂移。
>
> 「兩套規則漂移」的意思：如果 serializer 自己寫一套 crontab 驗證、utils 再寫一套，
> 兩套規則可能不同步，導致 serializer 放行但 utils 解析失敗，或反過來。

---

## 基本用法（各服務繼承）

```python
from schedule_kit.serializers import BaseSchedulerSerializer

class MyCronTaskSerializer(BaseSchedulerSerializer):
    class Meta:
        model = MyCronTask
        fields = "__all__"
```

> 繼承後，`execution_cycle` 的驗證自動生效，不需要額外設定。
> 各服務只需要加自己的業務欄位驗證（見下方範例）。

---

## 內建驗證：`execution_cycle`

單一欄位，依前綴判斷型別後分別驗證：

### crontab（5 欄位字串）

- **以 Celery 的 `crontab()` 為唯一準則**，不另寫平行 regex。

  > 原因：自己寫 regex 驗 crontab 很容易和 Celery 實際行為有出入。
  > 例如 Celery 的 `day_of_week` 接受 `mon`、`1`、`1-5`，但不接受 `0/2`。
  > 直接用 Celery 的 `crontab()` 嘗試解析，能解析就是合法，比維護一份 regex 可靠。

- 先檢查「剛好 5 個欄位」，再把欄位丟進 `celery.schedules.crontab()`，能解析才算合法。
- Celery 不支援 Vixie cron 的 `起始值/步進` 語法，故 `0/2`、`0/15` 一律被擋，只接受 `*/n` 或 `a-b/n`。
- 接住 Celery 例外換成清楚訊息（原始錯誤 `Invalid weekday literal` 對 minute 欄位很誤導）。

```python
from celery.schedules import crontab
from rest_framework import serializers

def validate_crontab(expr: str) -> str:
    fields = expr.split()
    if len(fields) != 5:
        raise serializers.ValidationError(
            f"crontab 必須是 5 個欄位，收到 {len(fields)} 個：{expr!r}"
        )
    minute, hour, dom, month, dow = fields
    try:
        crontab(minute=minute, hour=hour,
                day_of_month=dom, month_of_year=month, day_of_week=dow)
    except Exception:
        raise serializers.ValidationError(
            f"crontab 格式不符合 Celery 規範：{expr!r}（例如 `0/2` 不支援，請改用 `*/2`）"
        )
    return expr
```

### `@every`

- `@every <duration>` 由 `utils/cron.py` 解析成**總秒數**，建立 `IntervalSchedule(every=N, period="seconds")`。
- **支援全部單位**，可單一或複合組合（複合時各段相加）：

  | 單位 | 代號 | 秒數 |
  |------|------|------|
  | 週 | `w` | 604800 |
  | 天 | `d` | 86400 |
  | 小時 | `h` | 3600 |
  | 分 | `m` | 60 |
  | 秒 | `s` | 1 |

- 範例：

  | 輸入 | 解析 | 總秒數 |
  |------|------|--------|
  | `@every 30s` | 30 秒 | 30 |
  | `@every 5m` | 5 分 | 300 |
  | `@every 1h30m` | 1 時 + 30 分 | 5400 |
  | `@every 1d12h` | 1 天 + 12 時 | 129600 |
  | `@every 2w` | 2 週 | 1209600 |

- 規則：
  - `@every ` 後至少要有一段 `<數字><單位>`，否則 `raise ValidationError`。
  - 單位限 `w / d / h / m / s`，出現其他字元（含大寫、空格分隔的怪格式）即不合法。
  - 解析結果需 > 0 秒。

---

## 支援的排程格式

| 格式 | 範例 | 說明 |
|------|------|------|
| crontab | `*/5 * * * *` | 每 5 分鐘（對齊時鐘） |
| crontab | `0 8 * * 1` | 每週一 08:00 |
| @every | `@every 30s` | 每 30 秒（相對上次執行） |
| @every | `@every 1h30m` | 每 1.5 小時 |

> **`@every` 與 crontab 的差異**：
>
> - crontab 對齊時鐘觸發：`*/5 * * * *` 在 `:00`、`:05`、`:10` 觸發，不管上次什麼時候跑完。
> - `@every` 是相對於上次執行完成後 N 秒觸發，長時間任務會產生漂移。
>   例如 `@every 5m` 的任務跑了 2 分鐘，下次在第 7 分鐘才觸發，不是第 5 分鐘。
>
> 需要「整點、整分對齊」用 crontab；需要「每隔固定間隔」用 `@every`。

---

## 業務驗證由各服務自行加

套件只驗排程欄位，業務欄位驗證由子類補上：

```python
class AlertRuleTaskSerializer(BaseSchedulerSerializer):
    class Meta:
        model = AlertRuleTask
        fields = "__all__"

    def validate_cpu_threshold(self, value):   # 業務驗證，各服務自己加
        if not (0 < value <= 100):
            raise serializers.ValidationError("閾值必須在 1～100 之間")
        return value
```

> 套件不知道 `cpu_threshold` 是什麼，也不應該知道。
> 業務欄位的合法範圍是各服務的領域知識，由各服務自行定義。
