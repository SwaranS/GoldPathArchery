"""Presentation preferences only; athlete permissions remain object-specific."""

from .permissions import accessible_athletes, can, is_admin

WORKSPACES = {"archer": "My training", "parent": "Family", "coach": "Coaching"}


def navigation(request):
    roles = set()
    athlete_options = []
    if request.user.is_authenticated:
        roles = set(request.user.role_assignments.values_list("role", flat=True))
        # Explicit relationships, not declared roles, determine the available targets.
        athlete_options = [
            {"id": str(athlete.pk), "name": athlete.display_name}
            for athlete in accessible_athletes(request.user).order_by("display_name", "pk")
            if can(request.user, athlete, "view")
        ]
    return {"workspaces": [
        {"key": key, "label": label} for key, label in WORKSPACES.items() if key in roles
    ], "has_archer_role": "archer" in roles, "is_admin": is_admin(request.user),
        "athlete_switcher_options": athlete_options,
        "show_athlete_switcher": len(athlete_options) > 1,
    }
