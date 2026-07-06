from django.contrib import admin

from .models import AlertRuleTask


@admin.register(AlertRuleTask)
class AlertRuleTaskAdmin(admin.ModelAdmin):
    list_display = ["name", "enabled", "execution_cycle", "target_host", "updated_at"]
    list_filter = ["enabled"]
    search_fields = ["name", "target_host"]
