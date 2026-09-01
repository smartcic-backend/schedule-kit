import django_filters

from schedule_kit.filters import BaseExecutionRecordFilterSet


class AlertRuleExecutionFilterSet(BaseExecutionRecordFilterSet):
    """
    在套件的三個基本 filter（task_id / periodic_task / status）基礎上，
    加入本服務需要的時間區間查詢。
    """
    # query 參數沿用 start_time_* 以維持既有前端相容，實際查的是 ExecutionRecord.occurred_at
    start_time_after  = django_filters.DateTimeFilter(field_name="occurred_at", lookup_expr="gte")
    start_time_before = django_filters.DateTimeFilter(field_name="occurred_at", lookup_expr="lte")

    class Meta(BaseExecutionRecordFilterSet.Meta):
        pass
