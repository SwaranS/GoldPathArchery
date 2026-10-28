"""Presentation preferences only; athlete permissions remain object-specific."""

WORKSPACES = {"archer": "My training", "parent": "Family", "coach": "Coaching"}


def navigation(request):
    roles = set()
    if request.user.is_authenticated:
        roles = set(request.user.role_assignments.values_list("role", flat=True))
    return {"workspaces": [
        {"key": key, "label": label} for key, label in WORKSPACES.items() if key in roles
    ], "has_archer_role": "archer" in roles}
