"""Expense UI parity layer (Slice 1).

Serves the transplanted reference SPA (app/static/expense/) and the JSON
contract it boots against. The source app served these at root; inside the
portal they live under /expense/ because the root namespace is taken.

app.html / app.js / policy-renderer.js / app.css are byte-identical to the
reference apart from a scripted path-prefix rewrite (77 lines, all
reversible). login.html is deliberately not ported — the portal owns auth.

Error bodies are {"error": "..."} (not FastAPI's {"detail": ...}) because
the reference SPA's api() helper reads err.error.
"""
import os
import pathlib

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_optional_user
from ..expense.policy import POLICY
from ..models import Employee, ExpenseEmployeeMeta

router = APIRouter(prefix="/expense", tags=["expense-ui"])

PAGES = pathlib.Path(__file__).resolve().parent.parent / "static" / "expense"


def _err(status: int, message: str, **extra):
    return JSONResponse(status_code=status, content={"error": message, **extra})


def _guard(request: Request, user, db):
    """requireAuth + module access. JSON for /api, redirect for pages."""
    is_api = "/api/" in request.url.path
    if not user:
        if is_api:
            return _err(401, "Not authenticated", authenticated=False)
        return RedirectResponse("/auth/login", status_code=303)
    acc = get_access(db, user)
    if not (acc.expense_access or acc.can_admin_expense or acc.superadmin):
        if is_api:
            return _err(403, "You don't have access to the Expense module")
        return RedirectResponse("/", status_code=303)
    return None


def _is_admin(db: Session, user: Employee) -> bool:
    acc = get_access(db, user)
    return bool(acc.can_admin_expense or acc.superadmin)


def _level_of(db: Session, user: Employee) -> str:
    meta = (db.query(ExpenseEmployeeMeta)
            .filter(ExpenseEmployeeMeta.employee_id == user.id).first())
    return (meta.level if meta and meta.level else "L1")


# ------------------------------------------------------------------ page

@router.get("/", include_in_schema=False)
@router.get("", include_in_schema=False)
def spa(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    f = PAGES / "app.html"
    if not f.is_file():
        return _err(500, "Expense app asset missing from deployment: app.html")
    return FileResponse(f, media_type="text/html")


# ------------------------------------------------------------- bootstrap
# The SPA boots with three calls in order: /api/me, /api/policy/me,
# /api/admin/whoami. All three must answer before anything renders.

@router.get("/api/me")
def api_me(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    """Source shape: { authenticated, user: {...} }.

    The source served this at /auth/me from its own Passport session; here it
    is fed by the portal session. Field names are pinned — the SPA reads
    user.email, user.company and user.level directly.
    """
    if not user:
        return JSONResponse(status_code=401, content={"authenticated": False})
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    return {
        "authenticated": True,
        "user": {
            "name": user.name,
            "email": user.email,
            "company": "metfraa",          # portal is Metfraa-only by scope
            "level": _level_of(db, user),
            "employee_code": user.employee_code,
            "designation": getattr(user, "designation", "") or "",
            "department": getattr(user, "department", "") or "",
            "auth_method": "portal",
            "must_change_pw": bool(getattr(user, "must_reset_password", False)),
        },
    }


@router.get("/api/policy/me")
def api_policy_me(request: Request, user=Depends(get_optional_user),
                  db: Session = Depends(get_db)):
    """Source shape: { policy: {key, name, short, levels, forms}, level }."""
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    return {
        "policy": {
            "key": "metfraa",
            "name": POLICY["name"],
            "short": POLICY["short"],
            "levels": POLICY["levels"],
            "forms": POLICY["forms"],
        },
        "level": _level_of(db, user),
    }


@router.get("/api/admin/whoami")
def api_whoami(request: Request, user=Depends(get_optional_user),
               db: Session = Depends(get_db)):
    """Controls whether the admin panel is reachable in the SPA.

    The source read an ADMIN_EMAILS env var; here it comes from the portal's
    /people roles, matching the decision already taken for EHS.
    """
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    return {"is_admin": _is_admin(db, user)}


# ============================================================================
# Slice 2 — uploads, period lock, projects, submission reads
#
# Forced deviation, flagged in the port spec: the source stored pending bill
# uploads on a mounted disk (pending_uploads.stored_path). Vercel has no
# writable disk, so the bytes go into expense_pending_uploads keyed by the
# SPA's upload_token and move to OneDrive when the form is submitted. The
# JSON the SPA sees is unchanged.
# ============================================================================

import calendar as _cal
import re as _re
from datetime import datetime as _dt, timedelta as _td

from fastapi import File, Form, UploadFile  # noqa: E402
from sqlalchemy import or_  # noqa: E402

from ..models import (  # noqa: E402
    ExpenseAttachment, ExpensePendingUpload, ExpensePeriodOverride,
    ExpenseProject, ExpenseSubmission,
)

IST = _td(hours=5, minutes=30)
UPLOAD_MAX_MB = int(os.getenv("UPLOAD_MAX_MB", "10"))

# One-off transition cutoff carried over verbatim from period-lock.js.
# July 2026 was extended to 1 Aug 2026 23:59:59 IST (= 18:29:59 UTC).
SPECIAL_CUTOFFS = {"2026-07": _dt(2026, 8, 1, 18, 29, 59)}


def _cutoff_utc(period: str):
    """The instant a period locks, in UTC. 23:59:59 IST on its last day."""
    if not _re.match(r"^\d{4}-\d{2}$", period or ""):
        return None
    if period in SPECIAL_CUTOFFS:
        return SPECIAL_CUTOFFS[period]
    y, mo = int(period[:4]), int(period[5:7])
    last = _cal.monthrange(y, mo)[1]
    return _dt(y, mo, last, 18, 29, 59)


def _deadline_label(period: str) -> str:
    c = _cutoff_utc(period)
    if not c:
        return "(unknown)"
    ist = c + IST
    return f"{ist.strftime('%d %b %Y')} {ist.strftime('%I:%M %p').lstrip('0')} IST"


def _calendar_locked(period: str) -> bool:
    c = _cutoff_utc(period)
    return bool(c and _dt.utcnow() > c)


def _active_override(db: Session, period: str, employee_id: int):
    """Global (employee_id NULL) or personal, unexpired, unrevoked."""
    now = _dt.utcnow().isoformat()
    return (db.query(ExpensePeriodOverride)
            .filter(ExpensePeriodOverride.period == period,
                    ExpensePeriodOverride.revoked_at.is_(None),
                    ExpensePeriodOverride.expires_at > now,
                    or_(ExpensePeriodOverride.employee_id == employee_id,
                        ExpensePeriodOverride.employee_id.is_(None)))
            .order_by(ExpensePeriodOverride.employee_id.isnot(None).desc())
            .first())


def check_period(db: Session, period: str, employee_id: int, deadline_bypass=False) -> dict:
    """Port of period-lock.js checkPeriod. Same return keys."""
    if not period:
        return {"allowed": True, "no_period": True}
    if not _calendar_locked(period):
        return {"allowed": True}
    if deadline_bypass:
        return {"allowed": True, "via_bypass": True}
    o = _active_override(db, period, employee_id)
    if o:
        return {"allowed": True, "via_override": {
            "id": o.id,
            "scope": "global" if o.employee_id is None else "employee",
            "granted_by": o.granted_by, "granted_at": o.granted_at,
            "expires_at": o.expires_at, "reason": o.reason}}
    dl = _deadline_label(period)
    return {"allowed": False, "deadline": dl,
            "message": f"{period} is closed for new submissions (the deadline was {dl}). "
                       "Please contact HR to request a temporary override."}


@router.get("/api/submissions/period-lock/status")
def api_period_lock_status(request: Request, period: str = "",
                           user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    period = (period or "").strip()
    lock = check_period(db, period, user.id)
    cal_locked = _calendar_locked(period)
    return {
        "period": period,
        "allowed": bool(lock.get("allowed")),
        "calendar_locked": bool(cal_locked),
        "via_override": lock.get("via_override"),
        "deadline": _deadline_label(period) if cal_locked else None,
        "message": None if lock.get("allowed") else lock.get("message"),
    }


# ----------------------------------------------------------------- uploads

@router.post("/api/uploads")
async def api_upload(request: Request, upload_token: str = Form(""),
                     row_idx: str = Form(""), files: list[UploadFile] = File(default=[]),
                     user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    token = (upload_token or "").strip()
    if not token:
        return _err(400, "upload_token required")
    if not files:
        return _err(400, "No files received")

    idx = None
    if row_idx not in ("", None):
        try:
            n = int(row_idx)
            if 0 <= n < 1000:
                idx = n
        except ValueError:
            idx = None

    records = []
    for f in files[:20]:
        data = await f.read()
        if len(data) > UPLOAD_MAX_MB * 1024 * 1024:
            return _err(413, f"File too large. Max {UPLOAD_MAX_MB} MB per file.")
        row = ExpensePendingUpload(
            upload_token=token, employee_id=user.id, filename=f.filename or "bill",
            mime_type=f.content_type or "application/octet-stream",
            size_bytes=len(data), row_idx=idx, content=data)
        db.add(row)
        db.flush()
        records.append({"id": row.id, "filename": row.filename,
                        "mime_type": row.mime_type, "size_bytes": row.size_bytes,
                        "row_idx": row.row_idx})
    db.commit()
    return {"ok": True, "uploads": records}


@router.get("/api/uploads/{token}")
def api_uploads_list(token: str, request: Request,
                     user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    rows = (db.query(ExpensePendingUpload)
            .filter(ExpensePendingUpload.upload_token == token,
                    ExpensePendingUpload.employee_id == user.id)
            .order_by(ExpensePendingUpload.id).all())
    return {"uploads": [{"id": r.id, "filename": r.filename,
                         "mime_type": r.mime_type, "size_bytes": r.size_bytes}
                        for r in rows]}


@router.delete("/api/uploads/{upload_id}")
def api_upload_delete(upload_id: int, request: Request, token: str = "",
                      user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    row = (db.query(ExpensePendingUpload)
           .filter(ExpensePendingUpload.id == upload_id,
                   ExpensePendingUpload.upload_token == (token or ""),
                   ExpensePendingUpload.employee_id == user.id).first())
    if not row:
        return _err(404, "Not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- projects

@router.get("/api/projects")
def api_projects_list(request: Request, user=Depends(get_optional_user),
                      db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    rows = (db.query(ExpenseProject).filter(ExpenseProject.is_active == True)  # noqa: E712
            .order_by(ExpenseProject.name).all())
    return {"projects": [{"id": p.id, "code": p.code, "name": p.name,
                          "is_active": 1 if p.is_active else 0} for p in rows]}


# ------------------------------------------------------- submission reads

def _sub_row(s: ExpenseSubmission) -> dict:
    return {
        "id": s.id, "reference": s.reference, "company": "metfraa",
        "form_type": s.form_type, "period": s.period,
        "total_amount": s.total_amount, "status": s.status,
        "advance_stage": s.advance_stage,
        "submitted_at": s.submitted_at_ist,
        "reviewed_by": s.reviewed_by, "reviewed_at": s.reviewed_at_ist,
        "review_note": s.review_note,
        "changes_required": s.changes_required, "returned_at": s.returned_at_ist,
        "settled_at": s.settled_at_ist,
        "differential_amount": s.differential_amount,
    }


@router.get("/api/submissions")
def api_submissions(request: Request, user=Depends(get_optional_user),
                    db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    rows = (db.query(ExpenseSubmission)
            .filter(ExpenseSubmission.employee_id == user.id)
            .order_by(ExpenseSubmission.submitted_at_ist.desc()).all())
    return {"submissions": [_sub_row(s) for s in rows]}


@router.get("/api/submissions/open-advances")
def api_open_advances(request: Request, user=Depends(get_optional_user),
                      db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    rows = (db.query(ExpenseSubmission)
            .filter(ExpenseSubmission.employee_id == user.id,
                    ExpenseSubmission.form_type == "met_advance",
                    ExpenseSubmission.status.in_(["advance_approved", "settlement_rejected"]))
            .order_by(ExpenseSubmission.submitted_at_ist.desc()).all())
    out = []
    for s in rows:
        d = _sub_row(s)
        d["payload"] = s.payload or {}
        out.append(d)
    return {"advances": out}


@router.get("/api/submissions/{sub_id}")
def api_submission_detail(sub_id: int, request: Request,
                          user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    s = db.query(ExpenseSubmission).filter(ExpenseSubmission.id == sub_id).first()
    if not s:
        return _err(404, "Not found")
    if s.employee_id != user.id and not _is_admin(db, user):
        return _err(403, "Forbidden")

    project = None
    pid = (s.payload or {}).get("project_id")
    if pid:
        p = db.query(ExpenseProject).filter(ExpenseProject.id == pid).first()
        if p:
            project = {"id": p.id, "code": p.code, "name": p.name}

    # DTR rows reference projects per entry; resolve them up front so the
    # popup doesn't need one call per row (source behaviour).
    dtr_lookup = None
    if s.form_type == "met_dtr":
        dtr_lookup = {}
        for e in (s.payload or {}).get("entries", []) or []:
            epid = (e or {}).get("project_id")
            if epid and epid not in dtr_lookup:
                p = db.query(ExpenseProject).filter(ExpenseProject.id == epid).first()
                if p:
                    dtr_lookup[str(epid)] = {"id": p.id, "code": p.code, "name": p.name}

    atts = (db.query(ExpenseAttachment)
            .filter(ExpenseAttachment.submission_id == s.id)
            .order_by(ExpenseAttachment.id).all())

    return {"submission": {
        **_sub_row(s),
        "email_sent_at": None,
        "purpose_category": s.purpose_category,
        "purpose_other_reason": s.purpose_other_reason,
        "project": project,
        "client_name": (s.payload or {}).get("client_name"),
        "dtr_project_lookup": dtr_lookup,
        "actuals": s.actuals,
        "settlement_reviewed_by": s.settlement_reviewed_by,
        "settlement_reviewed_at": s.settled_at_ist,
        "settlement_note": s.settlement_note,
        "trip_end_date": s.trip_end_date,
        "late_settlement": bool(s.late_settlement),
        "late_hours": s.late_hours,
        "payload": s.payload or {},
        "employee": {
            "name": s.employee_name, "email": s.employee_email,
            "code": getattr(s.employee, "employee_code", None) if s.employee else None,
            "designation": getattr(s.employee, "designation", None) if s.employee else None,
            "department": getattr(s.employee, "department", None) if s.employee else None,
            "level": s.employee_level,
        },
        "attachments": [{"id": a.id, "filename": a.filename, "mime_type": a.mime_type,
                         "size_bytes": a.size_bytes, "category": a.label,
                         "row_idx": a.row_idx} for a in atts],
    }}
