import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def require_empty_schedulers(apps, schema_editor):
    for name in ("AlertRuleTask", "AsyncAlertRuleTask"):
        model = apps.get_model("example", name)
        count = model.objects.using(schema_editor.connection.alias).count()
        if count:
            raise RuntimeError(
                f"[SK-ID-UPGRADE-BLOCKED] {model._meta.db_table} has {count} UUID schedule(s).\n"
                "既有 UUID 排程需先建立整數 ID 對照；此 migration 不會自動轉換或清除資料。\n"
                "停止 Beat、Worker 及回呼，備份後以 python manage.py showmigrations 檢查進度。\n"
                "先前其他 migrations 可能已套用；不要直接把舊版程式接回已變更的資料庫。\n"
                "請依 mds/upgrade_integer_ids.md 在還原的測試環境驗證封存與匯回計畫。\n"
                "不要刪正式資料、改寫舊 migration 或使用 --fake 繞過檢查。"
            )


def require_empty_for_rollback(apps, schema_editor):
    for name in ("AlertRuleTask", "AsyncAlertRuleTask"):
        model = apps.get_model("example", name)
        if model.objects.using(schema_editor.connection.alias).exists():
            raise RuntimeError(
                f"[SK-ID-ROLLBACK-BLOCKED] {model._meta.db_table} has integer schedules.\n"
                "停止回滾：先備份，依整數↔UUID 對照驗證回復計畫，避免移除 id 欄位遺失資料。\n"
                "請參閱 mds/upgrade_integer_ids.md；不要使用 --fake。"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("example", "0001_initial"),
        ("schedule_kit", "0003_integer_task_id"),
    ]
    operations = [
        migrations.RunPython(require_empty_schedulers, migrations.RunPython.noop)
    ]
    for name in ("alertruletask", "asyncalertruletask"):
        operations.extend(
            [
                migrations.AlterField(
                    model_name=name,
                    name="timezone",
                    field=models.CharField(
                        max_length=64,
                        default="UTC",
                        help_text="IANA 時區名稱（例如 Asia/Taipei、UTC）。由後端自動帶入請求使用者的時區設定，前端無需填寫。",
                    ),
                ),
                migrations.RemoveField(model_name=name, name="id"),
                migrations.AddField(
                    model_name=name,
                    name="id",
                    field=models.AutoField(primary_key=True, serialize=False),
                ),
                migrations.AlterField(
                    model_name=name,
                    name="task",
                    field=models.OneToOneField(
                        to="django_celery_beat.periodictask",
                        null=True,
                        blank=True,
                        related_name="%(class)s",
                        on_delete=django.db.models.deletion.SET_NULL,
                    ),
                ),
                migrations.AlterField(
                    model_name=name,
                    name="created_by",
                    field=models.ForeignKey(
                        to=settings.AUTH_USER_MODEL,
                        null=True,
                        blank=True,
                        related_name="+",
                        db_constraint=False,
                        on_delete=django.db.models.deletion.SET_NULL,
                    ),
                ),
            ]
        )

    operations.append(
        migrations.RunPython(migrations.RunPython.noop, require_empty_for_rollback)
    )
