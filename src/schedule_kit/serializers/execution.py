from rest_framework import serializers
from ..models.execution import ExecutionRecord


class ExecutionRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionRecord
        fields = [
            "id", "task_title", "task_function", "task_model",
            "task_id", "task_created_by_id", "celery_task_id", "status",
            "occurred_at", "end_time", "message", "periodic_task",
        ]
        read_only_fields = [
            "id", "task_title", "task_function", "task_model",
            "task_id", "task_created_by_id", "celery_task_id", "status",
            "occurred_at", "end_time", "message", "periodic_task",
        ]
