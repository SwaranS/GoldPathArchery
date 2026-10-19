from datetime import datetime, timedelta, timezone

import jwt

from .config import Settings
from .models import AuthenticatedUser


DEV_USERS: dict[str, AuthenticatedUser] = {
    "archer": AuthenticatedUser(
        subject="dev-archer-001",
        email="archer.local@goldpath.test",
        name="Local Archer",
        roles=["archer"],
    ),
    "coach": AuthenticatedUser(
        subject="dev-coach-001",
        email="coach.local@goldpath.test",
        name="Local Coach",
        roles=["coach"],
    ),
    "guardian": AuthenticatedUser(
        subject="dev-guardian-001",
        email="guardian.local@goldpath.test",
        name="Local Guardian",
        roles=["guardian"],
    ),
    "admin": AuthenticatedUser(
        subject="dev-admin-001",
        email="admin.local@goldpath.test",
        name="Local Admin",
        roles=["admin"],
    ),
}


def create_dev_token(user: AuthenticatedUser, settings: Settings) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.dev_token_ttl_minutes)

    payload = {
        "sub": user.subject,
        "email": user.email,
        "name": user.name,
        "roles": user.roles,
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }

    token = jwt.encode(payload, settings.dev_jwt_secret, algorithm="HS256")
    return token, int((expires - now).total_seconds())
