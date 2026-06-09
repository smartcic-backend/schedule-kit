from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AlertRuleExecutionRecordViewSet,
    AlertRuleTaskViewSet,
    AsyncAlertRuleTaskViewSet,
    agent_callback,
)

router = DefaultRouter()
router.register("alert-rules", AlertRuleTaskViewSet, basename="alert-rule")
router.register("async-alert-rules", AsyncAlertRuleTaskViewSet, basename="async-alert-rule")
router.register("executions", AlertRuleExecutionRecordViewSet, basename="alert-rule-execution")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api-auth/", include("rest_framework.urls")),  # browsable API 登入登出
    path("api/", include(router.urls)),
    path("api/agent-callback/", agent_callback, name="agent-callback"),
]
