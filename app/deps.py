"""Auth dependencies — JWT-based session management.

Replaces the old MSAL-based session dependency. Each authenticated request
carries a JWT cookie which we decode here to look up the current user.
"""
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .database import get_db
from .models import Employee

# Cookie name — same across the app
SESSION_COOKIE = "metfraa_session"

# JWT settings
JWT_SECRET = os.getenv("SESSION_SECRET") or os.getenv("SECRET_KEY") or "change-me-in-production"
JWT_ALG = "HS256"
JWT_EXPIRY_HOURS = 8


def issue_session_token(employee: Employee) -> str:
    """Create a signed JWT for this employee. Returned string goes in the cookie."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(employee.id),
        "code": employee.employee_code,
        "is_admin": bool(employee.is_admin),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXPIRY_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def set_session_cookie(response: Response, token: str) -> None:
    """Attach the session cookie to a response (login/change-password success)."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=JWT_EXPIRY_HOURS * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Wipe the session cookie (logout)."""
    response.delete_cookie(SESSION_COOKIE, path="/")


def _decode_session(request: Request) -> dict | None:
    """Decode the JWT from the cookie. Returns payload dict or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Employee:
    """FastAPI dependency — resolve the logged-in Employee, or 401.

    NOTE: This does NOT enforce that must_reset_password=False. Callers who
    should refuse mid-reset users (like most routes) get that check via
    get_current_user_ready. This one exists for the change-password route
    itself, which must be reachable in the mid-reset state.
    """
    payload = _decode_session(request)
    if not payload:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid session")

    user = db.query(Employee).filter_by(id=user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def get_current_user_ready(
    user: Employee = Depends(get_current_user),
) -> Employee:
    """Same as get_current_user but rejects users who still need to reset their password.

    Applied to every route except /auth/change-password.
    """
    if user.must_reset_password:
        raise HTTPException(status_code=403, detail="Password reset required")
    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Employee | None:
    """Non-throwing version — for pages that render differently for anonymous users."""
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


def require_admin(
    user: Employee = Depends(get_current_user_ready),
) -> Employee:
    """FastAPI dependency — require admin privileges."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
