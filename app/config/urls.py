from django.contrib import admin
from django.http import HttpResponse
from django.urls import path


def home(request):
    return HttpResponse(
        "<h1>GoldPathArchery</h1>"
        "<p>Local development is running.</p>"
    )


urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
]
