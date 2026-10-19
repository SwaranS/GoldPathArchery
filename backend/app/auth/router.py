from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from .config import Settings, get_settings
from .dependencies import get_current_user
from .dev_tokens import DEV_USERS, create_dev_token
from .models import AuthenticatedUser, DevLoginResponse

router = APIRouter()


@router.get("/dev/users")
def list_dev_users(settings: Annotated[Settings, Depends(get_settings)]):
    _require_dev_auth(settings)
    return DEV_USERS


@router.post("/dev/login/{user_key}", response_model=DevLoginResponse)
def dev_login(user_key: str, settings: Annotated[Settings, Depends(get_settings)]):
    _require_dev_auth(settings)
    user = DEV_USERS.get(user_key)
    if user is None:
        raise HTTPException(status_code=404, detail="Unknown development user")

    token, expires_in = create_dev_token(user, settings)
    return DevLoginResponse(access_token=token, expires_in=expires_in, user=user)


@router.get("/api/me", response_model=AuthenticatedUser)
def me(current_user: Annotated[AuthenticatedUser, Depends(get_current_user)]):
    return current_user


def _require_dev_auth(settings: Settings) -> None:
    if settings.app_env != "local" or settings.auth_mode != "dev":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Development authentication is disabled",
        )
