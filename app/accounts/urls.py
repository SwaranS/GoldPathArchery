from django.urls import path

from . import athlete_views
from .views import profile

urlpatterns = [
    path("profile/", profile, name="account-profile"),
    path("athletes/", athlete_views.athletes, name="athletes"),
    path(
        "athletes/<uuid:athlete_id>/",
        athlete_views.athlete_detail,
        name="athlete-detail",
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
]
