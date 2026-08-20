"""
Role Based Permissions.

Admin

Operator

Viewer
"""

"""
Role Based Permissions

Admin

Operator

Viewer
"""
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Job

from .dependencies import get_current_user
from .enums import UserRole
from .models import User


def require_admin(
    current_user: User = Depends(get_current_user),
):

    if current_user.role != UserRole.ADMIN:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required.",
        )

    return current_user


def require_operator(
    current_user: User = Depends(get_current_user),
):

    if current_user.role not in [
        UserRole.ADMIN,
        UserRole.OPERATOR,
    ]:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator permission required.",
        )

    return current_user


def require_viewer(
    current_user: User = Depends(get_current_user),
):

    return current_user


def get_job_for_read(
    db: Session,
    job_id: str,
) -> Job:
    """
    Everyone (Admin, Operator, Viewer) can read any job.
    """
    job = db.query(Job).filter(Job.job_id == job_id).first()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        )

    return job


def get_job_for_update(
    db: Session,
    job_id: str,
    current_user: User,
) -> Job:
    """
    Admin -> Any job
    Operator -> Own jobs only
    Viewer -> No access
    """

    job = get_job_for_read(db, job_id)

    if current_user.role.value == "admin":
        return job

    if current_user.role.value == "operator":
        if job.owner_id == current_user.id:
            return job

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only modify your own jobs.",
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Viewer accounts cannot modify jobs.",
    )


def get_job_for_delete(
    db: Session,
    job_id: str,
    current_user: User,
) -> Job:
    """
    Admin -> Delete any job
    Operator -> Delete own job
    Viewer -> Cannot delete
    """

    job = get_job_for_read(db, job_id)

    if current_user.role.value == "admin":
        return job

    if current_user.role.value == "operator":
        if job.owner_id == current_user.id:
            return job

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own jobs.",
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Viewer accounts cannot delete jobs.",
    )
