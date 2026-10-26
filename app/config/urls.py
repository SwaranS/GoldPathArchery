from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path


def home(request):
    return HttpResponse(
        "<h1>GoldPathArchery</h1>"
        '<p><a href="/accounts/login/">Sign in or create account with Google</a></p>'
    )


urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("account/", include("accounts.urls")),
]
