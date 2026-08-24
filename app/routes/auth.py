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
from ..models import AuditLog, Employee, PasswordOtp, PasswordResetRequest

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


DEFAULT_PASSWORD = "Metfraa@123"
RESET_LINK_EXPIRY_HOURS = 24
BASE_URL = os.getenv("BASE_URL", "https://kpis.metfraa.com").rstrip("/")

# --- self-service OTP reset tunables ---
OTP_EXPIRY_MIN = int(os.getenv("OTP_EXPIRY_MIN", "10"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
OTP_RESEND_COOLDOWN_SEC = int(os.getenv("OTP_RESEND_COOLDOWN_SEC", "30"))
RESET_TOKEN_EXPIRY_MIN = int(os.getenv("OTP_RESET_TOKEN_EXPIRY_MIN", "15"))


def _mask_phone(raw) -> str:
    """Show only the last 4 digits so the user recognises their own number
    without it being fully disclosed on screen."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) < 4:
        return "your registered mobile"
    return "••• ••• " + digits[-4:]


def _gen_otp() -> str:
    return f"{secrets.randbelow(10 ** 6):06d}"


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


# ============================================================
# Self-service password reset over WhatsApp OTP
#
#   /auth/reset            enter employee code
#   POST /auth/reset/send  → WhatsApp a 6-digit code to the on-file mobile
#   POST /auth/reset/verify→ check the code, mint a short-lived reset token
#   POST /auth/reset/set   → set the new password, log in
#
# The code is stored hashed; a reset_token bridges verify→set so the final
# POST can't be forged. No HR approval needed — proving control of the
# registered mobile is the authorisation.
# ============================================================

def _render_reset(request, stage, *, err=None, ok=None, flow=None,
                  masked=None, reset_token=None, attempts_left=None):
    return templates.TemplateResponse(request, "password_otp.html", {
        "stage": stage, "err": err, "ok": ok, "flow": flow or "",
        "masked": masked or "", "reset_token": reset_token or "",
        "attempts_left": attempts_left,
    })


@router.get("/reset", response_class=HTMLResponse)
def reset_start_page(request: Request, err: str | None = None):
    return _render_reset(request, "code", err=err)


@router.post("/reset/send")
async def reset_send_otp(
    request: Request,
    employee_code: str = Form(...),
    db: Session = Depends(get_db),
):
    code = (employee_code or "").strip().upper()
    if not code:
        return _render_reset(request, "code", err="Please enter your employee code.")

    emp = db.query(Employee).filter(Employee.employee_code == code).first()
    if not emp or not emp.is_active:
        return _render_reset(request, "code",
                             err="No active account found for that code. Check the code or contact HR.")

    from ..services import wati
    phone = wati.normalize_phone(emp.phone)
    if not phone:
        return _render_reset(request, "code",
                             err="No mobile number is on file for your account. Please contact HR to reset your password.")

    # Resend cooldown — don't let a button-masher fan out a burst of codes.
    last = (db.query(PasswordOtp)
            .filter(PasswordOtp.employee_id == emp.id,
                    PasswordOtp.consumed_at.is_(None))
            .order_by(PasswordOtp.id.desc()).first())
    if last and last.created_at and \
            (datetime.utcnow() - last.created_at).total_seconds() < OTP_RESEND_COOLDOWN_SEC:
        wait = OTP_RESEND_COOLDOWN_SEC - int((datetime.utcnow() - last.created_at).total_seconds())
        return _render_reset(request, "otp", flow=last.flow_token,
                             masked=_mask_phone(emp.phone),
                             err=f"A code was just sent. Please wait {wait}s before requesting another.")

    otp = _gen_otp()
    row = PasswordOtp(
        employee_id=emp.id,
        flow_token=secrets.token_urlsafe(32),
        code_hash=hash_password(otp),
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MIN),
        attempts=0,
    )
    db.add(row)
    db.commit()

    ok = wati.password_otp(emp.phone, otp, db)
    db.add(AuditLog(actor_code=emp.employee_code, actor_email=emp.email,
                    action="password_otp_sent",
                    details={"employee_id": emp.id, "delivered": bool(ok)}))
    db.commit()

    if not ok:
        return _render_reset(request, "code",
                             err="We couldn't send a WhatsApp code to your number right now. "
                                 "Please try again shortly, or contact HR.")

    return _render_reset(request, "otp", flow=row.flow_token,
                         masked=_mask_phone(emp.phone),
                         ok=f"A 6-digit code was sent to {_mask_phone(emp.phone)} on WhatsApp.")


@router.post("/reset/resend")
async def reset_resend_otp(
    request: Request,
    flow: str = Form(...),
    db: Session = Depends(get_db),
):
    row = db.query(PasswordOtp).filter_by(flow_token=flow).first()
    if not row or row.consumed_at:
        return _render_reset(request, "code", err="That reset session has expired. Please start again.")
    emp = row.employee
    if not emp or not emp.is_active:
        return _render_reset(request, "code", err="Account unavailable. Please contact HR.")
    # Reuse the send path's cooldown + issue logic by delegating.
    return await reset_send_otp(request, employee_code=emp.employee_code, db=db)


@router.post("/reset/verify")
async def reset_verify_otp(
    request: Request,
    flow: str = Form(...),
    otp: str = Form(...),
    db: Session = Depends(get_db),
):
    row = db.query(PasswordOtp).filter_by(flow_token=flow).first()
    if not row or row.consumed_at:
        return _render_reset(request, "code", err="That reset session has expired. Please start again.")

    masked = _mask_phone(row.employee.phone if row.employee else None)

    if row.expires_at < datetime.utcnow():
        return _render_reset(request, "code",
                             err="Your code has expired. Please request a new one.")

    if row.attempts >= OTP_MAX_ATTEMPTS:
        return _render_reset(request, "code",
                             err="Too many incorrect attempts. Please request a new code.")

    entered = re.sub(r"\D", "", otp or "")
    if not verify_password(entered, row.code_hash):
        row.attempts += 1
        db.commit()
        left = max(0, OTP_MAX_ATTEMPTS - row.attempts)
        if left == 0:
            return _render_reset(request, "code",
                                 err="Too many incorrect attempts. Please request a new code.")
        return _render_reset(request, "otp", flow=flow, masked=masked,
                             err="Incorrect code. Please try again.", attempts_left=left)

    # Correct — mint a short-lived reset token for the set-password step.
    row.verified_at = datetime.utcnow()
    row.reset_token = secrets.token_urlsafe(32)
    row.reset_expires_at = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRY_MIN)
    db.commit()
    return _render_reset(request, "password", reset_token=row.reset_token)


@router.post("/reset/set")
async def reset_set_password(
    request: Request,
    reset_token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    row = db.query(PasswordOtp).filter_by(reset_token=reset_token).first()
    if not row or row.consumed_at or not row.reset_expires_at:
        return _render_reset(request, "code", err="That reset session is no longer valid. Please start again.")
    if row.reset_expires_at < datetime.utcnow():
        return _render_reset(request, "code", err="Your reset window expired. Please start again.")

    emp = row.employee
    if not emp or not emp.is_active:
        return _render_reset(request, "code", err="Account unavailable. Please contact HR.")

    if new_password != confirm_password:
        return _render_reset(request, "password", reset_token=reset_token,
                             err="The two passwords do not match.")
    perr = validate_new_password(new_password)
    if perr:
        return _render_reset(request, "password", reset_token=reset_token, err=perr)
    if new_password == DEFAULT_PASSWORD:
        return _render_reset(request, "password", reset_token=reset_token,
                             err="Please choose a password different from the default.")

    emp.password_hash = hash_password(new_password)
    emp.must_reset_password = False
    row.consumed_at = datetime.utcnow()
    db.add(AuditLog(actor_code=emp.employee_code, actor_email=emp.email,
                    action="password_reset_via_otp",
                    details={"employee_id": emp.id}))
    db.commit()

    # Log them straight in — they've proven the mobile and set a fresh password.
    token = issue_session_token(emp)
    response = RedirectResponse(url="/", status_code=303)
    set_session_cookie(response, token)
    return response
