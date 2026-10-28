from django.contrib import admin
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import include, path


def home(request):
    if request.user.is_authenticated:
        return redirect("workspace-home")
    return render(request, "home.html")


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
