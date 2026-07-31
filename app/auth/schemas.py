"""
Pydantic Schemas.

Will contain:

UserCreate

UserLogin

UserResponse

TokenResponse

RefreshRequest

ChangePassword

UserUpdate
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .enums import UserRole


# -----------------------------
# Register
# -----------------------------
class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    full_name: str = Field(..., min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(..., min_length=8)
    confirm_password: str


# -----------------------------
# Login
# -----------------------------
class UserLogin(BaseModel):
    email: EmailStr
    password: str


# -----------------------------
# Refresh Token
# -----------------------------
class RefreshTokenRequest(BaseModel):
    refresh_token: str


# -----------------------------
# Change Password
# -----------------------------
class ChangePassword(BaseModel):
    old_password: str
    new_password: str
    confirm_password: str


# -----------------------------
# User Response
# -----------------------------
class UserResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int

    username: str

    full_name: str

    email: EmailStr

    phone: str | None = None

    profile_image: str | None = None

    role: UserRole

    is_active: bool

    is_verified: bool

    last_login: datetime | None = None

    created_at: datetime


# -----------------------------
# Login Response
# -----------------------------
class LoginResponse(BaseModel):

    access_token: str

    refresh_token: str

    token_type: str = "bearer"

    user: UserResponse


# =====================================================
# Admin User Create
# =====================================================


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)

    full_name: str = Field(..., min_length=2, max_length=150)

    email: EmailStr

    password: str = Field(..., min_length=8)

    phone: str | None = None

    role: UserRole = UserRole.OPERATOR


# =====================================================
# Admin User Update
# =====================================================


class UserUpdate(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)

    full_name: str = Field(..., min_length=2, max_length=150)

    email: EmailStr

    phone: str | None = None

    role: UserRole

    is_active: bool


# =====================================================
# User List Response
# =====================================================


class UserListResponse(BaseModel):

    users: list[UserResponse]
