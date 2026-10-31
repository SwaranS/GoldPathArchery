from django.urls import path
from . import views

app_name = "clubs"
urlpatterns = [
    path("", views.directory, name="directory"),
    path("request/", views.apply, name="apply"),
    path("drafts/<uuid:claim_id>/", views.apply, name="draft"),
    path("claims/<uuid:claim_id>/", views.claim, name="claim"),
    path("verification/", views.queue, name="queue"),
    path("verification/<uuid:claim_id>/", views.review, name="review"),
    path("evidence/<uuid:evidence_id>/", views.evidence_download, name="evidence"),
    path("<uuid:club_id>/manage/", views.manage, name="manage"),
    path("<slug:slug>/", views.profile, name="profile"),
]
