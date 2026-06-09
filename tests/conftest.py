import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="testuser", password="testpass"
    )


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(
        username="otheruser", password="otherpass"
    )


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="staffuser", password="staffpass", is_staff=True
    )


@pytest.fixture
def auth_client(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def staff_client(staff_user):
    c = APIClient()
    c.force_authenticate(user=staff_user)
    return c


@pytest.fixture
def alert_rule_payload():
    return {
        "title": "Test CPU Alert",
        "execution_cycle": "*/5 * * * *",
        "cpu_threshold": 80,
        "target_host": "test-server",
        "notify_email": "ops@example.com",
    }
