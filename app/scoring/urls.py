from django.urls import path
from . import views

urlpatterns = [
    path("athlete/<uuid:athlete_id>/", views.history, name="scoring-history"),
    path("athlete/<uuid:athlete_id>/start/", views.start, name="scoring-start"),
    path("athlete/<uuid:athlete_id>/equipment/", views.equipment, name="scoring-equipment"),
    path("session/<uuid:session_id>/", views.session, name="scoring-session"),
    path("session/<uuid:session_id>/save/", views.save, name="scoring-save"),
]
