"""
檢查 Celery Beat 與 Worker 狀態的 Django Management Command。
"""

from celery import current_app
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from ...utils.schedule import get_next_run_time


def _get_app():
    return current_app._get_current_object()


class Command(BaseCommand):
    help = "檢查 Celery Beat 與 Worker 狀態，支援逐一執行檢查並格式化輸出"

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            type=str,
            choices=["worker", "beat", "all"],
            default="all",
            help="選擇要執行的檢查項目 (worker, beat, all)",
        )
        parser.add_argument(
            "--format",
            type=str,
            choices=["simple", "detailed"],
            default="detailed",
            help="輸出格式 (simple, detailed)",
        )

    def handle(self, *args, **options):
        check_type = options["check"]
        format_type = options["format"]

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("Celery 狀態檢查工具"))
        self.stdout.write("=" * 80 + "\n")

        if check_type in ("worker", "all"):
            self.check_worker_status(format_type)
        if check_type in ("beat", "all"):
            self.check_beat_status(format_type)

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("檢查完成"))
        self.stdout.write("=" * 80 + "\n")

    # ── Worker ────────────────────────────────────────────────────────────

    def check_worker_status(self, format_type="detailed"):
        self.stdout.write("\n" + "-" * 80)
        self.stdout.write(self.style.WARNING("【檢查 Worker 狀態】"))
        self.stdout.write("-" * 80)

        try:
            inspect = _get_app().control.inspect()

            self.stdout.write("\n[1] 檢查 Worker 連線狀態...")
            active_workers = inspect.active()
            stats = inspect.stats()
            registered = inspect.registered()

            if not active_workers and not stats:
                self.stdout.write(self.style.ERROR("  ❌ 沒有可用的 Worker 連線"))
                return

            worker_names = list(stats.keys()) if stats else list(active_workers.keys())
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ 找到 {len(worker_names)} 個 Worker")
            )
            for worker_name in worker_names:
                self.stdout.write(f"    - {worker_name}")

            if format_type == "detailed" and stats:
                self._print_worker_stats(stats)

            self._print_active_tasks(active_workers, format_type)
            self._print_scheduled_tasks(inspect.scheduled(), format_type)
            self._print_registered_tasks(registered, format_type)

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"  ❌ 檢查 Worker 狀態時發生錯誤: {e}")
            )

    def _print_worker_stats(self, stats):
        self.stdout.write("\n[2] Worker 統計資訊...")
        for worker_name, worker_stats in stats.items():
            self.stdout.write(f"\n  Worker: {self.style.WARNING(worker_name)}")
            pool_info = worker_stats.get("pool", {})
            if pool_info:
                self.stdout.write(f'    Pool: {pool_info.get("implementation", "N/A")}')
                self.stdout.write(
                    f'    最大 Worker 數: {pool_info.get("max-concurrency", "N/A")}'
                )
            total = worker_stats.get("total")
            if isinstance(total, dict):
                self.stdout.write(
                    f"    總處理任務數: {sum(total.values())} (共 {len(total)} 種任務)"
                )
                for task_name, count in sorted(
                    total.items(), key=lambda x: x[1], reverse=True
                ):
                    self.stdout.write(f"      • {task_name}: {count} 次")
            elif total is not None:
                self.stdout.write(f"    總處理任務數: {total}")
            if "rss" in worker_stats:
                memory_mb = worker_stats["rss"] / 1024 / 1024
                self.stdout.write(f"    記憶體使用: {memory_mb:.2f} MB")

    def _print_active_tasks(self, active_workers, format_type):
        self.stdout.write("\n[3] 檢查活躍任務...")
        total_active = 0
        for worker_name, tasks in (active_workers or {}).items():
            if not tasks:
                continue
            total_active += len(tasks)
            if format_type == "detailed":
                self.stdout.write(f"\n  Worker: {self.style.WARNING(worker_name)}")
                self.stdout.write(f"    活躍任務數: {len(tasks)}")
                for task in tasks[:5]:
                    task_name = task.get("name", "Unknown")
                    task_id = task.get("id", "Unknown")
                    self.stdout.write(f"      - {task_name} (ID: {task_id[:8]}...)")
                if len(tasks) > 5:
                    self.stdout.write(f"      ... 還有 {len(tasks) - 5} 個任務")
        if total_active == 0:
            self.stdout.write(self.style.SUCCESS("  ✓ 目前沒有活躍的任務"))
        else:
            self.stdout.write(
                self.style.WARNING(f"  ⚠ 總共有 {total_active} 個活躍任務")
            )

    def _print_scheduled_tasks(self, scheduled, format_type):
        self.stdout.write("\n[4] 檢查已排程任務...")
        total_scheduled = 0
        for worker_name, tasks in (scheduled or {}).items():
            if not tasks:
                continue
            total_scheduled += len(tasks)
            if format_type == "detailed":
                self.stdout.write(f"\n  Worker: {self.style.WARNING(worker_name)}")
                self.stdout.write(f"    已排程任務數: {len(tasks)}")
                for task in tasks[:3]:
                    task_name = task.get("request", {}).get("task", "Unknown")
                    task_eta = task.get("eta", "Unknown")
                    self.stdout.write(f"      - {task_name} (ETA: {task_eta})")
                if len(tasks) > 3:
                    self.stdout.write(f"      ... 還有 {len(tasks) - 3} 個任務")
        if total_scheduled > 0:
            self.stdout.write(
                self.style.WARNING(f"  ⚠ 總共有 {total_scheduled} 個已排程任務")
            )
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ 目前沒有已排程的任務"))

    def _print_registered_tasks(self, registered, format_type):
        self.stdout.write("\n[5] 檢查已註冊任務...")
        if not registered:
            self.stdout.write(self.style.ERROR("  ❌ 沒有找到已註冊的任務"))
            return
        all_registered = set()
        for tasks in registered.values():
            all_registered.update(tasks or [])
        self.stdout.write(
            self.style.SUCCESS(f"  ✓ 總共註冊了 {len(all_registered)} 個任務")
        )
        if format_type == "detailed":
            for idx, task_name in enumerate(sorted(all_registered), 1):
                self.stdout.write(f"    {idx:3d}. {task_name}")

    # ── Beat ──────────────────────────────────────────────────────────────

    def check_beat_status(self, format_type="detailed"):
        self.stdout.write("\n" + "-" * 80)
        self.stdout.write(self.style.WARNING("【檢查 Beat 狀態】"))
        self.stdout.write("-" * 80)

        try:
            self.stdout.write("\n[1] 檢查 PeriodicTask 總數...")
            total_tasks = PeriodicTask.objects.count()
            enabled_count = PeriodicTask.objects.filter(enabled=True).count()
            disabled_count = total_tasks - enabled_count

            self.stdout.write(self.style.SUCCESS(f"  ✓ 總任務數: {total_tasks}"))
            line = self.style.SUCCESS(f"  ✓ 已啟用: {enabled_count}")
            if disabled_count > 0:
                line += f' | {self.style.WARNING(f"已停用: {disabled_count}")}'
            self.stdout.write(line)

            if format_type == "detailed":
                self._print_task_list()

            self._print_upcoming_tasks(format_type)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ 檢查 Beat 狀態時發生錯誤: {e}"))
            if format_type == "detailed":
                import traceback

                self.stdout.write(traceback.format_exc())

    def _print_task_list(self):
        self.stdout.write("\n[2] 任務列表...")
        tasks = PeriodicTask.objects.all().order_by("enabled", "name")
        if not tasks.exists():
            self.stdout.write(self.style.WARNING("  ⚠ 沒有找到任何 PeriodicTask"))
            return

        for task in tasks:
            if task.enabled:
                status_icon, status_text, name_style = (
                    "✓",
                    self.style.SUCCESS("已啟用"),
                    self.style.SUCCESS,
                )
            else:
                status_icon, status_text, name_style = (
                    "✗",
                    self.style.ERROR("已停用"),
                    self.style.WARNING,
                )

            self.stdout.write(f"\n  {status_icon} {name_style(task.name)}")
            self.stdout.write(f"      ID: {task.id}")
            self.stdout.write(f"      狀態: {status_text}")
            self.stdout.write(f"      任務名稱: {task.task}")

            schedule_info = self._get_schedule_info(task)
            if schedule_info:
                self.stdout.write(f"      執行週期: {schedule_info}")

            next_run = self._next_run_time(task)
            if next_run:
                self.stdout.write(
                    f"      下次執行時間: {self.style.SUCCESS(str(next_run))}"
                )

            if task.last_run_at:
                self.stdout.write(f"      最後執行時間: {task.last_run_at}")
            else:
                self.stdout.write("      最後執行時間: 尚未執行")
            if task.total_run_count:
                self.stdout.write(f"      總執行次數: {task.total_run_count}")

    def _print_upcoming_tasks(self, format_type):
        self.stdout.write("\n[3] 檢查即將執行的任務...")
        now = timezone.now()
        upcoming_tasks = []
        for task in PeriodicTask.objects.filter(enabled=True):
            next_run = self._next_run_time(task)
            if next_run and next_run > now:
                upcoming_tasks.append((task.name, next_run, self._get_schedule_info(task)))

        if not upcoming_tasks:
            self.stdout.write(self.style.WARNING("  ⚠ 沒有找到即將執行的任務"))
            return

        upcoming_tasks.sort(key=lambda x: x[1])
        self.stdout.write(
            self.style.SUCCESS(f"  ✓ 找到 {len(upcoming_tasks)} 個即將執行的任務")
        )
        if format_type == "detailed":
            for task_name, next_run, schedule_info in upcoming_tasks[:10]:
                self.stdout.write(f"\n    {self.style.WARNING(task_name)}")
                self.stdout.write(f"      下次執行: {self.style.SUCCESS(str(next_run))}")
                if schedule_info:
                    self.stdout.write(f"      執行週期: {schedule_info}")

    @staticmethod
    def _next_run_time(task):
        """crontab/interval 用套件的 get_next_run_time，clocked 直接取設定時間"""
        if not task.enabled:
            return None
        if task.clocked:
            clocked_time = task.clocked.clocked_time
            return clocked_time if clocked_time > timezone.now() else None
        try:
            return get_next_run_time(task)
        except Exception:
            return None

    @staticmethod
    def _get_schedule_info(task):
        if task.crontab:
            cron = task.crontab
            crontab_str = (
                f"{cron.minute} {cron.hour} {cron.day_of_week} "
                f"{cron.day_of_month} {cron.month_of_year}"
            )
            return f"Crontab ({crontab_str}, {cron.timezone})"
        if task.interval:
            period_map = {
                "days": "天",
                "hours": "小時",
                "minutes": "分鐘",
                "seconds": "秒",
                "microseconds": "微秒",
            }
            period_cn = period_map.get(task.interval.period, task.interval.period)
            return f"Interval (每 {task.interval.every} {period_cn})"
        if task.solar:
            solar = task.solar
            return f"Solar ({solar.event} at {solar.latitude}, {solar.longitude})"
        if task.clocked:
            return f"Clocked (執行時間: {task.clocked.clocked_time})"
        return None
