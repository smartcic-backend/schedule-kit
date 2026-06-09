from rest_framework import serializers

from schedule_kit.serializers import BaseSchedulerSerializer

from .models import AlertRuleTask, AsyncAlertRuleTask


class AlertRuleTaskSerializer(BaseSchedulerSerializer):
    class Meta:
        model = AlertRuleTask
        fields = "__all__"

    def validate_cpu_threshold(self, value):
        if not (0 < value <= 100):
            raise serializers.ValidationError("閾值必須在 1～100 之間")
        return value


class AsyncAlertRuleTaskSerializer(BaseSchedulerSerializer):
    class Meta:
        model = AsyncAlertRuleTask
        fields = "__all__"

    def validate_cpu_threshold(self, value):
        if not (0 < value <= 100):
            raise serializers.ValidationError("閾值必須在 1～100 之間")
        return value
