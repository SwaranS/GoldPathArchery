from django.urls import path

from scoring.views import equipment

from . import athlete_views
from .views import profile
from . import workspace_views, plan_views

urlpatterns = [
    path("plans/", plan_views.my_plans, name="my-plans"),
    path("start/", workspace_views.landing, name="workspace-home"),
    path("workspace/<str:workspace>/", workspace_views.workspace, name="workspace"),
    path("profile/", profile, name="account-profile"),
    path("athletes/", athlete_views.athletes, name="athletes"),
    path(
        "athletes/<uuid:athlete_id>/",
        athlete_views.athlete_detail,
        name="athlete-detail",
    ),
    path(
        "athletes/<uuid:athlete_id>/today/",
        athlete_views.athlete_section,
        {"section": "today"},
        name="athlete-today",
    ),
    path(
        "athletes/<uuid:athlete_id>/plans/",
        plan_views.plans,
        name="athlete-plans",
    ),
    path(
        "athletes/<uuid:athlete_id>/score/",
        athlete_views.athlete_section,
        {"section": "score"},
        name="athlete-score",
    ),
    path(
        "athletes/<uuid:athlete_id>/progress/",
        athlete_views.athlete_section,
        {"section": "progress"},
        name="athlete-progress",
    ),
    path(
        "athletes/<uuid:athlete_id>/equipment/",
        equipment,
        name="athlete-equipment",
    ),
    path(
        "athletes/<uuid:athlete_id>/export/",
        athlete_views.athlete_section,
        {"section": "export"},
        name="athlete-export",
    ),
    path(
        "athletes/<uuid:athlete_id>/invite/",
        athlete_views.invitation_create,
        name="invitation-create",
    ),
    path(
        "athletes/<uuid:athlete_id>/invitations/<uuid:invitation_id>/revoke/",
        athlete_views.invitation_revoke,
        name="invitation-revoke",
    ),
    path(
        "athletes/<uuid:athlete_id>/grants/<str:kind>/<int:link_id>/",
        athlete_views.grant_update,
        name="grant-update",
    ),
    path(
        "athletes/<uuid:athlete_id>/parent-review/",
        athlete_views.parent_review,
        name="parent-review",
    ),
    path(
        "invitations/<str:token>/",
        athlete_views.invitation_accept,
        name="invitation-accept",
    ),
    path(
        "discovery/",
        athlete_views.workspace_section,
        {"section": "discovery"},
        name="athlete-discovery",
    ),
    path(
        "contributions/",
        athlete_views.workspace_section,
        {"section": "contributions"},
        name="coach-contributions",
    ),
    path(
        "manager/",
        athlete_views.workspace_section,
        {"section": "manager"},
        name="manager-queue",
    ),
    path(
        "admin-ops/",
        athlete_views.workspace_section,
        {"section": "admin_ops"},
        name="admin-ops",
    ),
]
