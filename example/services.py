import os

import requests as http_requests

from schedule_kit.api import update_record

from .models import AlertRuleTask

AGENT_URL    = os.environ.get("AGENT_URL",    "http://your-agent-service/dispatch")
CALLBACK_URL = os.environ.get("CALLBACK_URL", "http://web:8000/api/agent-callback/")


class AlertRuleService:

    @staticmethod
    def check_and_notify(task: AlertRuleTask) -> tuple[bool, str]:
        try:
            cpu = _get_cpu_usage(task.target_host)
            if cpu >= task.cpu_threshold:
                _send_alert_email(task.notify_email, task.target_host, cpu)
            return True, f"cpu={cpu:.1f}% threshold={task.cpu_threshold}%"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def dispatch_to_agent(task: AlertRuleTask, record_id: int) -> None:
        """非同步任務：把工作丟給外部 agent，帶入 record_id 讓 agent 打回來時能對應紀錄。"""
        http_requests.post(
            AGENT_URL,
            json={
                "record_id":    record_id,
                "callback_url": CALLBACK_URL,
            },
            timeout=10,
        )

    @staticmethod
    def handle_agent_callback(record_id: int, success: bool, message: str) -> None:
        """agent 打回來時呼叫，更新 ExecutionRecord status 與 end_time。"""
        update_record(record_id, success=success, message=message)


# ── 各服務自己實作 ────────────────────────────────────────────────────────────

import logging
import random

_logger = logging.getLogger(__name__)


def _get_cpu_usage(host: str) -> float:
    return round(random.uniform(10, 95), 1)


def _send_alert_email(email: str, host: str, cpu: float) -> None:
    _logger.warning("[ALERT] CPU on %s is %.1f%% — notification sent to %s", host, cpu, email)
