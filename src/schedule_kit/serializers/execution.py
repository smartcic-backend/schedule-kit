from rest_framework import serializers
from ..messages import resolve_message
from ..models.execution import ExecutionRecord


class ExecutionRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionRecord
        # message_i18n is not exposed: `message` is resolved to the request language.
        fields = [
            "id", "task_title", "task_function", "task_model",
            "task_id", "task_created_by_id", "celery_task_id", "status",
            "occurred_at", "end_time", "message", "message_code", "message_params",
            "periodic_task",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["message"] = resolve_message(instance)
        return data
