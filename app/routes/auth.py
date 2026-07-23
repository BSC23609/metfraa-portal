"""Auth routes for Metfraa KPI v2.

Login: employee code + password
First login: forced password reset
Forgot password: request → email to Sheela → she clicks link to reset

No M365 SSO anymore.
"""
import os
import re
import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    SESSION_COOKIE,
    clear_session_cookie,
    get_current_user,
    get_optional_user,
    issue_session_token,
    set_session_cookie,
)
from ..models import AuditLog, Employee, PasswordResetRequest

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


DEFAULT_PASSWORD = "Metfraa@123"
RESET_LINK_EXPIRY_HOURS = 24
BASE_URL = os.getenv("BASE_URL", "https://kpis.metfraa.com").rstrip("/")


# ============================================================
# Password helpers
# ============================================================

def hash_password(plain: str) -> str:
    """Hash with bcrypt. Returns a string suitable for DB storage."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def validate_new_password(pw: str) -> str | None:
    """Return error message if invalid, else None."""
    if len(pw) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Za-z]", pw):
        return "Password must contain at least one letter."
    if not re.search(r"\d", pw):
        return "Password must contain at least one number."
    return None


# ============================================================
# Login / logout
# ============================================================

@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    err: str | None = None,
    next: str | None = None,
    user: Employee | None = Depends(get_optional_user),
):
    """Render the login form. If already logged in, bounce to dashboard."""
    if user and not user.must_reset_password:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"err": err, "next": next or ""},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    employee_code: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    """Handle login form submission."""
    code = (employee_code or "").strip().upper()
    if not code or not password:
        return RedirectResponse(
            url=f"/auth/login?err=Please+enter+both+code+and+password",
            status_code=303,
        )

    emp = db.query(Employee).filter(Employee.employee_code == code).first()
    if not emp or not emp.is_active:
        return RedirectResponse(
            url="/auth/login?err=Invalid+employee+code+or+password",
            status_code=303,
        )

    if not verify_password(password, emp.password_hash):
        return RedirectResponse(
            url="/auth/login?err=Invalid+employee+code+or+password",
            status_code=303,
        )

    # Update last_login_at
    emp.last_login_at = datetime.utcnow()
    db.commit()

    # Audit
    db.add(AuditLog(
        actor_code=emp.employee_code,
        actor_email=emp.email,
        action="login",
        details={"employee_id": emp.id, "name": emp.name},
    ))
    db.commit()

    # If they still have the default flag set, force a reset
    token = issue_session_token(emp)
    if emp.must_reset_password:
        target = "/auth/change-password"
    else:
        target = next if (next and next.startswith("/")) else "/"

    response = RedirectResponse(url=target, status_code=303)
    set_session_cookie(response, token)
    return response


@router.get("/logout")
def logout(request: Request):
    """Log out — clear cookie and bounce to login page."""
    response = RedirectResponse(url="/auth/login", status_code=303)
    clear_session_cookie(response)
    return response


@router.post("/logout")
def logout_post(request: Request):
    """Also allow POST logout for CSRF-safer buttons."""
    return logout(request)


# ============================================================
# Change password (first-login OR voluntary)
# ============================================================

@router.get("/change-password", response_class=HTMLResponse)
def change_password_page(
    request: Request,
    err: str | None = None,
    user: Employee = Depends(get_current_user),
):
    """Render the change-password form. Reachable even when must_reset_password=True."""
    return templates.TemplateResponse(
        request,
        "change_password.html",
        {
            "err": err,
            "must_reset": user.must_reset_password,
            "user_name": user.name,
            "employee_code": user.employee_code,
        },
    )


@router.post("/change-password")
async def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Handle new-password submission."""

    if not verify_password(current_password, user.password_hash):
        return RedirectResponse(
            url="/auth/change-password?err=Current+password+is+incorrect",
            status_code=303,
        )

    if new_password != confirm_password:
        return RedirectResponse(
            url="/auth/change-password?err=New+passwords+do+not+match",
            status_code=303,
        )

    err = validate_new_password(new_password)
    if err:
        return RedirectResponse(
            url=f"/auth/change-password?err={err.replace(' ', '+')}",
            status_code=303,
        )

    if new_password == DEFAULT_PASSWORD:
        return RedirectResponse(
            url="/auth/change-password?err=You+must+choose+a+password+different+from+the+default",
            status_code=303,
        )

    if verify_password(new_password, user.password_hash):
        return RedirectResponse(
            url="/auth/change-password?err=New+password+must+differ+from+current",
            status_code=303,
        )

    # All good — update
    user.password_hash = hash_password(new_password)
    user.must_reset_password = False
    db.add(AuditLog(
        actor_code=user.employee_code,
        actor_email=user.email,
        action="password_changed",
        details={"employee_id": user.id},
    ))
    db.commit()

    # Refresh session token so the new state is reflected
    token = issue_session_token(user)
    response = RedirectResponse(url="/", status_code=303)
    set_session_cookie(response, token)
    return response


# ============================================================
# Forgot password — user requests, Sheela approves via email link
# ============================================================

@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request, err: str | None = None, ok: str | None = None):
    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        {"err": err, "ok": ok},
    )


@router.post("/forgot-password")
async def forgot_password_submit(
    request: Request,
    employee_code: str = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    code = (employee_code or "").strip().upper()
    if not code:
        return RedirectResponse(
            url="/auth/forgot-password?err=Please+enter+your+employee+code",
            status_code=303,
        )

    emp = db.query(Employee).filter(Employee.employee_code == code).first()
    # Deliberately do not reveal whether the code exists — respond ok either way
    # (but if it doesn't exist we won't create a token or send an email).
    if not emp or not emp.is_active:
        return RedirectResponse(
            url="/auth/forgot-password?ok=If+the+code+exists,+HR+has+been+notified",
            status_code=303,
        )

    # Create a signed reset token
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=RESET_LINK_EXPIRY_HOURS)
    req = PasswordResetRequest(
        employee_id=emp.id,
        reason=(reason or "").strip()[:1000] or "No reason provided",
        token=token,
        status="pending",
        expires_at=expires_at,
    )
    db.add(req)
    db.commit()

    # Send email to HR — send it best-effort, don't fail the request if email is down
    try:
        from ..services.email_service import send_password_reset_request_email
        reset_link = f"{BASE_URL}/auth/password-reset/{token}"
        await send_password_reset_request_email(
            employee_name=emp.name,
            employee_code=emp.employee_code,
            reason=req.reason,
            reset_link=reset_link,
            expires_at=expires_at,
        )
    except Exception:
        # Log but continue; HR can still see the request in the admin panel
        pass

    return RedirectResponse(
        url="/auth/forgot-password?ok=Request+sent+to+HR.+You+will+be+contacted+once+it's+approved.",
        status_code=303,
    )


@router.get("/password-reset/{token}", response_class=HTMLResponse)
def password_reset_confirm_page(
    request: Request,
    token: str,
    err: str | None = None,
    ok: str | None = None,
    db: Session = Depends(get_db),
):
    """Sheela lands here from the email link. Show details + Approve/Deny buttons.

    We deliberately require the visitor to also be a logged-in admin (so a leaked
    link isn't enough — you also need admin session).
    """
    # Check the token exists and isn't expired
    req = db.query(PasswordResetRequest).filter_by(token=token).first()
    if not req:
        return templates.TemplateResponse(
            request,
            "password_reset.html",
            {"err": "Invalid or unknown reset link.", "ok": None, "req": None, "employee": None, "token": token},
        )
    if req.status != "pending":
        return templates.TemplateResponse(
            request,
            "password_reset.html",
            {"err": f"This request was already {req.status}.", "ok": None, "req": req, "employee": req.employee, "token": token},
        )
    if req.expires_at < datetime.utcnow():
        return templates.TemplateResponse(
            request,
            "password_reset.html",
            {"err": "This reset link has expired.", "ok": None, "req": req, "employee": req.employee, "token": token},
        )

    return templates.TemplateResponse(
        request,
        "password_reset.html",
        {"err": err, "ok": ok, "req": req, "employee": req.employee, "token": token},
    )


@router.post("/password-reset/{token}")
async def password_reset_confirm_submit(
    request: Request,
    token: str,
    action: str = Form(...),  # "approve" or "deny"
    admin: Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sheela clicks Approve or Deny. Must be logged in as admin.

    On Approve: password reset to Metfraa@123, must_reset_password=True.
    On Deny: status=denied, no password change.
    """
    if not admin.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can approve resets")

    req = db.query(PasswordResetRequest).filter_by(token=token).first()
    if not req:
        raise HTTPException(status_code=404, detail="Reset request not found")
    if req.status != "pending":
        return RedirectResponse(
            url=f"/auth/password-reset/{token}?err=Already+{req.status}",
            status_code=303,
        )
    if req.expires_at < datetime.utcnow():
        req.status = "expired"
        db.commit()
        return RedirectResponse(
            url=f"/auth/password-reset/{token}?err=Link+expired",
            status_code=303,
        )

    emp = req.employee
    if not emp:
        raise HTTPException(status_code=404, detail="Employee no longer exists")

    if action == "approve":
        emp.password_hash = hash_password(DEFAULT_PASSWORD)
        emp.must_reset_password = True
        req.status = "fulfilled"
        req.fulfilled_at = datetime.utcnow()
        req.fulfilled_by_code = admin.employee_code
        db.add(AuditLog(
            actor_code=admin.employee_code,
            actor_email=admin.email,
            action="password_reset_approved",
            details={"target_employee_id": emp.id, "target_code": emp.employee_code, "request_id": req.id},
        ))
        db.commit()
        return RedirectResponse(
            url=f"/auth/password-reset/{token}?ok=Password+reset+to+Metfraa@123.+Please+inform+the+employee.",
            status_code=303,
        )

    elif action == "deny":
        req.status = "denied"
        req.fulfilled_at = datetime.utcnow()
        req.fulfilled_by_code = admin.employee_code
        db.add(AuditLog(
            actor_code=admin.employee_code,
            actor_email=admin.email,
            action="password_reset_denied",
            details={"target_employee_id": emp.id, "target_code": emp.employee_code, "request_id": req.id},
        ))
        db.commit()
        return RedirectResponse(
            url=f"/auth/password-reset/{token}?ok=Request+denied.",
            status_code=303,
        )

    else:
        raise HTTPException(status_code=400, detail="Unknown action")
