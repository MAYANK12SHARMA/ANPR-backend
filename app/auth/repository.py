"""
Database Layer.

Responsible only for database operations.

No JWT.

No password verification.

No business logic.
"""

from datetime import datetime
from sqlalchemy.orm import Session
from .models import User, RefreshToken
from .enums import UserRole


class AuthRepository:
    """
    Authentication Repository

    Responsible only for database operations.
    """

    def __init__(self, db: Session):
        self.db = db

    # =====================================================
    # USER
    # =====================================================

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_user_by_email(self, email: str) -> User | None:
        return self.db.query(User).filter(User.email == email).first()

    def get_user_by_username(self, username: str) -> User | None:
        return self.db.query(User).filter(User.username == username).first()

    def get_all_users(self) -> list[User]:
        return self.db.query(User).order_by(User.created_at.desc()).all()

    def create_admin_user(
        self,
        username: str,
        full_name: str,
        email: str,
        hashed_password: str,
        phone: str | None,
        role: UserRole,
    ) -> User:

        user = User(
            username=username,
            full_name=full_name,
            email=email,
            hashed_password=hashed_password,
            phone=phone,
            role=role,
        )

        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        return user

    def create_user(
        self,
        username: str,
        full_name: str,
        email: str,
        hashed_password: str,
    ) -> User:

        user = User(
            username=username,
            full_name=full_name,
            email=email,
            hashed_password=hashed_password,
        )

        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        return user

    def update_last_login(
        self,
        user: User,
    ) -> None:

        user.last_login = datetime.utcnow()

        self.db.commit()

    def update_user(
        self,
        user: User,
    ) -> User:

        self.db.commit()
        self.db.refresh(user)

        return user

    def delete_user(
        self,
        user: User,
    ) -> None:

        self.db.delete(user)

        self.db.commit()

    # =====================================================
    # REFRESH TOKEN
    # =====================================================

    def save_refresh_token(
        self,
        user_id: int,
        token: str,
        expires_at: datetime,
    ) -> RefreshToken:

        refresh_token = RefreshToken(
            user_id=user_id,
            token=token,
            expires_at=expires_at,
        )

        self.db.add(refresh_token)
        self.db.commit()
        self.db.refresh(refresh_token)

        return refresh_token

    def get_refresh_token(
        self,
        token: str,
    ) -> RefreshToken | None:

        return (
            self.db.query(RefreshToken)
            .filter(
                RefreshToken.token == token,
                RefreshToken.revoked == False,
            )
            .first()
        )

    def revoke_refresh_token(
        self,
        token: str,
    ) -> bool:

        refresh = (
            self.db.query(RefreshToken)
            .filter(
                RefreshToken.token == token,
                RefreshToken.revoked == False,
            )
            .first()
        )

        if refresh is None:
            return False

        refresh.revoked = True

        self.db.commit()

        return True

    def revoke_all_tokens(
        self,
        user_id: int,
    ) -> None:

        tokens = (
            self.db.query(RefreshToken)
            .filter(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked == False,
            )
            .all()
        )

        for token in tokens:
            token.revoked = True

        self.db.commit()
