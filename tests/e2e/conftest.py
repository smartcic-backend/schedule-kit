import os
import time

import pytest
import requests

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
E2E_USER = ("e2e", "e2e-secret")

ALERT_RULE_BASE = {
    "name": "E2E CPU Alert",
    "execution_cycle": "*/5 * * * *",
    "cpu_threshold": 80,
    "target_host": "e2e-server",
    "notify_email": "e2e@example.com",
}


def wait_until(condition_fn, timeout=60, interval=2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition_fn():
            return True
        time.sleep(interval)
    return False


def pytest_collection_modifyitems(items):
    """服務不在線時，將所有 e2e 測試標記為 skip（不中斷整個 session）。"""
    if _ping():
        return
    skip = pytest.mark.skip(reason=f"Service at {BASE_URL} not available — start Docker first")
    for item in items:
        if item.get_closest_marker("e2e"):
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def wait_for_service():
    """服務在線時，等待完全就緒再開始跑測試。"""
    if not _ping():
        return
    ok = wait_until(
        lambda: _ping(),
        timeout=60,
        interval=2,
    )
    if not ok:
        pytest.exit(f"Service at {BASE_URL} did not become ready within 60s")


def _ping():
    try:
        r = requests.get(f"{BASE_URL}/api/alert-rules/", auth=E2E_USER, timeout=3)
        return r.status_code in (200, 401, 403)
    except requests.exceptions.ConnectionError:
        return False


@pytest.fixture
def session():
    s = requests.Session()
    s.auth = E2E_USER
    return s


@pytest.fixture
def alert_rule_payload():
    return ALERT_RULE_BASE.copy()


@pytest.fixture
def created_rule(session, alert_rule_payload):
    r = session.post(f"{BASE_URL}/api/alert-rules/", json=alert_rule_payload)
    assert r.status_code == 201, r.text
    rule = r.json()
    yield rule
    session.delete(f"{BASE_URL}/api/alert-rules/{rule['id']}/")
