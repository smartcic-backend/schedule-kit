from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from example.models import AlertRuleTask, AsyncAlertRuleTask

ALERT_RULES = [
    {
        "title": "每 5 分鐘 CPU 檢查 (UTC+0)",
        "execution_cycle": "*/5 * * * *",
        "timezone": "UTC",
        "cpu_threshold": 80,
        "target_host": "web-server-01",
        "notify_email": "ops@example.com",
    },
    {
        "title": "每小時整點 CPU 檢查 (Asia/Taipei)",
        "execution_cycle": "0 * * * *",
        "timezone": "Asia/Taipei",
        "cpu_threshold": 90,
        "target_host": "db-server-01",
        "notify_email": "ops@example.com",
    },
    {
        "title": "週間工作時段 CPU 檢查 (Asia/Tokyo)",
        "execution_cycle": "*/30 8-17 * * mon-fri",
        "timezone": "Asia/Tokyo",
        "cpu_threshold": 75,
        "target_host": "api-server-01",
        "notify_email": "ops@example.com",
    },
    {
        "title": "每天早上 8 點 CPU 檢查 (America/New_York)",
        "execution_cycle": "0 8 * * *",
        "timezone": "America/New_York",
        "cpu_threshold": 70,
        "target_host": "worker-server-01",
        "notify_email": "ops@example.com",
    },
    {
        "title": "每天下午 2 點 CPU 檢查 (Europe/London)",
        "execution_cycle": "0 14 * * *",
        "timezone": "Europe/London",
        "cpu_threshold": 85,
        "target_host": "eu-server-01",
        "notify_email": "ops@example.com",
    },
]

ASYNC_ALERT_RULES = [
    {
        "title": "每 30 秒 CPU 檢查（非同步 UTC+0）",
        "execution_cycle": "@every 30s",
        "timezone": "UTC",
        "cpu_threshold": 85,
        "target_host": "edge-server-01",
        "notify_email": "ops@example.com",
    },
    {
        "title": "每 10 分鐘 CPU 檢查（非同步 UTC+8 台北）",
        "execution_cycle": "@every 10m",
        "timezone": "Asia/Taipei",
        "cpu_threshold": 95,
        "target_host": "cache-server-01",
        "notify_email": "ops@example.com",
    },
    {
        "title": "每小時 CPU 檢查（非同步 UTC+8 上海）",
        "execution_cycle": "@every 1h",
        "timezone": "Asia/Shanghai",
        "cpu_threshold": 88,
        "target_host": "cn-server-01",
        "notify_email": "ops@example.com",
    },
]


class Command(BaseCommand):
    help = "建立示範用排程資料（idempotent）"

    def handle(self, *args, **options):
        User = get_user_model()
        owner = User.objects.filter(username="e2e").first()

        created = skipped = 0

        for data in ALERT_RULES:
            _, is_new = AlertRuleTask.objects.get_or_create(
                title=data["title"],
                defaults={**data, "created_by": owner},
            )
            if is_new:
                created += 1
            else:
                skipped += 1

        for data in ASYNC_ALERT_RULES:
            _, is_new = AsyncAlertRuleTask.objects.get_or_create(
                title=data["title"],
                defaults={**data, "created_by": owner},
            )
            if is_new:
                created += 1
            else:
                skipped += 1

        self.stdout.write(f"seed_data: created={created}, skipped={skipped}")
