from django.db import models
from django.utils.translation import gettext_lazy as _
from django_celery_beat.models import PeriodicTask

STATUS = [("active", _("active")), ("disabled", _("disabled"))]


class BaseSchedulerTask(models.Model):
    task_name = "base_task"

    title = models.CharField(max_length=70, unique=True)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=8, choices=STATUS, default="active")
    execution_cycle = models.CharField(max_length=128)
    timezone = models.CharField(max_length=64, default="UTC")
    task = models.OneToOneField(
        PeriodicTask,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="%(class)s",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def get_task_args(self) -> list:
        raise NotImplementedError

    def __str__(self):
        return self.title
