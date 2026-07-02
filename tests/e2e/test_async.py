"""
非同步任務端對端測試。
流程：Beat 觸發 → worker dispatch 到 mock-agent → mock-agent 回調 → ExecutionRecord 狀態更新。

mock-agent 的行為由各測試先透過 /set-behavior 顯式設定（success / fail / none），
不依賴呼叫順序，測試之間互相獨立。
"""

import time

import pytest
import requests as req

from .conftest import BASE_URL, wait_until

ASYNC_TASK_BASE = {
    "execution_cycle": "@every 10s",
    "cpu_threshold": 50,
    "target_host": "e2e-async-server",
    "notify_email": "async@example.com",
}
MOCK_AGENT_URL = "http://localhost:8001"


def _set_mock_agent(mode):
    r = req.post(f"{MOCK_AGENT_URL}/set-behavior", json={"mode": mode}, timeout=5)
    assert r.status_code == 200, r.text


def _get_records(session, task_id, status=None):
    params = {"task_id": task_id}
    if status:
        params["status"] = status
    return session.get(f"{BASE_URL}/api/executions/", params=params).json()


def _create_async_rule(session, title):
    r = session.post(
        f"{BASE_URL}/api/async-alert-rules/",
        json={**ASYNC_TASK_BASE, "name": title},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _delete_rule(session, rule_id):
    session.delete(f"{BASE_URL}/api/async-alert-rules/{rule_id}/")


@pytest.mark.e2e
def test_async_pending_then_success(session):
    """mock-agent 5 秒後回調 success → pending → success。"""
    _set_mock_agent("success")
    rule = _create_async_rule(session, "E2E Async Success")
    task_id = rule["id"]

    try:
        # 先出現 pending
        def has_pending():
            return any(
                r["status"] == "pending"
                for r in _get_records(session, task_id)
            )

        assert wait_until(has_pending, timeout=60), "pending record not created within 60s"

        # mock-agent 回調後轉為 success
        def is_success():
            return len(_get_records(session, task_id, status="success")) > 0

        assert wait_until(is_success, timeout=30), "status did not reach success within 30s"

        records = _get_records(session, task_id, status="success")
        assert records[0]["end_time"] is not None
    finally:
        _delete_rule(session, rule["id"])


@pytest.mark.e2e
def test_async_pending_then_fail(session):
    """mock-agent 5 秒後回調 fail → pending → fail。"""
    _set_mock_agent("fail")
    rule = _create_async_rule(session, "E2E Async Fail")
    task_id = rule["id"]

    try:
        def has_pending():
            return any(
                r["status"] == "pending"
                for r in _get_records(session, task_id)
            )

        assert wait_until(has_pending, timeout=60), "pending record not created within 60s"

        def is_fail():
            return len(_get_records(session, task_id, status="fail")) > 0

        assert wait_until(is_fail, timeout=30), "status did not reach fail within 30s"
    finally:
        _delete_rule(session, rule["id"])


@pytest.mark.e2e
def test_async_no_callback_stays_pending(session):
    """mock-agent 完全不回調 → record 停在 pending。"""
    _set_mock_agent("none")
    rule = _create_async_rule(session, "E2E Async No Callback")
    task_id = rule["id"]

    try:
        def has_pending():
            return any(
                r["status"] == "pending"
                for r in _get_records(session, task_id)
            )

        assert wait_until(has_pending, timeout=60), "pending record not created within 60s"

        # 等 15 秒確認沒有收到回調，狀態仍是 pending
        time.sleep(15)
        records = _get_records(session, task_id, status="pending")
        assert len(records) > 0, "expected record to remain pending (no callback)"
    finally:
        _delete_rule(session, rule["id"])
        _set_mock_agent("success")
