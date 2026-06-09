from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from schedule_kit.views import BaseExecutionRecordViewSet

from .filters import AlertRuleExecutionFilterSet
from .models import AlertRuleTask, AsyncAlertRuleTask
from .serializers import AlertRuleTaskSerializer, AsyncAlertRuleTaskSerializer
from .services import AlertRuleService


class AlertRuleTaskViewSet(viewsets.ModelViewSet):
    """排程 CRUD。存檔後 schedule_kit 自動同步到 PeriodicTask，不需額外呼叫。"""

    queryset = AlertRuleTask.objects.all()
    serializer_class = AlertRuleTaskSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AsyncAlertRuleTaskViewSet(viewsets.ModelViewSet):
    queryset = AsyncAlertRuleTask.objects.all()
    serializer_class = AsyncAlertRuleTaskSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AlertRuleExecutionRecordViewSet(BaseExecutionRecordViewSet):
    """
    執行紀錄唯讀 API。
    - filterset_class：在套件三個基本 filter 上加時間範圍查詢
    - get_queryset：只做權限過濾，serializer 由套件提供不需動
    """

    filterset_class = AlertRuleExecutionFilterSet

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if u.is_staff:
            return qs
        return qs.filter(task_created_by_id=u.id)


@api_view(["POST"])
@permission_classes([AllowAny])  # 外部 agent 打回來，不帶使用者身份
def agent_callback(request):
    """接收外部 agent 的非同步回調，更新 ExecutionRecord status。"""
    record_id = request.data.get("record_id")
    success   = request.data.get("success")
    message   = request.data.get("message", "")

    if record_id is None or success is None:
        return Response({"error": "record_id and success are required"}, status=400)

    AlertRuleService.handle_agent_callback(
        record_id=int(record_id),
        success=bool(success),
        message=str(message),
    )
    return Response({"status": "ok"})
