from django.urls import path
from . import views

urlpatterns = [
    path("new", views.new, name="training-new"),
    path("new/", views.new),
    path("plans/<uuid:pk>/", views.detail, name="training-detail"),
]
