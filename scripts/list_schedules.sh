#!/bin/bash
# 列出所有排程及其狀態、下次執行時間、上次執行結果
# next_run_time 從 API 取得（Beat 動態計算，不存在 DB）

BASE_URL="${E2E_BASE_URL:-http://localhost:8000}"
AUTH="e2e:e2e-secret"

PSQL="docker exec celery_kit-db-1 psql -U myservice -d myservice -x"

SQL_SYNC="
SELECT
    t.id,
    t.title,
    t.execution_cycle,
    t.timezone,
    t.status                                        AS task_status,
    pt.enabled                                      AS beat_enabled,
    pt.last_run_at AT TIME ZONE 'Asia/Taipei'       AS last_run_at,
    pt.queue
FROM example_alertruletask t
LEFT JOIN django_celery_beat_periodictask pt ON pt.id = t.task_id
ORDER BY t.id;
"

SQL_ASYNC="
SELECT
    t.id,
    t.title,
    t.execution_cycle,
    t.timezone,
    t.status                                        AS task_status,
    pt.enabled                                      AS beat_enabled,
    pt.last_run_at AT TIME ZONE 'Asia/Taipei'       AS last_run_at,
    pt.queue
FROM example_asyncalertruletask t
LEFT JOIN django_celery_beat_periodictask pt ON pt.id = t.task_id
ORDER BY t.id;
"

echo "=== 同步排程 (AlertRuleTask) ==="
$PSQL -c "$SQL_SYNC"

echo ""
echo "=== 非同步排程 (AsyncAlertRuleTask) ==="
$PSQL -c "$SQL_ASYNC"

echo ""
echo "=== 排程總覽：下次執行 + 上次執行結果 ==="

_print_schedules() {
    local endpoint=$1
    local label=$2

    echo "[$label]"
    curl -s -u "$AUTH" "$BASE_URL/api/$endpoint/" | python3 -c "
import sys, json
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import base64

base_url = '${BASE_URL}'
auth = base64.b64encode(b'${AUTH}').decode()

schedules = json.load(sys.stdin)
for r in schedules:
    tid  = r['id']
    nrt  = r['next_run_time'] or '(disabled)'

    # 取最後一筆執行紀錄
    req = Request(
        f\"{base_url}/api/executions/?task_id={tid}\",
        headers={'Authorization': f'Basic {auth}'}
    )
    records = json.loads(urlopen(req).read())
    last = records[0] if records else None

    if last:
        last_status = last['status']
        last_time   = last['start_time']
        last_msg    = (last['message'] or '')[:60]
    else:
        last_status = '(no records)'
        last_time   = '-'
        last_msg    = ''

    print(f\"  [{tid}] {r['title']}\")
    print(f\"       execution_cycle  : {r['execution_cycle']}\")
    print(f\"       next_run_time    : {nrt}\")
    print(f\"       last_exec_time   : {last_time}\")
    print(f\"       last_exec_status : {last_status}\")
    if last_msg:
        print(f\"       last_exec_msg    : {last_msg}\")
    print()
"
}

_print_schedules "alert-rules"       "AlertRuleTask"
_print_schedules "async-alert-rules" "AsyncAlertRuleTask"
