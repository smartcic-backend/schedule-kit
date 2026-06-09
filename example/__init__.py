# 讓 Django 啟動時自動載入 Celery app
# 缺少這行，Worker 啟動後找不到 tasks，Beat dispatch 出去會 NotRegistered
from .celery import app as celery_app

__all__ = ("celery_app",)
