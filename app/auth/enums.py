from enum import Enum


class UserRole(str, Enum):
    """
    Supported roles inside the system.
    """

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class TokenType(str, Enum):
    """
    JWT Token Types.
    """

    ACCESS = "access"
    REFRESH = "refresh"