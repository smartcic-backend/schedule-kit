from django.contrib import admin

from .models import AlertRuleTask


@admin.register(AlertRuleTask)
class AlertRuleTaskAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "execution_cycle", "target_host", "updated_at"]
    list_filter = ["status"]
    search_fields = ["title", "target_host"]
