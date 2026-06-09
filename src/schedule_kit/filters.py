import django_filters
from .models.execution import ExecutionRecord


class BaseExecutionRecordFilterSet(django_filters.FilterSet):
    class Meta:
        model = ExecutionRecord
        fields = {
            "task_id": ["exact"],
            "periodic_task": ["exact"],
            "status": ["exact"],
        }
