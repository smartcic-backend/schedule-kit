import pytest
from django.utils import timezone
from example.models import AlertRuleTask
from example.serializers import AlertRuleTaskSerializer

BASE = {
    "title": "Serializer Test Alert",
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
        task = AlertRuleTask.objects.create(**{**BASE, "title": "NextRun Crontab"})
        task.refresh_from_db()
        data = AlertRuleTaskSerializer(task).data
        assert data["next_run_time"] is not None

    @pytest.mark.django_db
    def test_next_run_time_is_future(self):
        task = AlertRuleTask.objects.create(**{**BASE, "title": "NextRun Future"})
        task.refresh_from_db()
        data = AlertRuleTaskSerializer(task).data
        assert data["next_run_time"] > timezone.now()

    @pytest.mark.django_db
    def test_next_run_time_none_when_disabled(self):
        task = AlertRuleTask.objects.create(**{**BASE, "title": "NextRun Disabled", "status": "disabled"})
        task.refresh_from_db()
        data = AlertRuleTaskSerializer(task).data
        assert data["next_run_time"] is None

    @pytest.mark.django_db
    def test_next_run_time_interval(self):
        task = AlertRuleTask.objects.create(
            **{**BASE, "title": "NextRun Interval", "execution_cycle": "@every 1h"}
        )
        task.refresh_from_db()
        data = AlertRuleTaskSerializer(task).data
        assert data["next_run_time"] is not None


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
