from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.orm import Session

from app.db.database import SessionLocal

from .dependencies import (
    get_current_user,
    require_admin,
)
from .models import User
from .schemas import (
    LoginResponse,
    RefreshTokenRequest,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from .service import AuthService

router = APIRouter()


# =====================================================
# Database Dependency
# =====================================================


def get_db():
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


# # =====================================================
# # Register
# # =====================================================


# @router.post(
#     "/register",
#     response_model=UserResponse,
#     status_code=201,
# )
# def register(
#     request: UserRegister,
#     db: Session = Depends(get_db),
# ):
#     service = AuthService(db)

#     user = service.register_user(request)

#     return user


# =====================================================
# Login
# =====================================================


@router.post(
    "/login",
    response_model=LoginResponse,
)
def login(
    request: UserLogin,
    db: Session = Depends(get_db),
):
    service = AuthService(db)

    return service.login_user(
        request.email,
        request.password,
    )


# =====================================================
# Current User
# =====================================================


@router.get(
    "/me",
    response_model=UserResponse,
)
def get_profile(
    current_user: User = Depends(get_current_user),
):
    return current_user


# =====================================================
# Refresh Token
# =====================================================


@router.post("/refresh")
def refresh_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    service = AuthService(db)

    access_token = service.refresh_access_token(request.refresh_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


# =====================================================
# Logout
# =====================================================


@router.post("/logout")
def logout(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    service = AuthService(db)

    return service.logout(request.refresh_token)


# =====================================================
# Get All Users (Admin)
# =====================================================


@router.get(
    "/users",
    response_model=list[UserResponse],
)
def get_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):

    service = AuthService(db)

    return service.get_users()


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    service = AuthService(db)

    return service.get_user(user_id)


# =====================================================
# Create User (Admin)
# =====================================================


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    request: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    service = AuthService(db)

    return service.create_user(request)


# =====================================================
# Update User (Admin)
# =====================================================


@router.put(
    "/users/{user_id}",
    response_model=UserResponse,
)
def update_user(
    user_id: int,
    request: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    service = AuthService(db)

    return service.update_user(
        user_id,
        request,
        admin,
    )


@router.patch(
    "/me/email-notification",
    response_model=UserResponse,
)
def update_my_email_notification(
    enabled: bool = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = AuthService(db)

    return service.update_my_email_notification(
        enabled=enabled,
        current_user=current_user,
    )


 



# =====================================================
# Delete User (Admin)
# =====================================================


@router.delete(
    "/users/{user_id}",
)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    service = AuthService(db)

    return service.delete_user(user_id, admin)


# =====================================================
# Get User By ID (Admin)
# =====================================================
