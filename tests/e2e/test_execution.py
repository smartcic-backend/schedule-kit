"""
執行紀錄端對端測試。
建立 @every 10s 排程，等待 Beat 觸發後確認 ExecutionRecord 被寫入。
"""

import pytest
from .conftest import BASE_URL, wait_until

FAST_TASK = {
    "title": "E2E Fast Task",
    "execution_cycle": "@every 10s",
    "cpu_threshold": 50,
    "target_host": "e2e-exec-server",
    "notify_email": "exec@example.com",
}


def _get_records(session, task_id, status=None):
    params = {"task_id": task_id}
    if status:
        params["status"] = status
    return session.get(f"{BASE_URL}/api/executions/", params=params).json()


@pytest.fixture
def fast_rule(session):
    r = session.post(f"{BASE_URL}/api/alert-rules/", json=FAST_TASK)
    assert r.status_code == 201, r.text
    rule = r.json()
    yield rule
    session.delete(f"{BASE_URL}/api/alert-rules/{rule['id']}/")


@pytest.mark.e2e
def test_execution_record_created(session, fast_rule):
    task_id = fast_rule["id"]

    def has_record():
        return len(_get_records(session, task_id)) > 0

    assert wait_until(has_record, timeout=60), (
        "ExecutionRecord was not created within 60s"
    )


@pytest.mark.e2e
def test_execution_record_status(session, fast_rule):
    task_id = fast_rule["id"]

    def has_terminal_record():
        records = _get_records(session, task_id)
        return any(rec["status"] in ("success", "fail") for rec in records)

    assert wait_until(has_terminal_record, timeout=90), (
        "No execution record reached success/fail within 90s"
    )

    records = _get_records(session, task_id)
    terminal = [rec for rec in records if rec["status"] in ("success", "fail")]
    assert terminal[0]["start_time"] is not None
    assert terminal[0]["end_time"] is not None


