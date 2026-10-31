"""Run the PostgreSQL projection tests against a real server.

pytest-django creates and drops a separate test database (SK_PG_TEST_NAME), so the
configured database itself is never written. Credentials come from the environment:

    SK_PG_HOST=... SK_PG_PORT=5432 SK_PG_NAME=... SK_PG_USER=... SK_PG_PASSWORD=... \\
        pytest --ds=tests.pg_settings -m postgres
"""

import os

from tests.settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ.get("SK_PG_HOST", "localhost"),
        "PORT": os.environ.get("SK_PG_PORT", "5432"),
        "NAME": os.environ.get("SK_PG_NAME", "postgres"),
        "USER": os.environ.get("SK_PG_USER", "postgres"),
        "PASSWORD": os.environ.get("SK_PG_PASSWORD", ""),
        "TEST": {"NAME": os.environ.get("SK_PG_TEST_NAME", "test_schedule_kit_pg")},
    }
}
