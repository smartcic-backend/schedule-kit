#!/bin/bash
# 查詢執行紀錄
# 用法：
#   ./list_executions.sh              # 最新 20 筆
#   ./list_executions.sh --task-id 5  # 指定排程
#   ./list_executions.sh --status fail
#   ./list_executions.sh --limit 50

PSQL="docker exec schedule-kit-db-1 psql -U myservice -d myservice -x"

LIMIT=20
WHERE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --task-id) WHERE="$WHERE AND task_id = $2"; shift 2 ;;
        --status)  WHERE="$WHERE AND status = '$2'"; shift 2 ;;
        --limit)   LIMIT=$2; shift 2 ;;
        *) echo "未知參數：$1"; exit 1 ;;
    esac
done

SQL="
SELECT
    id,
    task_title,
    task_id,
    status,
    start_time AT TIME ZONE 'Asia/Taipei'   AS start_time,
    end_time   AT TIME ZONE 'Asia/Taipei'   AS end_time,
    EXTRACT(EPOCH FROM (end_time - start_time))::int AS duration_sec,
    LEFT(message, 80)                       AS message
FROM schedule_kit_executionrecord
WHERE 1=1 $WHERE
ORDER BY id DESC
LIMIT $LIMIT;
"

echo "=== 執行紀錄（最新 $LIMIT 筆）==="
$PSQL -c "$SQL"
