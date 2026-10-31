from django.db import migrations, models


def require_empty_records(apps, schema_editor):
    model = apps.get_model("schedule_kit", "ExecutionRecord")
    count = model.objects.using(schema_editor.connection.alias).count()
    if count:
        raise RuntimeError(
            f"UUID execution records exist: {model._meta.db_table} has {count} record(s).\n"
            "[SK-ID-UPGRADE-BLOCKED] 停止升級：既有 UUID 不能直接轉為整數。\n"
            "本 migration 尚未變更此表；先前其他 migrations 可能已套用。\n"
            "1. 暫停 Beat、Worker、回呼及排程寫入，先備份資料庫。\n"
            "2. 執行 python manage.py showmigrations schedule_kit 檢查實際進度。\n"
            "3. 匯出必須使用相容的舊版程式／備份資料庫，不要用新版整數 model 讀取 UUID。\n"
            "4. 保留既有環境，先在備份還原的測試環境建立各排程模型 UUID→整數對照，\n"
            "   遷移排程、外鍵、PeriodicTask args/kwargs 與歷史紀錄，再驗證回呼及查詢。\n"
            "5. 本 migration 僅支援空表；有資料須依升級指引設計封存、空表升級及對照匯回流程。\n"
            "不要刪除正式資料、改寫舊 migration 或使用 --fake 繞過檢查。\n"
            "完整操作：套件原始碼 mds/upgrade_integer_ids.md（README 的整數 ID 升級指引）。"
        )


def require_empty_for_rollback(apps, schema_editor):
    model = apps.get_model("schedule_kit", "ExecutionRecord")
    if model.objects.using(schema_editor.connection.alias).exists():
        raise RuntimeError(
            "[SK-ID-ROLLBACK-BLOCKED] 已有整數執行紀錄，停止回滾以免移除 task_id 欄位造成資料遺失。\n"
            "先備份，依 UUID↔整數對照完成專案資料回復計畫；請參閱 mds/upgrade_integer_ids.md。\n"
            "不要使用 --fake；程式與資料庫須一併回復至同一版本。"
        )


class Migration(migrations.Migration):
    dependencies = [("schedule_kit", "0002_executionrecord_occurred_at")]
    operations = [
        migrations.RunPython(require_empty_records, migrations.RunPython.noop),
        migrations.RemoveField(model_name="executionrecord", name="task_id"),
        migrations.AddField(
            model_name="executionrecord",
            name="task_id",
            field=models.IntegerField(null=True, blank=True, db_index=True),
        ),
        migrations.RunPython(migrations.RunPython.noop, require_empty_for_rollback),
    ]
