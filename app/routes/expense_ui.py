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


# ============================================================================
# Slice 3 — the write path
#
#   POST   /api/submissions                    create
#   PATCH  /api/submissions/{id}               edit a returned draft + resubmit
#   POST   /api/submissions/{id}/clone-attachments
#   POST   /api/submissions/{id}/settle        file an advance settlement
#   GET    /api/submissions/{id}/attachment/{att_id}
#
# The SPA posts JSON with an upload_token; the portal's own submit route
# takes multipart with inline files. Rather than fork the OneDrive/PDF
# machinery, this claims the pending uploads and reuses the same helpers.
# ============================================================================

import json as _json  # noqa: E402
import random as _random  # noqa: E402
import string as _string  # noqa: E402

from ..expense.policy import FORM_META  # noqa: E402
from ..expense.validators import validate as _validate  # noqa: E402
from ..services import onedrive as _od  # noqa: E402

DTR = "met_dtr"


def _reference(code: str) -> str:
    d = (_dt.utcnow() + IST).strftime("%y%m%d")
    tail = "".join(_random.choices(_string.ascii_uppercase + _string.digits, k=4))
    return f"MET-{code}-{d}-{tail}"


def _ist_now() -> str:
    return (_dt.utcnow() + IST).strftime("%Y-%m-%d %H:%M:%S")


def _pending_for(db: Session, token: str, employee_id: int):
    if not token:
        return []
    return (db.query(ExpensePendingUpload)
            .filter(ExpensePendingUpload.upload_token == token,
                    ExpensePendingUpload.employee_id == employee_id)
            .order_by(ExpensePendingUpload.id).all())


def _prepare_raw(form_type: str, raw: dict) -> dict:
    """DTR validator requires has_bill per entry; the multipart route derives
    it from the uploaded files, the SPA signals it via bill_pending_id."""
    if form_type == DTR:
        for e in (raw.get("entries") or []):
            if isinstance(e, dict):
                e["has_bill"] = e.get("bill_pending_id") is not None
    return raw


def _resolve_attachments(form_type: str, raw: dict, pending: list):
    """Port of the source's attachment-collection branch.

    Non-DTR: every pending upload becomes a form-level attachment.
    DTR: only uploads referenced by an entry's bill_pending_id, stamped with
    row_idx, each usable exactly once.

    Read from the RAW payload, not the validated one — the validators strip
    bill_pending_id (it is a client-side handle, never persisted). Raw and
    validated entries stay index-aligned, so row_idx is valid for both.
    Returns (specs, error).
    """
    if form_type != DTR:
        return [{"pending": p, "category": "general", "label": "", "row_idx": None}
                for p in pending], None

    by_id = {p.id: p for p in pending}
    claimed, specs = set(), []
    entries = raw.get("entries") if isinstance(raw.get("entries"), list) else []
    for i, e in enumerate(entries):
        bill_id = (e or {}).get("bill_pending_id")
        if bill_id is None:
            continue
        p = by_id.get(bill_id)
        if not p:
            return None, (f"Entry #{i + 1} references a bill that wasn't "
                          "uploaded under this submission.")
        if bill_id in claimed:
            return None, (f"Entry #{i + 1} references a bill already used by "
                          "another entry — upload a separate file.")
        claimed.add(bill_id)
        specs.append({"pending": p, "category": "dtr_bill",
                      "label": f"Entry {i + 1}", "row_idx": i})
    return specs, None


def _store_attachments(db: Session, sub: ExpenseSubmission, specs: list):
    """Move claimed pending uploads into OneDrive and link them."""
    from ..routes.expense import _artifacts, _compress
    folder = f"{_artifacts().submission_folder(sub)}/Bills"
    n = 0
    for spec in specs:
        p = spec["pending"]
        data, mime = _compress(p.content, p.mime_type)
        ext = ".jpg" if mime == "image/jpeg" else (
            "." + (p.filename.rsplit(".", 1)[-1] if "." in p.filename else "bin"))
        n += 1
        stem = f"row{spec['row_idx']}" if spec["row_idx"] is not None else "bill"
        path = f"{folder}/{stem}_{n}{ext}"
        info = _od.upload_to_path(data, path, mime)
        db.add(ExpenseAttachment(
            submission_id=sub.id, filename=p.filename, onedrive_path=path,
            web_url=(info or {}).get("webUrl"), mime_type=mime,
            size_bytes=len(data), row_idx=spec["row_idx"], label=spec["label"] or spec["category"]))


def _meta_from_payload(payload: dict, raw: dict | None = None) -> dict:
    """The source's validator surfaced these on v.meta so they land in
    first-class columns instead of being buried in the JSON payload."""
    raw = raw or {}

    def pick(k):
        v = payload.get(k)
        return v if v not in (None, "") else raw.get(k)

    return {"purpose_category": pick("purpose_category"),
            "purpose_other_reason": pick("purpose_other_reason"),
            "project_id": pick("project_id"),
            "client_name": pick("client_name")}


def _check_project(db: Session, project_id):
    """Defence in depth — the SPA filters to active projects, the API must not trust it."""
    if project_id is None:
        return None
    p = db.query(ExpenseProject).filter(ExpenseProject.id == project_id).first()
    if not p or not p.is_active:
        return "Selected project is not valid. Please pick from the active list."
    return None


@router.post("/api/submissions")
async def api_submission_create(request: Request, user=Depends(get_optional_user),
                                db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    body = await request.json()
    form_type = (body or {}).get("form_type")
    if not form_type:
        return _err(400, "form_type required")
    meta = FORM_META.get(form_type)
    if not meta:
        return _err(400, "Unknown form type")

    raw = _prepare_raw(form_type, (body or {}).get("payload") or {})
    ok, payload_or_err, total = _validate(form_type, raw, _level_of(db, user))
    if not ok:
        return _err(400, payload_or_err)
    payload = payload_or_err

    token = ((body or {}).get("upload_token") or "").strip()
    pending = _pending_for(db, token, user.id)
    specs, perr = _resolve_attachments(form_type, raw, pending)
    if perr:
        return _err(400, perr)

    period = payload.get("period")
    lock = check_period(db, period, user.id)
    if not lock.get("allowed"):
        return JSONResponse(status_code=423, content={
            "error": lock.get("message"), "deadline": lock.get("deadline"),
            "period_locked": True})

    m = _meta_from_payload(payload, raw)
    proj_err = _check_project(db, m["project_id"])
    if proj_err:
        return _err(400, proj_err)

    sub = ExpenseSubmission(
        reference=_reference(meta["code"]), employee_id=user.id,
        employee_name=user.name, employee_email=user.email,
        employee_level=_level_of(db, user), form_type=form_type, period=period,
        payload=payload, total_amount=total, status="pending",
        purpose_category=m["purpose_category"],
        purpose_other_reason=m["purpose_other_reason"],
        submitted_at_ist=_ist_now())
    db.add(sub)
    db.flush()

    try:
        _store_attachments(db, sub, specs)
    except Exception as e:
        db.rollback()
        return _err(502, f"Bill upload to OneDrive failed — please retry ({e})")

    for p in pending:
        db.delete(p)
    db.commit()

    return {"ok": True, "submission": {
        "id": sub.id, "reference": sub.reference, "total": total,
        "status": "pending", "od_synced": True, "pdf_url": None,
        "message": "Submitted for approval. You will be notified once an admin reviews it."}}


@router.patch("/api/submissions/{sub_id}")
async def api_submission_edit(sub_id: int, request: Request,
                              user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    sub = db.query(ExpenseSubmission).filter(ExpenseSubmission.id == sub_id).first()
    if not sub:
        return _err(404, "Submission not found.")
    if sub.employee_id != user.id:
        return _err(403, "You can only edit your own submissions.")
    if sub.status != "draft":
        return _err(400, "This submission is already awaiting review and cannot be edited."
                    if sub.status == "pending"
                    else f"Submissions in status '{sub.status}' cannot be edited.")

    body = await request.json()
    form_type = (body or {}).get("form_type")
    if not form_type:
        return _err(400, "form_type required")
    if form_type != sub.form_type:
        return _err(400, "Cannot change the form type on a resubmit.")
    meta = FORM_META.get(form_type)
    if not meta:
        return _err(400, "Unknown form type")

    raw = _prepare_raw(form_type, (body or {}).get("payload") or {})
    ok, payload_or_err, total = _validate(form_type, raw, _level_of(db, user))
    if not ok:
        return _err(400, payload_or_err)
    payload = payload_or_err

    token = ((body or {}).get("upload_token") or "").strip()
    pending = _pending_for(db, token, user.id)
    specs, perr = _resolve_attachments(form_type, raw, pending)
    if perr:
        return _err(400, perr)

    period = payload.get("period")
    lock = check_period(db, period, user.id, deadline_bypass=bool(sub.deadline_bypass))
    if not lock.get("allowed"):
        return JSONResponse(status_code=423, content={
            "error": lock.get("message"), "deadline": lock.get("deadline"),
            "period_locked": True})

    m = _meta_from_payload(payload, raw)
    proj_err = _check_project(db, m["project_id"])
    if proj_err:
        return _err(400, proj_err)

    # Attachments are replaced wholesale — the edit screen re-presents the
    # existing ones via clone-attachments, so `pending` is the full new set.
    for a in db.query(ExpenseAttachment).filter(
            ExpenseAttachment.submission_id == sub.id).all():
        db.delete(a)
    db.flush()

    sub.payload = payload
    sub.total_amount = total
    sub.period = period
    sub.status = "pending"
    sub.purpose_category = m["purpose_category"]
    sub.purpose_other_reason = m["purpose_other_reason"]
    sub.changes_required = None
    sub.returned_at_ist = None
    sub.submitted_at_ist = _ist_now()

    try:
        _store_attachments(db, sub, specs)
    except Exception as e:
        db.rollback()
        return _err(502, f"Bill upload to OneDrive failed — please retry ({e})")

    for p in pending:
        db.delete(p)
    db.commit()

    return {"ok": True, "submission": {
        "id": sub.id, "reference": sub.reference, "total": total,
        "status": "pending", "od_synced": True, "pdf_url": None,
        "message": "Resubmitted for approval."}}


@router.post("/api/submissions/{sub_id}/clone-attachments")
async def api_clone_attachments(sub_id: int, request: Request,
                                user=Depends(get_optional_user), db: Session = Depends(get_db)):
    """Copy an existing submission's bills into the pending pool under a
    fresh token, so the edit screen can show them with remove buttons."""
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    sub = db.query(ExpenseSubmission).filter(ExpenseSubmission.id == sub_id).first()
    if not sub:
        return _err(404, "Submission not found.")
    if sub.employee_id != user.id:
        return _err(403, "Forbidden.")
    if sub.status != "draft":
        return _err(400, f"Cannot clone attachments from '{sub.status}' status.")
    body = await request.json()
    token = ((body or {}).get("upload_token") or "").strip()
    if not token:
        return _err(400, "upload_token required")

    cloned = []
    for a in (db.query(ExpenseAttachment)
              .filter(ExpenseAttachment.submission_id == sub.id)
              .order_by(ExpenseAttachment.id).all()):
        data = None
        try:
            data = _od.download_from_path(a.onedrive_path)
        except Exception:
            data = None
        if data is None:
            # The bill is unreachable; skip rather than fail the whole edit.
            continue
        row = ExpensePendingUpload(
            upload_token=token, employee_id=user.id, filename=a.filename,
            mime_type=a.mime_type, size_bytes=a.size_bytes,
            row_idx=a.row_idx, content=data)
        db.add(row)
        db.flush()
        cloned.append({"id": row.id, "original_attachment_id": a.id,
                       "filename": a.filename, "mime_type": a.mime_type,
                       "size_bytes": a.size_bytes, "row_idx": a.row_idx})
    db.commit()
    return {"ok": True, "uploads": cloned}


@router.post("/api/submissions/{sub_id}/settle")
async def api_settle(sub_id: int, request: Request,
                     user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    sub = db.query(ExpenseSubmission).filter(ExpenseSubmission.id == sub_id).first()
    if not sub:
        return _err(404, "Submission not found.")
    if sub.employee_id != user.id:
        return _err(403, "Not your submission.")
    if sub.form_type != "met_advance":
        return _err(400, "Only Travel Advance submissions can be settled.")
    if sub.status not in ("advance_approved", "settlement_rejected"):
        return _err(400, f"Cannot settle from status '{sub.status}'.")

    body = await request.json()
    token = ((body or {}).get("upload_token") or "").strip()
    actuals = (body or {}).get("actuals") or {}
    trip_end = (body or {}).get("trip_end_date")

    # 72-hour rule: soft flag only, never a hard block.
    trip_end_date, late, late_hours = None, False, None
    if trip_end and _re.match(r"^\d{4}-\d{2}-\d{2}$", str(trip_end)):
        trip_end_date = str(trip_end)
        y, mo, d = (int(x) for x in trip_end_date.split("-"))
        deadline = _dt(y, mo, d, 18, 29, 0) + _td(hours=72)   # 23:59 IST + 72h
        now = _dt.utcnow()
        if now > deadline:
            late = True
            late_hours = round((now - deadline).total_seconds() / 3600.0, 1)

    pending = _pending_for(db, token, user.id)
    if not pending:
        return _err(400, "At least one bill is required to settle the advance.")

    specs = [{"pending": p, "category": "settlement", "label": "Settlement bill",
              "row_idx": None} for p in pending]
    try:
        _store_attachments(db, sub, specs)
    except Exception as e:
        db.rollback()
        return _err(502, f"Bill upload to OneDrive failed — please retry ({e})")

    sub.actuals = actuals
    sub.trip_end_date = trip_end_date
    sub.late_settlement = late
    sub.late_hours = late_hours
    sub.status = "settlement_pending"
    sub.settled_at_ist = _ist_now()
    for p in pending:
        db.delete(p)
    db.commit()

    return {"ok": True, "submission": {
        "id": sub.id, "reference": sub.reference, "status": "settlement_pending",
        "late_settlement": late, "late_hours": late_hours,
        "message": "Settlement filed — awaiting review."}}


@router.get("/api/submissions/{sub_id}/attachment/{att_id}")
def api_attachment(sub_id: int, att_id: int, request: Request,
                   user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    sub = db.query(ExpenseSubmission).filter(ExpenseSubmission.id == sub_id).first()
    if not sub:
        return _err(404, "Not found")
    if sub.employee_id != user.id and not _is_admin(db, user):
        return _err(403, "Forbidden")
    a = (db.query(ExpenseAttachment)
         .filter(ExpenseAttachment.id == att_id,
                 ExpenseAttachment.submission_id == sub.id).first())
    if not a:
        return _err(404, "Not found")
    data = _od.download_from_path(a.onedrive_path)
    if data is None:
        return _err(404, "File not found in OneDrive")
    from fastapi.responses import Response as _Resp
    return _Resp(content=data, media_type=a.mime_type or "application/octet-stream",
                 headers={"Content-Disposition": f'inline; filename="{a.filename}"',
                          "Cache-Control": "private, max-age=3600"})
