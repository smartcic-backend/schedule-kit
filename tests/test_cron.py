import pytest
from schedule_kit.utils.cron import (
    estimate_period_seconds,
    is_every,
    parse_every_seconds,
    validate_crontab,
)


def test_is_every():
    assert is_every("@every 30s") is True
    assert is_every("*/5 * * * *") is False


class TestParseEverySeconds:
    def test_single_units(self):
        assert parse_every_seconds("@every 30s") == 30
        assert parse_every_seconds("@every 5m") == 300
        assert parse_every_seconds("@every 1h") == 3600
        assert parse_every_seconds("@every 1d") == 86400
        assert parse_every_seconds("@every 1w") == 604800

    def test_compound_units(self):
        assert parse_every_seconds("@every 1h30m") == 5400
        assert parse_every_seconds("@every 1d12h") == 129600
        assert parse_every_seconds("@every 2w") == 1209600

    def test_invalid_unit(self):
        with pytest.raises(ValueError):
            parse_every_seconds("@every 1hour")

    def test_empty_duration(self):
        with pytest.raises(ValueError):
            parse_every_seconds("@every ")

    def test_zero_duration(self):
        with pytest.raises(ValueError):
            parse_every_seconds("@every 0s")


class TestValidateCrontab:
    def test_valid_formats(self):
        validate_crontab("*/5 * * * *")
        validate_crontab("0 8 * * 1")
        validate_crontab("0 0 1 1 *")
        validate_crontab("* * * * *")

    def test_invalid_slash_syntax(self):
        with pytest.raises(ValueError, match="0/2"):
            validate_crontab("0/2 * * * *")

    def test_wrong_field_count_too_few(self):
        with pytest.raises(ValueError, match="5 個欄位"):
            validate_crontab("* * * *")

    def test_wrong_field_count_too_many(self):
        with pytest.raises(ValueError, match="5 個欄位"):
            validate_crontab("* * * * * *")


class TestEstimatePeriodSeconds:
    def test_every_minute(self):
        assert estimate_period_seconds("* * * * *") == 60

    def test_every_n_minutes(self):
        assert estimate_period_seconds("*/5 * * * *") == 300
        assert estimate_period_seconds("*/2 * * * *") == 120

    def test_hourly(self):
        assert estimate_period_seconds("0 * * * *") == 3600

    def test_every_n_hours(self):
        assert estimate_period_seconds("0 */6 * * *") == 21600

    def test_daily(self):
        assert estimate_period_seconds("0 8 * * *") == 86400

    def test_every_interval(self):
        assert estimate_period_seconds("@every 30s") == 30
        assert estimate_period_seconds("@every 1h30m") == 5400
