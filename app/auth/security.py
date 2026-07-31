"""
Password hashing.

Functions:

hash_password()

verify_password()
"""

from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)


def hash_password(password: str) -> str:
    """
    Hash Password
    """
    return pwd_context.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    """
    Verify Password
    """
    return pwd_context.verify(
        plain_password,
        hashed_password,
    )
