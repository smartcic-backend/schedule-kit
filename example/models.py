from django.db import models

from schedule_kit.models import BaseSchedulerTask


class AsyncAlertRuleTask(BaseSchedulerTask):
    """CPU 超閾值告警排程（非同步：把工作交給外部 agent，等回調）。"""

    task_name = "alert_rule_async_task"

    cpu_threshold = models.FloatField()
    target_host = models.CharField(max_length=255)
    notify_email = models.EmailField()
    created_by = models.ForeignKey(
        "auth.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "CPU 告警排程（非同步）"

    def get_task_args(self) -> list:
        return [self.id]


class AlertRuleTask(BaseSchedulerTask):
    """CPU 超閾值告警排程。"""

    task_name = "alert_rule_task"

    cpu_threshold = models.FloatField()
    target_host = models.CharField(max_length=255)
    notify_email = models.EmailField()
    created_by = models.ForeignKey(
        "auth.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = "CPU 告警排程"

    def get_task_args(self) -> list:
        return [self.id]
