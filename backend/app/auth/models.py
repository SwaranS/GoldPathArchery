from typing import Literal

from pydantic import BaseModel, EmailStr


Role = Literal["archer", "coach", "guardian", "admin"]


class AuthenticatedUser(BaseModel):
    subject: str
    email: EmailStr
    name: str
    roles: list[Role]


class DevLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthenticatedUser
