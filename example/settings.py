"""
完整 Django settings，示範接入 schedule_kit 所需的所有設定。
"""

import os

SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")

DEBUG = True

ALLOWED_HOSTS = ["*"]

# ── Apps ──────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "rest_framework",
    "django_filters",
    "django_celery_beat",   # PeriodicTask / CrontabSchedule / IntervalSchedule 的 model
    "schedule_kit",           # AppConfig.ready() 自動掛載 signal、讀取 CELERY_SCHEDULER
    "example",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "example.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

STATIC_URL = "/static/"

# ── Database ──────────────────────────────────────────────────────────────────
# docker-compose 透過 DATABASE_URL 注入；本機開發沒設時 fallback 到 SQLite
_db_url = os.environ.get("DATABASE_URL")

if _db_url:
    import re
    _m = re.match(r"postgres://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", _db_url)
    if not _m:
        raise ValueError(f"DATABASE_URL 格式無法解析：{_db_url}")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _m.group(5),
            "USER": _m.group(1),
            "PASSWORD": _m.group(2),
            "HOST": _m.group(3),
            "PORT": _m.group(4),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TIME_ZONE = "UTC"
USE_TZ = True

# ── DRF ───────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# ── Celery 原生設定（各服務自備，套件不介入）────────────────────────────────
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672/")

# DatabaseScheduler 讓 Beat 從 DB 讀排程，套件寫進 PeriodicTask 後即時生效，不需重啟 Beat
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

CELERY_TIMEZONE = "Asia/Taipei"

# ── 套件設定 ──────────────────────────────────────────────────────────────────
CELERY_SCHEDULER = {
    # Worker 監聽的 queue 名稱，套件同步 PeriodicTask 時會帶入
    "QUEUE_NAME": "myservice",

    # 排程時區，建議與 CELERY_TIMEZONE 一致
    "TIMEZONE": "Asia/Taipei",

    # expire_seconds 動態計算參數（防止任務在 queue 裡積壓過久才跑）
    # expire = 排程週期 - SAFETY_MARGIN_SECONDS，夾在 MIN / MAX 之間
    "SAFETY_MARGIN_SECONDS": 30,
    "MIN_EXPIRE_SECONDS": 60,
    "MAX_EXPIRE_SECONDS": 86400,

    # ExecutionRecord 保留上限（兩個條件獨立運作，先到先刪）
    "TASK_RECORD_KEEP_MAX_COUNT": 1000,  # 同一 task_id 最多保留幾筆
    "TASK_RECORD_KEEP_MAX_DAYS": 30,     # 超過幾天的紀錄刪除
}
