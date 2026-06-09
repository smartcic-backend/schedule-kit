import django_filters

from schedule_kit.filters import BaseExecutionRecordFilterSet


class AlertRuleExecutionFilterSet(BaseExecutionRecordFilterSet):
    """
    在套件的三個基本 filter（task_id / periodic_task / status）基礎上，
    加入本服務需要的時間區間查詢。
    """
    start_time_after  = django_filters.DateTimeFilter(field_name="start_time", lookup_expr="gte")
    start_time_before = django_filters.DateTimeFilter(field_name="start_time", lookup_expr="lte")

    class Meta(BaseExecutionRecordFilterSet.Meta):
        pass
