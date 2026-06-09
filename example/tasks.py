from schedule_kit.decorators import recorded_task

from .models import AlertRuleTask, AsyncAlertRuleTask
from .services import AlertRuleService


# ── 同步任務：跑完立刻知道結果 ────────────────────────────────────────────────

@recorded_task(name="alert_rule_task", queue="myservice")
def alert_rule_task(task_id: int, record_id: int = 0):
    task = AlertRuleTask.objects.get(id=task_id)
    success, message = AlertRuleService.check_and_notify(task)
    return task, success, message


# ── 非同步任務：把工作丟給外部 agent，等回調 ──────────────────────────────────

@recorded_task(name="alert_rule_async_task", queue="myservice")
def alert_rule_async_task(task_id: int, record_id: int = 0):
    task = AsyncAlertRuleTask.objects.get(id=task_id)
    AlertRuleService.dispatch_to_agent(task, record_id=record_id)
    return task, None, f"dispatched record_id={record_id}"
