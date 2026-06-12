import uuid

import pytest
from django.utils import timezone
from schedule_kit.models import ExecutionRecord


def U(n: int) -> uuid.UUID:
    """測試用固定 UUID，方便以小整數區分不同排程。"""
    return uuid.UUID(int=n)

BASE = {
    "title": "View Test Alert",
    "execution_cycle": "*/5 * * * *",
    "cpu_threshold": 80,
    "target_host": "server-01",
    "notify_email": "ops@example.com",
}


@pytest.mark.django_db
def test_create_returns_201(auth_client, alert_rule_payload):
    r = auth_client.post("/api/alert-rules/", alert_rule_payload, format="json")
    assert r.status_code == 201
    assert "id" in r.data


@pytest.mark.django_db
def test_create_invalid_crontab_returns_400(auth_client, alert_rule_payload):
    alert_rule_payload["execution_cycle"] = "0/2 * * * *"
    r = auth_client.post("/api/alert-rules/", alert_rule_payload, format="json")
    assert r.status_code == 400
    assert "execution_cycle" in r.data


@pytest.mark.django_db
def test_create_invalid_threshold_returns_400(auth_client, alert_rule_payload):
    alert_rule_payload["cpu_threshold"] = 150
    r = auth_client.post("/api/alert-rules/", alert_rule_payload, format="json")
    assert r.status_code == 400
    assert "cpu_threshold" in r.data


@pytest.mark.django_db
def test_create_valid_every(auth_client, alert_rule_payload):
    alert_rule_payload["execution_cycle"] = "@every 1h30m"
    alert_rule_payload["title"] = "Every Test"
    r = auth_client.post("/api/alert-rules/", alert_rule_payload, format="json")
    assert r.status_code == 201


@pytest.mark.django_db
def test_update_execution_cycle(auth_client, alert_rule_payload):
    r = auth_client.post("/api/alert-rules/", alert_rule_payload, format="json")
    task_id = r.data["id"]
    r = auth_client.patch(
        f"/api/alert-rules/{task_id}/",
        {"execution_cycle": "0 * * * *"},
        format="json",
    )
    assert r.status_code == 200


@pytest.mark.django_db
def test_disable_schedule(auth_client, alert_rule_payload):
    r = auth_client.post("/api/alert-rules/", alert_rule_payload, format="json")
    task_id = r.data["id"]
    r = auth_client.patch(
        f"/api/alert-rules/{task_id}/", {"status": "disabled"}, format="json"
    )
    assert r.status_code == 200


@pytest.mark.django_db
def test_delete_returns_204(auth_client, alert_rule_payload):
    r = auth_client.post("/api/alert-rules/", alert_rule_payload, format="json")
    task_id = r.data["id"]
    r = auth_client.delete(f"/api/alert-rules/{task_id}/")
    assert r.status_code == 204
    r = auth_client.get(f"/api/alert-rules/{task_id}/")
    assert r.status_code == 404


@pytest.mark.django_db
def test_execution_records_list(auth_client):
    r = auth_client.get("/api/executions/")
    assert r.status_code == 200


@pytest.mark.django_db
def test_execution_records_post_not_allowed(auth_client):
    r = auth_client.post("/api/executions/", {}, format="json")
    assert r.status_code == 405


@pytest.mark.django_db
def test_execution_records_delete_not_allowed(auth_client):
    r = auth_client.delete("/api/executions/1/")
    assert r.status_code == 405


@pytest.mark.django_db
def test_execution_records_put_not_allowed(auth_client):
    r = auth_client.put("/api/executions/1/", {}, format="json")
    assert r.status_code == 405


@pytest.mark.django_db
def test_unauthenticated_returns_403(api_client):
    r = api_client.get("/api/alert-rules/")
    assert r.status_code in (401, 403)

    r = api_client.get("/api/executions/")
    assert r.status_code in (401, 403)


def _make_record(task_id, status="success", created_by_id=None):
    return ExecutionRecord.objects.create(
        task_function="test_task",
        task_id=task_id,
        task_created_by_id=created_by_id,
        status=status,
        occurred_at=timezone.now(),
    )


@pytest.mark.django_db
def test_filter_by_task_id(auth_client):
    _make_record(task_id=U(10))
    _make_record(task_id=U(20))
    r = auth_client.get(f"/api/executions/?task_id={U(10)}")
    assert r.status_code == 200
    assert all(rec["task_id"] == str(U(10)) for rec in r.json())


@pytest.mark.django_db
def test_filter_by_status(auth_client):
    _make_record(task_id=U(1), status="success")
    _make_record(task_id=U(1), status="fail")
    r = auth_client.get("/api/executions/?status=success")
    assert all(rec["status"] == "success" for rec in r.json())
    r = auth_client.get("/api/executions/?status=fail")
    assert all(rec["status"] == "fail" for rec in r.json())


@pytest.mark.django_db
def test_regular_user_sees_only_own_records(auth_client, user, other_user):
    _make_record(task_id=U(1), created_by_id=user.id)
    _make_record(task_id=U(2), created_by_id=other_user.id)
    r = auth_client.get("/api/executions/")
    assert r.status_code == 200
    assert all(rec["task_created_by_id"] == user.id for rec in r.json())


@pytest.mark.django_db
def test_staff_user_sees_all_records(staff_client, user, other_user):
    _make_record(task_id=U(1), created_by_id=user.id)
    _make_record(task_id=U(2), created_by_id=other_user.id)
    r = staff_client.get("/api/executions/")
    assert r.status_code == 200
    assert len(r.json()) == 2
