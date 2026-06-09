from rest_framework import serializers
from ..utils.cron import is_every, parse_every_seconds, validate_crontab
from ..utils.schedule import get_next_run_time


class BaseSchedulerSerializer(serializers.ModelSerializer):
    next_run_time = serializers.SerializerMethodField()

    def get_next_run_time(self, obj):
        return get_next_run_time(obj.task)

    def validate_execution_cycle(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("execution_cycle 不可為空")
        if is_every(value):
            try:
                parse_every_seconds(value)
            except ValueError as e:
                raise serializers.ValidationError(str(e))
        else:
            try:
                validate_crontab(value)
            except ValueError as e:
                raise serializers.ValidationError(str(e))
        return value
