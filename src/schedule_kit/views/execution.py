from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, viewsets
from ..models.execution import ExecutionRecord
from ..serializers.execution import ExecutionRecordSerializer
from ..filters import BaseExecutionRecordFilterSet


class BaseExecutionRecordViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ExecutionRecordSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = BaseExecutionRecordFilterSet

    def get_queryset(self):
        return ExecutionRecord.objects.all().order_by("-start_time")
