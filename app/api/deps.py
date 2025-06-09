"""API dependencies."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from typing import Generator

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.user import User

# Re-export for convenience
__all__ = ["get_db", "get_current_active_user"]


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current active user."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user