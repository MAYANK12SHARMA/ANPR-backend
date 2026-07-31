import re


def normalize_email(email: str) -> str:
    """
    Convert email to lowercase and strip spaces.
    """
    return email.strip().lower()


def validate_password(password: str) -> bool:
    """
    Password Rules

    - Minimum 8 characters
    - One uppercase
    - One lowercase
    - One number
    """

    pattern = (
        r"^(?=.*[a-z])"
        r"(?=.*[A-Z])"
        r"(?=.*\d)"
        r".{8,}$"
    )

    return bool(re.match(pattern, password))