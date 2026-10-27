from copy import deepcopy
import uuid

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import RoundDefinition, RoundStage, ScoringRuleSet, TargetFace, ScoringSession, ScoreChangeAudit
from . import services


class ConfigurationAdmin(admin.ModelAdmin):
    list_display = ("name", "active")
    actions = ("duplicate", "activate", "deactivate")

    @admin.action(description="Duplicate selected configurations", permissions=["add"])
    def duplicate(self, request, queryset):
        for original in queryset:
            stages = list(original.stages.all()) if isinstance(original, RoundDefinition) else []
            copy = deepcopy(original)
            copy.pk = None
            copy.name = original.name[:90] + " (copy)"
            copy.active = False
            copy.save()
            for stage in stages:
                stage.pk = None
                stage.round = copy
                stage.save()

    @admin.action(description="Activate selected configurations", permissions=["change"])
    def activate(self, request, queryset):
        queryset.update(active=True)

    @admin.action(description="Deactivate selected configurations", permissions=["change"])
    def deactivate(self, request, queryset):
        queryset.update(active=False)


admin.site.register(TargetFace, ConfigurationAdmin)
admin.site.register(ScoringRuleSet, ConfigurationAdmin)


class StagesFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if not any(f.cleaned_data and not f.cleaned_data.get("DELETE") for f in self.forms):
            raise ValidationError("Add at least one stage.")


class StageInline(admin.TabularInline):
    model = RoundStage
    formset = StagesFormSet
    extra = 1


@admin.register(RoundDefinition)
class RoundAdmin(ConfigurationAdmin):
    inlines = (StageInline,)
    list_display = ("name", "division", "active", "maximum")


@admin.register(ScoringSession)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("id", "athlete", "context", "status", "verified_at")
    actions = ("verify",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    @admin.action(description="Verify and lock completed competition results", permissions=["change"])
    def verify(self, request, queryset):
        for session in queryset:
            try:
                services.mutate(request.user, session.pk, dict(action="verify", key=str(uuid.uuid4()), version=session.version))
            except ValidationError as error:
                self.message_user(request, "; ".join(error.messages), messages.ERROR)


@admin.register(ScoreChangeAudit)
class AuditAdmin(admin.ModelAdmin):
    list_display = ("session", "actor", "at", "operation")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
