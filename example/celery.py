"""
Celery app 設定，各服務自建。
通常放在 config/celery.py 或 <project>/celery.py。
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example.settings")

app = Celery("myservice")

# 從 Django settings 讀取 Celery 設定（CELERY_ 前綴的 key）
app.config_from_object("django.conf:settings", namespace="CELERY")

# 自動掃描所有 INSTALLED_APPS 裡的 tasks.py
app.autodiscover_tasks()
