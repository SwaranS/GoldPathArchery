from django.contrib import admin
from django.http import Http404, HttpResponse
from django.urls import include, path


def home(request):
    return HttpResponse(
        "<h1>GoldPathArchery</h1>"
        '<p><a href="/accounts/login/">Sign in or create account with Google</a></p>'
    )


def disabled_password_signup(request):
    # Public registration must go through verified Google OAuth, not local passwords.
    raise Http404("Use Google sign-in to create an account.")


urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("accounts/signup/", disabled_password_signup),
    path("accounts/", include("allauth.urls")),
    path("account/", include("accounts.urls")),
]
