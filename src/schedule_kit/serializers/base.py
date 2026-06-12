from zoneinfo import ZoneInfo

from rest_framework import serializers
from ..utils.cron import is_every, parse_every_seconds, validate_crontab
from ..utils.schedule import get_next_run_time


class CurrentUserDefault(serializers.CurrentUserDefault):
    """同 DRF CurrentUserDefault，但沒有 request context（測試、背景程式）時回傳 None。"""

    def __call__(self, serializer_field):
        request = serializer_field.context.get("request")
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return user
        return None


class CurrentUserTimezoneDefault:
    """未指定 timezone 時，自動帶入請求使用者的時區設定（user.timezone）。

    使用者未設定時區、或沒有 request context（測試、背景程式）時，回傳 "UTC"。
    """

    requires_context = True

    def __call__(self, serializer_field):
        request = serializer_field.context.get("request")
        user = getattr(request, "user", None)
        return getattr(user, "timezone", None) or "UTC"


class BaseSchedulerSerializer(serializers.ModelSerializer):
    next_run_time = serializers.SerializerMethodField()
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    timezone = serializers.CharField(
        max_length=64,
        default=CurrentUserTimezoneDefault(),
        help_text=(
            "IANA 時區名稱（例如 Asia/Taipei、UTC）。"
            "未指定時預設帶入請求使用者的時區設定（user.timezone）；"
            "使用者未設定或無 request context 時為 UTC。"
        ),
    )
    last_run_at = serializers.DateTimeField(
        read_only=True,
        source="task.last_run_at",
        default=None,
    )
    total_run_count = serializers.IntegerField(
        read_only=True,
        source="task.total_run_count",
        default=None,
    )

    def get_next_run_time(self, obj):
        return get_next_run_time(obj.task)

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise serializers.ValidationError(f"無效的 IANA 時區名稱：{value!r}")
        return value

    def validate_execution_cycle(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("execution_cycle 不可為空")
        if is_every(value):
            try:
                parse_every_seconds(value)
            except ValueError as e:
                raise serializers.ValidationError(str(e))
        else:
            try:
                validate_crontab(value)
            except ValueError as e:
                raise serializers.ValidationError(str(e))
        return value


class EmailNotificationSerializer(serializers.ModelSerializer):
    """對應 models.EmailNotification 的 mixin，與 BaseSchedulerSerializer 組合使用。"""

    task_email_to = serializers.ListField(
        child=serializers.EmailField(),
        required=False,
    )

    def validate(self, attrs):
        enabled = attrs.get(
            "task_email_enabled",
            getattr(self.instance, "task_email_enabled", False),
        )
        recipients = attrs.get(
            "task_email_to",
            getattr(self.instance, "task_email_to", None) or [],
        )
        if enabled and not recipients:
            raise serializers.ValidationError(
                {"task_email_to": "當啟用 Email 通知功能，必須給定至少一個 Email"}
            )
        return super().validate(attrs)
