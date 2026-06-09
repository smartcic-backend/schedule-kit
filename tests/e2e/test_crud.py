"""
CRUD API 端對端測試。
驗證 AlertRuleTask 的建立、讀取、更新、刪除，以及 schedule_kit 自動同步的結果。
"""

import pytest
from .conftest import BASE_URL


@pytest.mark.e2e
def test_list_returns_200(session):
    r = session.get(f"{BASE_URL}/api/alert-rules/")
    assert r.status_code == 200


@pytest.mark.e2e
def test_create_rule(session, alert_rule_payload):
    r = session.post(f"{BASE_URL}/api/alert-rules/", json=alert_rule_payload)
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == alert_rule_payload["title"]
    assert data["status"] == "active"
    assert data["next_run_time"] is not None
    # 清理
    session.delete(f"{BASE_URL}/api/alert-rules/{data['id']}/")


@pytest.mark.e2e
def test_create_sets_next_run_in_future(session, alert_rule_payload):
    from datetime import datetime, timezone
    r = session.post(f"{BASE_URL}/api/alert-rules/", json=alert_rule_payload)
    assert r.status_code == 201
    data = r.json()
    nrt = datetime.fromisoformat(data["next_run_time"])
    assert nrt > datetime.now(tz=timezone.utc)
    session.delete(f"{BASE_URL}/api/alert-rules/{data['id']}/")


@pytest.mark.e2e
def test_retrieve_rule(session, created_rule):
    r = session.get(f"{BASE_URL}/api/alert-rules/{created_rule['id']}/")
    assert r.status_code == 200
    assert r.json()["id"] == created_rule["id"]


@pytest.mark.e2e
def test_update_threshold(session, created_rule):
    r = session.patch(
        f"{BASE_URL}/api/alert-rules/{created_rule['id']}/",
        json={"cpu_threshold": 95},
    )
    assert r.status_code == 200
    assert r.json()["cpu_threshold"] == 95


@pytest.mark.e2e
def test_disable_rule(session, created_rule):
    r = session.patch(
        f"{BASE_URL}/api/alert-rules/{created_rule['id']}/",
        json={"status": "disabled"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "disabled"
    assert data["next_run_time"] is None


@pytest.mark.e2e
def test_delete_rule(session, alert_rule_payload):
    r = session.post(f"{BASE_URL}/api/alert-rules/", json=alert_rule_payload)
    rule_id = r.json()["id"]
    r = session.delete(f"{BASE_URL}/api/alert-rules/{rule_id}/")
    assert r.status_code == 204
    r = session.get(f"{BASE_URL}/api/alert-rules/{rule_id}/")
    assert r.status_code == 404


@pytest.mark.e2e
def test_invalid_execution_cycle(session, alert_rule_payload):
    alert_rule_payload["execution_cycle"] = "0/2 * * * *"
    r = session.post(f"{BASE_URL}/api/alert-rules/", json=alert_rule_payload)
    assert r.status_code == 400
    assert "execution_cycle" in r.json()


@pytest.mark.e2e
def test_unauthenticated_returns_403(alert_rule_payload):
    import requests
    r = requests.get(f"{BASE_URL}/api/alert-rules/")
    assert r.status_code in (401, 403)
