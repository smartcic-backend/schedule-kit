import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_celery_beat.models import PeriodicTask

STATUS = [("active", _("active")), ("disabled", _("disabled"))]


class BaseSchedulerTask(models.Model):
    task_name = "base_task"

    # 套件標準：所有排程 model 統一使用 UUID 作為主鍵
    # （識別碼不重複使用，且跨環境 export/import 不會發生 ID 衝突）
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=70, unique=True)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=8, choices=STATUS, default="active")
    execution_cycle = models.CharField(max_length=128)
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        help_text="IANA 時區名稱（例如 Asia/Taipei、UTC）。由後端自動帶入請求使用者的時區設定，前端無需填寫。",
    )
    task = models.OneToOneField(
        PeriodicTask,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def get_task_args(self) -> list:
        raise NotImplementedError

    def __str__(self):
        return self.title


class EmailNotification(models.Model):
    """Email 通知欄位 mixin，與 BaseSchedulerTask 組合使用。"""

    task_email_enabled = models.BooleanField(default=False)
    # 用 JSONField 而非 postgres ArrayField，維持資料庫無關性
    task_email_to = models.JSONField(default=list, blank=True)
    task_success_send_email = models.BooleanField(default=False)

    class Meta:
        abstract = True
