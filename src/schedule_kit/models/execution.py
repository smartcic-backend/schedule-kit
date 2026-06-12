from django.db import models
from django_celery_beat.models import PeriodicTask

EXEC_STATUS = [
    ("running", "running"),
    ("pending", "pending"),
    ("success", "success"),
    ("fail", "fail"),
]


class ExecutionRecord(models.Model):
    task_title = models.CharField(max_length=70, blank=True, default="")
    task_function = models.CharField(max_length=255)
    task_model = models.CharField(max_length=255, blank=True, default="")
    task_id = models.UUIDField(null=True, blank=True, db_index=True)
    task_created_by_id = models.IntegerField(null=True, blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    status = models.CharField(max_length=8, choices=EXEC_STATUS, default="running")
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    message = models.TextField(blank=True, default="")
    periodic_task = models.ForeignKey(
        PeriodicTask,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="execution_records",
    )

    class Meta:
        app_label = "schedule_kit"
        ordering = ["-start_time"]

    def __str__(self):
        return f"{self.task_title} [{self.status}] @ {self.start_time}"
