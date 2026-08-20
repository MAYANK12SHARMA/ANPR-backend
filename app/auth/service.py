"""
Authentication business logic.

Responsible for:

Register

Login

Refresh Token

Logout

Profile

Password Change
"""

from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .constants import REFRESH_TOKEN_EXPIRE_DAYS
from .jwt import create_access_token, create_refresh_token, verify_token
from .models import User
from .repository import AuthRepository
from .schemas import (
    LoginResponse,
    UserCreate,
    UserRegister,
    UserResponse,
    UserUpdate,
)
from .security import hash_password, verify_password

class AuthService:

    def __init__(self, db: Session):
        self.repository = AuthRepository(db)

    # =====================================================
    # REGISTER
    # =====================================================

    def register_user(
        self,
        request: UserRegister,
    ) -> User:

        # Password Match
        if request.password != request.confirm_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Passwords do not match.",
            )

        # Email Exists
        if self.repository.get_user_by_email(request.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists.",
            )

        # Username Exists
        if self.repository.get_user_by_username(request.username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists.",
            )

        # Hash Password
        hashed_password = hash_password(request.password)

        # Create User
        user = self.repository.create_user(
            username=request.username,
            full_name=request.full_name,
            email=request.email,
            hashed_password=hashed_password,
        )

        return user

    # =====================================================
    # LOGIN
    # =====================================================

    def login_user(
        self,
        email: str,
        password: str,
    ):

        user = self.repository.get_user_by_email(email)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Email or Password.",
            )

        if not verify_password(
            password,
            user.hashed_password,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Email or Password.",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )
        self.repository.update_last_login(user)

        access_token = create_access_token(
            {
                "sub": str(user.id),
                "email": user.email,
                "role": user.role.value,
            }
        )

        refresh_token = create_refresh_token(
            {
                "sub": str(user.id),
            }
        )

        expires = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        self.repository.save_refresh_token(
            user.id,
            refresh_token,
            expires,
        )

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=UserResponse.model_validate(user),
        )

    # =====================================================
    # CURRENT USER
    # =====================================================

    def get_current_user(
        self,
        token: str,
    ) -> User:

        payload = verify_token(token)

        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Token."
            )

        user_id = int(payload["sub"])

        user = self.repository.get_user_by_id(user_id)

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user."
            )

        return user

    # =====================================================
    # REFRESH TOKEN
    # =====================================================

    def refresh_access_token(
        self,
        refresh_token: str,
    ):

        token = self.repository.get_refresh_token(refresh_token)

        if token is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Refresh Token Invalid."
            )

        payload = verify_token(refresh_token)

        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Refresh Token Expired."
            )

        user = self.repository.get_user_by_id(int(payload["sub"]))

        access_token = create_access_token(
            {
                "sub": str(user.id),
                "email": user.email,
                "role": user.role.value,
            }
        )

        return access_token

    # =====================================================
    # LOGOUT
    # =====================================================

    def logout(
        self,
        refresh_token: str,
    ):

        success = self.repository.revoke_refresh_token(refresh_token)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or already revoked refresh token.",
            )

        return {"message": "Logged out successfully."}

    # =====================================================
    # GET ALL USERS
    # =====================================================

    def get_users(self) -> list[User]:

        return self.repository.get_all_users()

    def get_user(
        self,
        user_id: int,
    ) -> User:

        user = self.repository.get_user_by_id(user_id)

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        return user

    # =====================================================
    # CREATE USER (ADMIN)
    # =====================================================

    def create_user(
        self,
        request: UserCreate,
    ) -> User:

        request.username = request.username.strip().lower()

        if self.repository.get_user_by_email(request.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists.",
            )

        if self.repository.get_user_by_username(request.username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists.",
            )

        hashed_password = hash_password(request.password)

        return self.repository.create_admin_user(
            username=request.username,
            full_name=request.full_name,
            email=request.email,
            hashed_password=hashed_password,
            phone=request.phone,
            role=request.role,
        )

    # =====================================================
    # UPDATE USER
    # =====================================================

    def update_user(
        self,
        user_id: int,
        request: UserUpdate,
        current_user: User,
    ) -> User:

        user = self.repository.get_user_by_id(user_id)

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        request.username = request.username.strip().lower()

        if current_user.id == user.id and request.role != current_user.role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot change your own role.",
            )

        if current_user.id == user.id and request.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate your own account.",
            )

        existing = self.repository.get_user_by_email(request.email)

        if existing and existing.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists.",
            )

        existing = self.repository.get_user_by_username(request.username)

        if existing and existing.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists.",
            )

        user.username = request.username
        user.full_name = request.full_name
        user.email = request.email
        user.phone = request.phone
        user.role = request.role
        user.is_active = request.is_active

        # NEW
        user.receive_processing_email = request.receive_processing_email

        return self.repository.update_user(user)

    # =====================================================
    # DELETE USER
    # =====================================================

    # =====================================================
    # MY EMAIL NOTIFICATION
    # =====================================================

    def update_my_email_notification(
        self,
        enabled: bool,
        current_user: User,
    ) -> User:
        """
        Enable or disable processing completion
        emails for the logged-in user.
        """

        return self.repository.update_email_notification(
            current_user,
            enabled,
        )

    # =====================================================
    # ADMIN / OPERATOR EMAIL NOTIFICATION
    # =====================================================


    def update_user_email_notification(
        self,
        user_id: int,
        enabled: bool,
        current_user: User,
    ) -> User:

        user = self.repository.get_user_by_id(user_id)

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        # Admin
        if current_user.role.value == "admin":
            return self.repository.update_email_notification(
                user,
                enabled,
            )

        # Operator
        if current_user.role.value == "operator":

            if user.role.value == "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Operators cannot modify admin notification settings.",
                )

            return self.repository.update_email_notification(
                user,
                enabled,
            )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied.",
        )

    def delete_user(
        self,
        user_id: int,
        current_user: User,
    ) -> dict:

        if current_user.id == user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot delete your own account.",
            )

        user = self.repository.get_user_by_id(user_id)

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        self.repository.delete_user(user)

        return {"message": "User deleted successfully."}
