from django.urls import path
from . import views, membership_views

app_name = "clubs"
urlpatterns = [
    path("", views.directory, name="directory"),
    path("memberships/", membership_views.mine, name="memberships"),
    path("invitations/<uuid:action_id>/", membership_views.accept_invitation, name="invitation"),
    path("appointments/<uuid:action_id>/", membership_views.role_response, name="role-response"),
    path("memberships/<uuid:member_id>/leave/", membership_views.leave, name="leave"),
    path("athletes/<uuid:athlete_id>/home/", membership_views.home, name="home-club"),
    path("<uuid:club_id>/join/", membership_views.join, name="join"),
    path("<uuid:club_id>/members/", membership_views.manage, name="membership-manage"),
    path("<uuid:club_id>/invite/", membership_views.invite, name="invite"),
    path("request/", views.apply, name="apply"),
    path("drafts/<uuid:claim_id>/", views.apply, name="draft"),
    path("claims/<uuid:claim_id>/", views.claim, name="claim"),
    path("verification/", views.queue, name="queue"),
    path("verification/<uuid:claim_id>/", views.review, name="review"),
    path("evidence/<uuid:evidence_id>/", views.evidence_download, name="evidence"),
    path("<uuid:club_id>/manage/", views.manage, name="manage"),
    path("<slug:slug>/", views.profile, name="profile"),
]
