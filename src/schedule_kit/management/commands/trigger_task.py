"""
手動觸發 Celery 排程任務，無需等待排程時間。

任務與排程 model 的對應關係由 BaseSchedulerTask 子類的 task_name 自動推導，
不需要任何專案端設定。
"""

import inspect
import json

from celery import current_app
from django.core.management.base import BaseCommand, CommandError

from ...conf import get_queue_name


def _get_app():
    app = current_app._get_current_object()
    # management command 行程裡 autodiscover_tasks() 是 lazy 的，
    # 不主動觸發的話 app.tasks 看不到專案任務
    app.loader.import_default_modules()
    return app


def _task_model_mapping() -> dict:
    """task_name -> 排程 model 類別，從已註冊的 BaseSchedulerTask 子類推導"""
    from ...models.base import BaseSchedulerTask
    from ...signals import _get_all_subclasses

    return {
        cls.task_name: cls
        for cls in _get_all_subclasses(BaseSchedulerTask)
        if cls.task_name != BaseSchedulerTask.task_name
    }


class Command(BaseCommand):
    help = "手動觸發 Celery 排程任務，無需等待排程時間"

    def add_arguments(self, parser):
        parser.add_argument(
            "--list",
            action="store_true",
            help="列出 Celery app beat_schedule 中的排程任務",
        )
        parser.add_argument(
            "--list-all",
            action="store_true",
            help="列出所有註冊在 Beat 資料庫中的排程任務（包含動態建立的）",
        )
        parser.add_argument(
            "--args",
            type=str,
            default="[]",
            help="傳遞給任務的參數，JSON 格式 (例如: '[1]')",
        )
        parser.add_argument(
            "--queue",
            type=str,
            default=None,
            help="指定任務發送到哪個 queue（預設依排程設定或 CELERY_SCHEDULER.QUEUE_NAME）",
        )
        parser.add_argument(
            "--use-default",
            action="store_true",
            help="使用排程配置的預設參數（從 beat_schedule 或資料庫讀取）",
        )
        parser.add_argument(
            "--schedule-name",
            type=str,
            default=None,
            help="指定排程名稱（PeriodicTask.name），用於區分相同任務的不同排程",
        )
        parser.add_argument(
            "task_name",
            nargs="?",
            type=str,
            help="要觸發的任務名稱，或留空改用 --schedule-name",
        )

    def handle(self, *args, **options):
        if options["list_all"]:
            self._list_all_beat_tasks()
            return

        app = _get_app()
        beat_schedule = app.conf.beat_schedule

        if options["list"]:
            self._list_beat_schedule(beat_schedule)
            return

        schedule_name = options.get("schedule_name")
        task_name = options.get("task_name")
        task_args_from_schedule = ()
        task_queue_from_schedule = None

        if schedule_name:
            schedule_info = self._get_schedule_by_name(schedule_name)
            if not schedule_info:
                raise CommandError(
                    f"找不到排程名稱: {schedule_name}\n請使用 --list-all 查看所有可用的排程"
                )
            task_name = schedule_info["task_name"]
            task_args_from_schedule = schedule_info["args"]
            task_queue_from_schedule = schedule_info["queue"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"從排程 '{schedule_name}' 讀取資訊:\n"
                    f"  任務: {task_name}\n"
                    f"  參數: {list(task_args_from_schedule)}\n"
                    f'  Queue: {task_queue_from_schedule or "(未設定)"}'
                )
            )
        elif not task_name:
            raise CommandError(
                "請提供任務名稱或排程名稱，或使用 --list / --list-all 查看所有可用任務\n\n"
                "範例:\n"
                "  python manage.py trigger_task --list-all\n"
                "  python manage.py trigger_task --args '[1]' my_task\n"
                "  python manage.py trigger_task --schedule-name '每日報表'\n"
                "  python manage.py trigger_task --schedule-name '每日報表' --args '[5]'\n"
                "  python manage.py trigger_task --args '[1]' --queue other_queue my_task"
            )
        else:
            # 先從 beat_schedule 查找，再回退到資料庫
            for schedule_config in beat_schedule.values():
                if schedule_config["task"] == task_name:
                    task_args_from_schedule = schedule_config.get("args", ())
                    task_queue_from_schedule = schedule_config.get("options", {}).get(
                        "queue"
                    )
                    break
            else:
                db_task_info = self._get_task_info_from_db(task_name)
                if db_task_info:
                    task_queue_from_schedule = db_task_info.get("queue")
                    task_args_from_schedule = db_task_info.get("args", ())
                    self.stdout.write(
                        self.style.NOTICE(f"從資料庫讀取任務資訊: {task_name}")
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"警告: 任務 '{task_name}' 不在 beat_schedule 和資料庫中，"
                            f"但仍會嘗試執行..."
                        )
                    )

        final_args = self._resolve_args(options, task_args_from_schedule)
        final_queue = (
            options.get("queue") or task_queue_from_schedule or get_queue_name()
        )

        self._send_task(task_name, final_args, final_queue)

    # ── 參數解析 ──────────────────────────────────────────────────────────

    def _resolve_args(self, options, task_args_from_schedule):
        if options.get("use_default"):
            if task_args_from_schedule:
                self.stdout.write(
                    self.style.NOTICE(f"使用預設參數: {list(task_args_from_schedule)}")
                )
                return list(task_args_from_schedule)
            self.stdout.write(self.style.WARNING("找不到預設參數，將不傳遞任何參數"))
            return []

        try:
            custom_args = json.loads(options.get("args", "[]"))
            if not isinstance(custom_args, list):
                raise ValueError("參數必須是陣列格式")
        except (json.JSONDecodeError, ValueError) as e:
            raise CommandError(f"參數格式錯誤: {e}\n範例: --args '[1]'")

        if custom_args:
            return custom_args
        if task_args_from_schedule:
            self.stdout.write(
                self.style.NOTICE(
                    f"未指定參數，使用預設參數: {list(task_args_from_schedule)}"
                )
            )
            return list(task_args_from_schedule)
        return []

    # ── 觸發 ──────────────────────────────────────────────────────────────

    def _send_task(self, task_name, final_args, final_queue):
        app = _get_app()
        try:
            self.stdout.write(f"\n正在觸發任務: {self.style.SUCCESS(task_name)}")
            if final_args:
                self.stdout.write(f"參數: {list(final_args)}")
            self.stdout.write(f"Queue: {final_queue}")

            result = app.send_task(task_name, args=list(final_args), queue=final_queue)

            self.stdout.write(
                self.style.SUCCESS(f"\n✓ 任務已成功觸發！\n任務 ID: {result.id}\n")
            )
            self.stdout.write(
                self.style.WARNING(
                    "提示: 可以透過以下方式查看任務執行狀態：\n"
                    "  - 查看 Celery worker 日誌\n"
                    "  - 查看資料庫中的 ExecutionRecord 記錄\n"
                    f"  - 確認 Worker 有訂閱 queue: {final_queue}\n"
                )
            )
        except Exception as e:
            raise CommandError(f"觸發任務失敗: {e}")

    # ── 查詢 ──────────────────────────────────────────────────────────────

    def _get_schedule_by_name(self, schedule_name):
        from django_celery_beat.models import PeriodicTask

        periodic_task = PeriodicTask.objects.filter(name=schedule_name).first()
        if not periodic_task:
            return None
        return {
            "task_name": periodic_task.task,
            "queue": periodic_task.queue or None,
            "args": tuple(self._parse_json(periodic_task.args, [])),
        }

    def _get_task_info_from_db(self, task_name):
        from django_celery_beat.models import PeriodicTask

        periodic_task = PeriodicTask.objects.filter(task=task_name).first()
        if not periodic_task:
            return None
        return {
            "queue": periodic_task.queue or None,
            "args": tuple(self._parse_json(periodic_task.args, [])),
        }

    @staticmethod
    def _parse_json(raw, default):
        if not raw:
            return default
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return default

    # ── 列表 ──────────────────────────────────────────────────────────────

    def _list_beat_schedule(self, beat_schedule):
        self.stdout.write(self.style.SUCCESS("\n=== beat_schedule 中的排程任務 ===\n"))
        if not beat_schedule:
            self.stdout.write(self.style.WARNING("beat_schedule 是空的\n"))
        for schedule_name, schedule_config in beat_schedule.items():
            task_name = schedule_config["task"]
            self.stdout.write(f"排程名稱: {self.style.WARNING(schedule_name)}")
            self.stdout.write(f"  任務名稱: {task_name}")
            self.stdout.write(f'  排程時間: {schedule_config["schedule"]}')

            task_queue = schedule_config.get("options", {}).get(
                "queue"
            ) or self._get_task_queue(task_name)
            if task_queue:
                self.stdout.write(f"  Queue: {task_queue}")

            task_args = schedule_config.get("args", ())
            if task_args:
                self.stdout.write(f"  預設參數: {task_args}")
                args_detail = self._get_args_detail(task_name, list(task_args))
                if args_detail:
                    self.stdout.write(f"  參數詳情: {args_detail}")

            task_signature = self._get_task_signature(task_name)
            if task_signature:
                self.stdout.write(f"  函數簽名: {task_signature}")
            self.stdout.write("")

        self.stdout.write(
            self.style.NOTICE(
                "\n提示: 使用 --list-all 可以查看所有註冊在 Beat 資料庫中的任務\n"
            )
        )

    def _list_all_beat_tasks(self):
        from django_celery_beat.models import PeriodicTask

        app = _get_app()
        periodic_tasks = PeriodicTask.objects.all().select_related(
            "crontab", "interval", "solar", "clocked"
        )
        if not periodic_tasks.exists():
            self.stdout.write(
                self.style.WARNING("\n目前沒有任何註冊在 Beat 資料庫中的排程任務\n")
            )
            return

        self.stdout.write(
            self.style.SUCCESS("\n=== 所有註冊在 Beat 資料庫中的排程任務 ===\n")
        )

        local_tasks = {t for t in app.tasks.keys() if not t.startswith("celery.")}
        enabled_tasks, disabled_tasks = [], []
        for task in periodic_tasks:
            task_queue = (task.queue or "").strip() or self._get_task_queue(task.task)
            info = {
                "task": task,
                "name": task.name,
                "task_name": task.task,
                "enabled": task.enabled,
                "schedule": self._format_schedule(task),
                "args": task.args or "[]",
                "kwargs": task.kwargs or "{}",
                "queue": task_queue,
                "is_external": task.task not in local_tasks,
            }
            (enabled_tasks if task.enabled else disabled_tasks).append(info)

        if enabled_tasks:
            self.stdout.write(self.style.SUCCESS("【啟用中的任務】\n"))
            for info in enabled_tasks:
                self._print_task_info(info)
        if disabled_tasks:
            self.stdout.write(self.style.WARNING("\n【已停用的任務】\n"))
            for info in disabled_tasks:
                self._print_task_info(info)

        self.stdout.write(
            self.style.NOTICE(
                f"\n總計: {len(periodic_tasks)} 個任務 "
                f"(啟用: {len(enabled_tasks)}, 停用: {len(disabled_tasks)})"
            )
        )
        external_count = sum(
            1 for t in enabled_tasks + disabled_tasks if t["is_external"]
        )
        if external_count > 0:
            self.stdout.write(
                self.style.NOTICE(f"未註冊在本專案 Celery app 的任務: {external_count} 個\n")
            )

    def _print_task_info(self, info):
        status_icon = "✓" if info["enabled"] else "✗"
        name_display = info["name"]
        if info["is_external"]:
            name_display = f'{info["name"]} (外部專案)'

        self.stdout.write(f"{status_icon} 排程名稱: {self.style.WARNING(name_display)}")
        self.stdout.write(f'  任務名稱: {info["task_name"]}')
        self.stdout.write(f'  排程時間: {info["schedule"]}')
        if info["queue"]:
            self.stdout.write(f'  Queue: {info["queue"]}')
        elif info["is_external"]:
            self.stdout.write("  Queue: (未設定，可能需要在資料庫中設定)")

        if info["args"] != "[]":
            args_display = self._parse_json(info["args"], info["args"])
            self.stdout.write(f"  預設參數 (args): {args_display}")
            if isinstance(args_display, list):
                args_detail = self._get_args_detail(info["task_name"], args_display)
                if args_detail:
                    self.stdout.write(f"  參數詳情: {args_detail}")
        if info["kwargs"] != "{}":
            kwargs_display = self._parse_json(info["kwargs"], info["kwargs"])
            self.stdout.write(f"  預設參數 (kwargs): {kwargs_display}")

        task_signature = self._get_task_signature(info["task_name"])
        if task_signature:
            self.stdout.write(f"  函數簽名: {task_signature}")
        if info["task"].last_run_at:
            self.stdout.write(f'  最後執行: {info["task"].last_run_at}')
        self.stdout.write("")

    @staticmethod
    def _format_schedule(task):
        if task.crontab:
            cron = task.crontab
            return (
                f"crontab({cron.minute} {cron.hour} {cron.day_of_week} "
                f"{cron.day_of_month} {cron.month_of_year})"
            )
        if task.interval:
            return f"每 {task.interval.every} {task.interval.period}"
        if task.solar:
            return f"solar({task.solar.event} {task.solar.latitude} {task.solar.longitude})"
        if task.clocked:
            return f"clocked({task.clocked.clocked_time})"
        return "未設定排程"

    def _get_task_queue(self, task_name):
        """從任務註冊或資料庫獲取 queue 資訊"""
        app = _get_app()
        task = app.tasks.get(task_name)
        if task is not None:
            queue = getattr(task, "queue", None)
            if queue:
                return queue

        from django_celery_beat.models import PeriodicTask

        periodic_task = PeriodicTask.objects.filter(task=task_name).first()
        if periodic_task and periodic_task.queue:
            return periodic_task.queue
        return None

    def _get_args_detail(self, task_name, args_list):
        """第一個參數視為排程 model 的 PK，顯示該筆排程的摘要"""
        model_class = _task_model_mapping().get(task_name)
        if model_class is None or not args_list:
            return None

        task_id = args_list[0]
        try:
            instance = model_class.objects.get(pk=task_id)
        except model_class.DoesNotExist:
            return f"ID={task_id} (記錄不存在)"
        except Exception as e:
            return f"ID={task_id} (查詢失敗: {e})"

        details = [f"標題='{instance.name}'"]
        if instance.description:
            desc = (
                instance.description[:50] + "..."
                if len(instance.description) > 50
                else instance.description
            )
            details.append(f"描述='{desc}'")
        details.append(f"狀態={instance.enable}")
        return ", ".join(details)

    def _get_task_signature(self, task_name):
        app = _get_app()
        task = app.tasks.get(task_name)
        if task is None:
            return None
        try:
            task_func = task.run if hasattr(task, "run") else task
            sig = inspect.signature(task_func)
        except (ValueError, TypeError):
            return None

        params = []
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "args", "kwargs"):
                continue
            annotation = (
                f": {param.annotation.__name__}"
                if param.annotation != inspect.Parameter.empty
                and hasattr(param.annotation, "__name__")
                else ""
            )
            if param.default == inspect.Parameter.empty:
                params.append(f"{param_name}{annotation}")
            else:
                params.append(f"{param_name}{annotation} = {param.default!r}")
        return f'{task_name}({", ".join(params)})'
