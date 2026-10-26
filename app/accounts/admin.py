from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, UserRole


class UserRoleInline(admin.TabularInline):
    model = UserRole
    extra = 0


@admin.register(User)
class GoldPathUserAdmin(UserAdmin):
    inlines = [UserRoleInline]


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "created_at")
    list_filter = ("role",)
