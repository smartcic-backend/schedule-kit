import pytest
from django.utils import timezone
from example.models import AlertRuleTask
from example.serializers import AlertRuleTaskSerializer

BASE = {
    "name": "Serializer Test Alert",
    "execution_cycle": "*/5 * * * *",
    "cpu_threshold": 80,
    "target_host": "server-01",
    "notify_email": "ops@example.com",
}


def _s(**kwargs):
    return AlertRuleTaskSerializer(data={**BASE, **kwargs})


@pytest.mark.django_db
class TestExecutionCycleValidation:
    def test_valid_crontab(self):
        assert _s().is_valid()

    def test_invalid_crontab_slash(self):
        s = _s(execution_cycle="0/2 * * * *")
        assert not s.is_valid()
        assert "execution_cycle" in s.errors

    def test_invalid_crontab_field_count(self):
        s = _s(execution_cycle="* * * *")
        assert not s.is_valid()
        assert "execution_cycle" in s.errors

    def test_valid_every_simple(self):
        assert _s(execution_cycle="@every 30s").is_valid()

    def test_valid_every_compound(self):
        assert _s(execution_cycle="@every 1h30m").is_valid()

    def test_invalid_every_unit(self):
        s = _s(execution_cycle="@every 1hour")
        assert not s.is_valid()
        assert "execution_cycle" in s.errors

    def test_invalid_every_no_duration(self):
        s = _s(execution_cycle="@every ")
        assert not s.is_valid()
        assert "execution_cycle" in s.errors


class TestNextRunTime:
    @pytest.mark.django_db
    def test_next_run_time_present_after_save(self):
        task = AlertRuleTask.objects.create(**{**BASE, "name": "NextRun Crontab"})
        task.refresh_from_db()
        data = AlertRuleTaskSerializer(task).data
        assert data["next_run_time"] is not None

    @pytest.mark.django_db
    def test_next_run_time_is_future(self):
        task = AlertRuleTask.objects.create(**{**BASE, "name": "NextRun Future"})
        task.refresh_from_db()
        data = AlertRuleTaskSerializer(task).data
        assert data["next_run_time"] > timezone.now()

    @pytest.mark.django_db
    def test_next_run_time_none_when_disabled(self):
        task = AlertRuleTask.objects.create(**{**BASE, "name": "NextRun Disabled", "enable": False})
        task.refresh_from_db()
        data = AlertRuleTaskSerializer(task).data
        assert data["next_run_time"] is None

    @pytest.mark.django_db
    def test_next_run_time_interval(self):
        task = AlertRuleTask.objects.create(
            **{**BASE, "name": "NextRun Interval", "execution_cycle": "@every 1h"}
        )
        task.refresh_from_db()
        data = AlertRuleTaskSerializer(task).data
        assert data["next_run_time"] is not None


@pytest.mark.django_db
class TestCreatedBy:
    def test_none_when_not_provided_by_system(self):
        s = _s(name="CreatedBy NoSystem")
        assert s.is_valid(), s.errors
        task = s.save()
        assert task.created_by is None

    def test_set_by_system_via_save(self, user):
        s = _s(name="CreatedBy System")
        assert s.is_valid(), s.errors
        task = s.save(created_by=user)
        assert task.created_by == user

    def test_client_input_ignored(self, user):
        s = AlertRuleTaskSerializer(
            data={**BASE, "name": "CreatedBy ClientIgnored", "created_by": user.pk},
        )
        assert s.is_valid(), s.errors
        task = s.save()
        assert task.created_by is None


@pytest.mark.django_db
class TestRunStats:
    def test_last_run_at_and_total_run_count_in_output(self):
        task = AlertRuleTask.objects.create(**{**BASE, "name": "RunStats"})
        task.refresh_from_db()
        data = AlertRuleTaskSerializer(task).data
        assert "last_run_at" in data
        assert data["total_run_count"] == 0

    def test_run_stats_none_when_no_periodic_task(self):
        task = AlertRuleTask(**{**BASE, "name": "RunStats NoTask"})
        data = AlertRuleTaskSerializer(task).data
        assert data["last_run_at"] is None
        assert data["total_run_count"] is None


@pytest.mark.django_db
class TestEmailNotificationValidation:
    def test_enabled_without_recipients_invalid(self):
        s = _s(name="Email NoRecipients", task_email_enabled=True)
        assert not s.is_valid()
        assert "task_email_to" in s.errors

    def test_enabled_with_recipients_valid(self):
        s = _s(
            name="Email WithRecipients",
            task_email_enabled=True,
            task_email_to=["a@example.com", "b@example.com"],
        )
        assert s.is_valid(), s.errors

    def test_invalid_email_format(self):
        s = _s(
            name="Email BadFormat",
            task_email_enabled=True,
            task_email_to=["not-an-email"],
        )
        assert not s.is_valid()
        assert "task_email_to" in s.errors

    def test_disabled_without_recipients_valid(self):
        assert _s(name="Email Disabled").is_valid()

    def test_partial_update_enable_without_existing_recipients_invalid(self):
        task = AlertRuleTask.objects.create(**{**BASE, "name": "Email PartialOn"})
        s = AlertRuleTaskSerializer(
            task, data={"task_email_enabled": True}, partial=True
        )
        assert not s.is_valid()
        assert "task_email_to" in s.errors

    def test_partial_update_enable_with_existing_recipients_valid(self):
        task = AlertRuleTask.objects.create(
            **{**BASE, "name": "Email PartialOk", "task_email_to": ["a@example.com"]}
        )
        s = AlertRuleTaskSerializer(
            task, data={"task_email_enabled": True}, partial=True
        )
        assert s.is_valid(), s.errors


@pytest.mark.django_db
class TestTimezoneDefault:
    class FakeRequest:
        def __init__(self, u):
            self.user = u

    def test_default_utc_without_request(self):
        s = _s(name="TZ NoRequest")
        assert s.is_valid(), s.errors
        task = s.save()
        assert task.timezone == "UTC"

    def test_auto_fill_from_user_timezone(self, user):
        user.timezone = "Asia/Taipei"  # 模擬主系統 user 的時區欄位
        s = AlertRuleTaskSerializer(
            data={**BASE, "name": "TZ FromUser"},
            context={"request": self.FakeRequest(user)},
        )
        assert s.is_valid(), s.errors
        task = s.save()
        assert task.timezone == "Asia/Taipei"

    def test_user_without_timezone_falls_back_to_utc(self, user):
        s = AlertRuleTaskSerializer(
            data={**BASE, "name": "TZ UserNoTz"},
            context={"request": self.FakeRequest(user)},
        )
        assert s.is_valid(), s.errors
        task = s.save()
        assert task.timezone == "UTC"

    def test_explicit_timezone_overrides_user(self, user):
        user.timezone = "Asia/Taipei"
        s = AlertRuleTaskSerializer(
            data={**BASE, "name": "TZ Explicit", "timezone": "Asia/Tokyo"},
            context={"request": self.FakeRequest(user)},
        )
        assert s.is_valid(), s.errors
        task = s.save()
        assert task.timezone == "Asia/Tokyo"

    def test_invalid_timezone_rejected(self):
        s = _s(name="TZ Bad", timezone="Not/AZone")
        assert not s.is_valid()
        assert "timezone" in s.errors


@pytest.mark.django_db
class TestBusinessValidation:
    def test_cpu_threshold_over_100(self):
        s = _s(cpu_threshold=150)
        assert not s.is_valid()
        assert "cpu_threshold" in s.errors

    def test_cpu_threshold_zero(self):
        s = _s(cpu_threshold=0)
        assert not s.is_valid()
        assert "cpu_threshold" in s.errors

    def test_cpu_threshold_boundary(self):
        assert _s(cpu_threshold=100).is_valid()
        assert _s(cpu_threshold=1).is_valid()
