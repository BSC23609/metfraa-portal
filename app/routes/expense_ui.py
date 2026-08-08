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

from fastapi import APIRouter, Depends, HTTPException, Request
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


def _as_int(v):
    """Coerce a payload id to int, or None if it isn't one.

    The SPA's <select> elements yield STRINGS, and an unchosen dropdown yields
    "". SQLite silently tolerates `WHERE int_col = ''`; Postgres raises
    InvalidTextRepresentation and the whole request 500s. Every payload id that
    reaches an integer column must come through here.
    """
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
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

from fastapi import BackgroundTasks  # noqa: E402
from ..models import (  # noqa: E402
    ExpenseAttachment, ExpenseConsolidatedReport, ExpensePendingUpload,
    ExpensePeriodOverride, ExpenseProject, ExpenseSubmission,
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
    pid = _as_int((s.payload or {}).get("project_id"))
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
            epid = _as_int((e or {}).get("project_id"))
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
from ..services.portal_notify import (  # noqa: E402
    notify_advance_stage, notify_consolidated_for_review,
    notify_consolidated_rejected, notify_consolidated_to_accounts,
    notify_expense_decision, notify_payment_marked,
)

log = __import__("logging").getLogger(__name__)

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
        entries = raw.get("entries")
        if entries is not None and not isinstance(entries, list):
            raise ValueError("entries must be a list")
        for e in (entries or []):
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
            "project_id": _as_int(pick("project_id")),
            "client_name": pick("client_name")}


def _check_project(db: Session, project_id):
    """Defence in depth — the SPA filters to active projects, the API must not trust it."""
    project_id = _as_int(project_id)
    if project_id is None:
        return None          # nothing selected — not an error
    p = db.query(ExpenseProject).filter(ExpenseProject.id == project_id).first()
    if not p or not p.is_active:
        return "Selected project is not valid. Please pick from the active list."
    return None


def _fail(where: str, form_type: str, user, exc: Exception):
    """Log the full traceback with enough context to find the row, and hand the
    user something they can quote back to us."""
    import traceback
    import uuid
    ref = uuid.uuid4().hex[:8]
    log.error("[expense-%s] ref=%s form=%s user=%s\n%s", where, ref, form_type,
              getattr(user, "employee_code", "?"), traceback.format_exc())
    return _err(500, "Something went wrong saving this claim. Nothing was saved — "
                     f"please try again. If it keeps happening quote reference {ref}.",
                ref=ref)


@router.post("/api/submissions")
async def api_submission_create(request: Request, user=Depends(get_optional_user),
                                db: Session = Depends(get_db)):
    try:
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
    except ValueError as e:
        return _err(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return _fail("create", form_type if "form_type" in locals() else "?", user, e)

@router.patch("/api/submissions/{sub_id}")
async def api_submission_edit(sub_id: int, request: Request,
                              user=Depends(get_optional_user), db: Session = Depends(get_db)):
    try:
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
    except ValueError as e:
        return _err(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return _fail("edit", form_type if "form_type" in locals() else "?", user, e)

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


# ============================================================================
# Slice 4 — admin review surface
#
# The 12 action verbs plus the pending queue and the admin submissions list.
# Status transitions are copied one-for-one from the source's prepared
# statements (server/db/index.js) — including the guard each one enforces on
# the *current* status, which is what stops a claim being paid twice.
#
#   Travel Advance chain:
#     pending --approve-->        advance_hr_verified   (stage mgmt_review)
#     --advance-mgmt-approve-->   advance_mgmt_approved (stage accounts_pay)
#     --advance-mark-paid-->      advance_approved      (stage paid, open)
#     --employee settles-->       settlement_pending
#     --approve-settlement-->     settled (differential = actual - advance)
#     --reject-settlement-->      settlement_rejected (employee may re-file)
# ============================================================================

REVIEW_STATES = ["pending", "advance_hr_verified", "advance_mgmt_approved",
                 "settlement_pending"]

# ============================================================================
# Slice 7 — side effects: PDF artifacts + email notifications
#
# The status transitions in slices 4-6 were deliberately silent. This wires
# in what the source fires alongside them:
#   approve (regular)   -> claim PDF to OneDrive + master-log row + employee email
#   advance chain       -> Management / Accounts / employee emails per stage
#   settlement decided  -> settled PDF + log + employee email
#   payment marked      -> employee email, error recorded but never blocking
#   consolidated        -> Arasu on send, Accounts on approve, employee on reject
#
# Every side effect is fail-soft: a Graph or SMTP outage must not roll back a
# status the reviewer has already committed to.
# ============================================================================

def _artifact_for(db: Session, sub: ExpenseSubmission) -> str | None:
    """Generate the claim PDF, push it to OneDrive, append the master-log row.

    Returns the OneDrive web URL, or None if anything failed (logged, never raised).
    """
    try:
        from ..routes.expense import _artifacts
        art = _artifacts()
        meta = FORM_META.get(sub.form_type) or {}
        title = meta.get("title", sub.form_type)
        pdf = art.generate_expense_pdf(sub, title)
        folder = art.submission_folder(sub)
        path = f"{folder}/{sub.reference}.pdf"
        info = _od.upload_to_path(pdf, path, "application/pdf")
        sub.pdf_web_url = (info or {}).get("webUrl") or path
        bills = [a.web_url or a.onedrive_path for a in
                 db.query(ExpenseAttachment)
                 .filter(ExpenseAttachment.submission_id == sub.id).all()]
        try:
            art.append_expense_log(sub, meta.get("code", ""), bills, sub.pdf_web_url)
        except Exception as e:
            log.warning("[expense-artifacts] master log append failed for %s: %s",
                        sub.reference, e)
        return sub.pdf_web_url
    except Exception as e:
        log.error("[expense-artifacts] PDF/OneDrive failed for %s: %s",
                  sub.reference, e, exc_info=True)
        return None




def _admin_guard(request: Request, user, db):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    if not _is_admin(db, user):
        return _err(403, "Admin access required")
    return None


def _admin_row(s: ExpenseSubmission) -> dict:
    d = _sub_row(s)
    d.update({
        "employee_name": s.employee_name,
        "employee_email": s.employee_email,
        "employee_level": s.employee_level,
        "purpose_category": s.purpose_category,
        "trip_end_date": s.trip_end_date,
        "late_settlement": bool(s.late_settlement),
        "late_hours": s.late_hours,
        "actuals": s.actuals,
        "settlement_note": s.settlement_note,
        "advance_hr_verified_by": s.advance_hr_verified_by,
        "advance_mgmt_approved_by": s.advance_mgmt_approved_by,
        "advance_paid_by": s.advance_paid_by,
        "deadline_bypass": bool(s.deadline_bypass),
    })
    return d


@router.get("/api/admin/submissions")
def api_admin_submissions(request: Request, status: str | None = None,
                          user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    q = db.query(ExpenseSubmission)
    if status:
        q = q.filter(ExpenseSubmission.status == status)
    rows = q.order_by(ExpenseSubmission.submitted_at_ist.desc()).all()
    return {"submissions": [_admin_row(s) for s in rows]}


@router.get("/api/admin/pending")
def api_admin_pending(request: Request, user=Depends(get_optional_user),
                      db: Session = Depends(get_db)):
    """All five in-flight review states, with per-stage counts for the badges."""
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    buckets = {}
    for st in REVIEW_STATES:
        buckets[st] = (db.query(ExpenseSubmission)
                       .filter(ExpenseSubmission.status == st)
                       .order_by(ExpenseSubmission.submitted_at_ist.desc()).all())
    ordered = [s for st in REVIEW_STATES for s in buckets[st]]
    return {
        "submissions": [_admin_row(s) for s in ordered],
        "pending_count": len(buckets["pending"]),
        "advance_hr_verified_count": len(buckets["advance_hr_verified"]),
        "advance_mgmt_approved_count": len(buckets["advance_mgmt_approved"]),
        "settlement_pending_count": len(buckets["settlement_pending"]),
    }


async def _body(request: Request) -> dict:
    try:
        return await request.json() or {}
    except Exception:
        return {}


def _reason_of(body: dict, key: str = "reason"):
    """Source requires 3-1000 chars on the reopen/recall/archive verbs."""
    r = str(body.get(key) or "").strip()
    if len(r) < 3:
        return None, "Please give a reason (3+ chars)."
    if len(r) > 1000:
        return None, "Reason too long (max 1000 chars)."
    return r, None


def _load(db: Session, sub_id: int):
    return db.query(ExpenseSubmission).filter(ExpenseSubmission.id == sub_id).first()


@router.post("/api/admin/submissions/{sub_id}/approve")
async def api_admin_approve(sub_id: int, request: Request, bg: BackgroundTasks,
                            user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    s = _load(db, sub_id)
    if not s:
        return _err(404, "Submission not found.")
    if s.status != "pending":
        return _err(400, f"Cannot approve a submission in '{s.status}' status.")
    note = (await _body(request)).get("note") or ""

    if s.form_type == "met_advance":
        # Stage 1 of the chain — HR verifies, Arasu approves next.
        s.status = "advance_hr_verified"
        s.advance_stage = "mgmt_review"
        s.advance_hr_verified_by = _me_email(db, user)
        s.advance_hr_verified_at = _ist_now()
        s.reviewed_by = _me_email(db, user)
        s.reviewed_at_ist = _ist_now()
        s.review_note = note
        db.commit()
        notify_advance_stage(bg, s, "hr_verified")
        return {"ok": True, "status": "advance_hr_verified",
                "message": "Advance verified — sent for management approval."}

    s.status = "approved"
    s.reviewed_by = _me_email(db, user)
    s.reviewed_at_ist = _ist_now()
    s.review_note = note
    pdf_url = _artifact_for(db, s)
    db.commit()
    notify_expense_decision(bg, s, (FORM_META.get(s.form_type) or {}).get("title", s.form_type))
    return {"ok": True, "status": "approved", "pdf_url": pdf_url}


def _me_email(db: Session, user) -> str:
    return (user.email or "").lower()


@router.post("/api/admin/submissions/{sub_id}/reject")
async def api_admin_reject(sub_id: int, request: Request, bg: BackgroundTasks,
                           user=Depends(get_optional_user), db: Session = Depends(get_db)):
    """Send back for changes — the row goes to draft, not to a dead end."""
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    s = _load(db, sub_id)
    if not s:
        return _err(404, "Submission not found.")
    if s.status != "pending":
        return _err(400, f"Cannot send back from '{s.status}' status.")
    body = await _body(request)
    changes = str(body.get("changes_required") or body.get("note") or "").strip()
    if not changes:
        return _err(400, "Please describe what needs to change so the employee "
                         "knows how to fix it.")
    if len(changes) > 2000:
        return _err(400, "Changes-required message is too long (max 2000 chars).")
    s.status = "draft"
    s.changes_required = changes
    s.returned_at_ist = _ist_now()
    s.reviewed_by = _me_email(db, user)
    s.reviewed_at_ist = _ist_now()
    s.review_note = str(body.get("note") or "").strip()
    db.commit()
    notify_expense_decision(bg, s, (FORM_META.get(s.form_type) or {}).get("title", s.form_type))
    return {"ok": True, "status": "draft"}


@router.post("/api/admin/submissions/{sub_id}/advance-mgmt-approve")
async def api_advance_mgmt_approve(sub_id: int, request: Request, bg: BackgroundTasks,
                                   user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    s = _load(db, sub_id)
    if not s:
        return _err(404, "Submission not found.")
    if s.form_type != "met_advance":
        return _err(400, "Only Travel Advance submissions have a management-approval step.")
    if s.status != "advance_hr_verified":
        return _err(400, f"Cannot mgmt-approve advance from '{s.status}' status.")
    s.status = "advance_mgmt_approved"
    s.advance_stage = "accounts_pay"
    s.advance_mgmt_approved_by = _me_email(db, user)
    s.advance_mgmt_approved_at = _ist_now()
    db.commit()
    notify_advance_stage(bg, s, "mgmt_approved")
    return {"ok": True, "status": "advance_mgmt_approved",
            "message": "Approved — sent to Accounts for payment."}


@router.post("/api/admin/submissions/{sub_id}/advance-mark-paid")
async def api_advance_mark_paid(sub_id: int, request: Request, bg: BackgroundTasks,
                                user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    s = _load(db, sub_id)
    if not s:
        return _err(404, "Submission not found.")
    if s.form_type != "met_advance":
        return _err(400, "Only Travel Advance submissions can be marked paid this way.")
    if s.status != "advance_mgmt_approved":
        return _err(400, f"Cannot mark paid from '{s.status}' status.")
    s.status = "advance_approved"        # open advance, awaiting settlement
    s.advance_stage = "paid"
    s.advance_paid_by = _me_email(db, user)
    s.advance_paid_at = _ist_now()
    db.commit()
    notify_advance_stage(bg, s, "paid")
    return {"ok": True, "status": "advance_approved",
            "message": "Payment recorded — advance is now open for settlement."}


@router.post("/api/admin/submissions/{sub_id}/approve-settlement")
async def api_approve_settlement(sub_id: int, request: Request, bg: BackgroundTasks,
                                 user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    s = _load(db, sub_id)
    if not s:
        return _err(404, "Submission not found.")
    if s.form_type != "met_advance":
        return _err(400, "Settlement approval only applies to Travel Advance submissions.")
    if s.status != "settlement_pending":
        return _err(400, f"Cannot approve settlement from '{s.status}' status.")
    # Signed differential = actual - advance. The consolidated report picks
    # up this number rather than the full actual, since the advance was paid.
    advance_amount = float(s.total_amount or 0)
    try:
        actual_amount = float((s.actuals or {}).get("actual_amount") or 0)
    except (TypeError, ValueError):
        actual_amount = 0.0
    s.differential_amount = round(actual_amount - advance_amount, 2)
    s.status = "settled"
    s.settlement_reviewed_by = _me_email(db, user)
    s.settlement_note = str((await _body(request)).get("note") or "")
    s.settled_at_ist = _ist_now()
    pdf_url = _artifact_for(db, s)
    db.commit()
    notify_expense_decision(bg, s, (FORM_META.get(s.form_type) or {}).get("title", s.form_type))
    return {"ok": True, "status": "settled",
            "differential_amount": s.differential_amount, "pdf_url": pdf_url}


@router.post("/api/admin/submissions/{sub_id}/reject-settlement")
async def api_reject_settlement(sub_id: int, request: Request, bg: BackgroundTasks,
                                user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    s = _load(db, sub_id)
    if not s:
        return _err(404, "Submission not found.")
    if s.form_type != "met_advance":
        return _err(400, "Settlement rejection only applies to Travel Advance submissions.")
    if s.status != "settlement_pending":
        return _err(400, f"Cannot reject settlement from '{s.status}' status.")
    s.status = "settlement_rejected"
    s.settlement_reviewed_by = _me_email(db, user)
    s.settlement_note = str((await _body(request)).get("note") or "")
    s.settled_at_ist = _ist_now()
    db.commit()
    notify_expense_decision(bg, s, (FORM_META.get(s.form_type) or {}).get("title", s.form_type))
    return {"ok": True, "rejected": True}


@router.post("/api/admin/submissions/{sub_id}/settle-offline")
async def api_settle_offline(sub_id: int, request: Request,
                             user=Depends(get_optional_user), db: Session = Depends(get_db)):
    """Already paid outside the portal — close it without a payment record."""
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    s = _load(db, sub_id)
    if not s:
        return _err(404, "Submission not found.")
    if s.status != "pending":
        return _err(400, "Only pending submissions can be marked settled-already. "
                         f"This one is '{s.status}'.")
    s.status = "settled_offline"
    s.reviewed_by = _me_email(db, user)
    s.reviewed_at_ist = _ist_now()
    s.review_note = str((await _body(request)).get("note") or "")
    db.commit()
    return {"ok": True}


def _in_locked_consolidated(db: Session, sub_id: int):
    """A submission inside a consolidated report that has left draft cannot be
    reopened — the source blocks this to stop the report and the rows diverging."""
    for r in (db.query(ExpenseConsolidatedReport)
              .filter(ExpenseConsolidatedReport.status.in_(["pending_mgmt", "approved"]))
              .all()):
        if sub_id in (r.submission_ids or []):
            return r
    return None


@router.post("/api/admin/submissions/{sub_id}/unapprove")
async def api_unapprove(sub_id: int, request: Request,
                        user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    s = _load(db, sub_id)
    if not s:
        return _err(404, "Submission not found.")
    if s.status != "approved":
        return _err(400, f"Only approved submissions can be reopened. This one is '{s.status}'.")
    reason, rerr = _reason_of(await _body(request))
    if rerr:
        return _err(400, rerr)
    locked = _in_locked_consolidated(db, sub_id)
    if locked:
        label = ("an approved consolidated report" if locked.status == "approved"
                 else "a consolidated report awaiting management approval")
        return _err(409, f"Cannot reopen — this submission is part of {label}. "
                         "To make changes, ask Arasu to reject the consolidated report "
                         "first (which returns every included submission to the employee "
                         "as a draft), or wait for the current consolidated flow to complete.")
    s.status = "pending"
    s.reviewed_by = _me_email(db, user)
    s.reviewed_at_ist = _ist_now()
    s.review_note = reason
    db.commit()
    return {"ok": True}


@router.post("/api/admin/submissions/{sub_id}/recall")
async def api_recall(sub_id: int, request: Request,
                     user=Depends(get_optional_user), db: Session = Depends(get_db)):
    """Pull a sent-back draft back into the review queue."""
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    s = _load(db, sub_id)
    if not s:
        return _err(404, "Submission not found.")
    if s.status != "draft":
        return _err(400, "Only sent-back (draft) submissions can be recalled. "
                         f"This one is '{s.status}'.")
    reason, rerr = _reason_of(await _body(request))
    if rerr:
        return _err(400, rerr)
    s.status = "pending"
    s.changes_required = None
    s.returned_at_ist = None
    s.reviewed_by = _me_email(db, user)
    s.reviewed_at_ist = _ist_now()
    s.review_note = reason
    db.commit()
    return {"ok": True}


@router.post("/api/admin/submissions/{sub_id}/archive")
async def api_archive(sub_id: int, request: Request,
                      user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    s = _load(db, sub_id)
    if not s:
        return _err(404, "Submission not found.")
    if s.status != "draft":
        return _err(400, f"Only sent-back (draft) submissions can be archived. This one is "
                         f"'{s.status}'. Send it back to draft first (or use Reopen/Recall) "
                         "if you want to archive it.")
    reason, rerr = _reason_of(await _body(request))
    if rerr:
        return _err(400, rerr)
    s.status = "archived"
    s.reviewed_by = _me_email(db, user)
    s.reviewed_at_ist = _ist_now()
    s.review_note = reason
    db.commit()
    return {"ok": True}


@router.post("/api/admin/submissions/{sub_id}/unarchive")
async def api_unarchive(sub_id: int, request: Request,
                        user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    s = _load(db, sub_id)
    if not s:
        return _err(404, "Submission not found.")
    if s.status != "archived":
        return _err(400, f"Only archived submissions can be unarchived. This one is '{s.status}'.")
    reason, rerr = _reason_of(await _body(request))
    if rerr:
        return _err(400, rerr)
    s.status = "draft"
    s.reviewed_by = _me_email(db, user)
    s.reviewed_at_ist = _ist_now()
    s.review_note = reason
    db.commit()
    return {"ok": True}


# ============================================================================
# Slice 5 — payments, period overrides, admin projects, employees
#
# Payable amount per row (source: payableAmountForRow):
#   settled  -> actuals.actual_amount   (the advance itself was paid earlier)
#   approved -> total_amount
#   anything else -> 0
# Recomputed server-side on mark-paid; a client-supplied amount is never trusted.
# ============================================================================

from ..models import ExpenseMonthlyPayment  # noqa: E402


def _payable(s: ExpenseSubmission) -> float:
    if s.status == "settled":
        try:
            v = float((s.actuals or {}).get("actual_amount") or 0)
        except (TypeError, ValueError):
            return 0.0
        return v if v > 0 else 0.0
    if s.status == "approved":
        try:
            return float(s.total_amount or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _valid_ym(year, month):
    try:
        y, mo = int(year), int(month)
    except (TypeError, ValueError):
        return None, None, "Valid year required (YYYY)"
    if not (2000 <= y <= 2100):
        return None, None, "Valid year required (YYYY)"
    if not (1 <= mo <= 12):
        return None, None, "Valid month required (1–12)"
    return y, mo, None


def _payable_rows(db: Session, period: str):
    return (db.query(ExpenseSubmission)
            .filter(ExpenseSubmission.period == period,
                    ExpenseSubmission.status.in_(["approved", "settled"]))
            .all())


@router.get("/api/admin/payments")
def api_payments(request: Request, year: int | None = None, month: int | None = None,
                 user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    y, mo, err = _valid_ym(year, month)
    if err:
        return _err(400, err)
    period = f"{y}-{mo:02d}"

    buckets = {}
    for s in _payable_rows(db, period):
        amt = _payable(s)
        if amt <= 0:
            continue
        b = buckets.setdefault(s.employee_id, {
            "id": s.employee_id, "name": s.employee_name, "email": s.employee_email,
            "total_payable": 0.0, "submission_count": 0, "submissions": []})
        b["total_payable"] += amt
        b["submission_count"] += 1
        b["submissions"].append({
            "id": s.id, "reference": s.reference, "form_type": s.form_type,
            "status": s.status, "payable_amount": round(amt, 2),
            "submitted_at": s.submitted_at_ist})

    paid_by = {p.employee_id: p for p in db.query(ExpenseMonthlyPayment)
               .filter(ExpenseMonthlyPayment.year == y,
                       ExpenseMonthlyPayment.month == mo).all()}

    employees = []
    for b in buckets.values():
        p = paid_by.get(b["id"])
        employees.append({**b, "total_payable": round(b["total_payable"], 2),
                          "paid": ({"amount_paid": p.amount_paid, "paid_by": p.paid_by,
                                    "paid_at": p.paid_at_ist,
                                    "email_sent_at": p.email_sent_at} if p else None)})
    employees.sort(key=lambda e: (e["name"] or "").lower())
    return {"year": y, "month": mo, "period": period, "employees": employees}


@router.post("/api/admin/payments/mark")
async def api_payments_mark(request: Request, bg: BackgroundTasks,
                            user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    body = await _body(request)
    try:
        emp_id = int(body.get("employee_id"))
        assert emp_id > 0
    except (TypeError, ValueError, AssertionError):
        return _err(400, "Valid employee_id required")
    y, mo, err = _valid_ym(body.get("year"), body.get("month"))
    if err:
        return _err(400, err.replace(" (YYYY)", "") if "year" in err else err)
    period = f"{y}-{mo:02d}"

    # Recompute server-side — never trust a client-supplied amount.
    total = sum(_payable(s) for s in _payable_rows(db, period) if s.employee_id == emp_id)
    if not total > 0:
        return _err(400, "No approved/settled submissions to pay for this employee × month.")
    amount = round(total, 2)

    row = (db.query(ExpenseMonthlyPayment)
           .filter(ExpenseMonthlyPayment.employee_id == emp_id,
                   ExpenseMonthlyPayment.year == y,
                   ExpenseMonthlyPayment.month == mo).first())
    if row:
        row.amount_paid = amount
        row.paid_by = _me_email(db, user)
        row.paid_at_ist = _ist_now()
    else:
        row = ExpenseMonthlyPayment(
            employee_id=emp_id, year=y, month=mo, amount_paid=amount,
            paid_by=_me_email(db, user), paid_at_ist=_ist_now())
        db.add(row)
    db.flush()          # so the email bookkeeping below can stamp this row
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    err = None
    try:
        notify_payment_marked(bg, emp.email if emp else None,
                              emp.name if emp else "", y, mo, amount)
        row.email_sent_at = _ist_now()
        row.email_error = None
    except Exception as e:            # payment stands even if the email fails
        err = str(e)[:480]
        log.warning("[payments] confirmation email failed: %s", e)
        row.email_error = err
    db.commit()
    return {"ok": True, "employee_id": emp_id, "year": y, "month": mo,
            "amount_paid": amount, "email_sent": err is None, "email_error": err}


@router.post("/api/admin/payments/unmark")
async def api_payments_unmark(request: Request, user=Depends(get_optional_user),
                              db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    body = await _body(request)
    try:
        emp_id = int(body.get("employee_id"))
    except (TypeError, ValueError):
        return _err(400, "Valid employee_id required")
    y, mo, err = _valid_ym(body.get("year"), body.get("month"))
    if err:
        return _err(400, err)
    row = (db.query(ExpenseMonthlyPayment)
           .filter(ExpenseMonthlyPayment.employee_id == emp_id,
                   ExpenseMonthlyPayment.year == y,
                   ExpenseMonthlyPayment.month == mo).first())
    if not row:
        return _err(404, "No payment record found for this employee × month.")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------- period overrides

def _override_json(o: ExpensePeriodOverride) -> dict:
    return {"id": o.id, "employee_id": o.employee_id, "period": o.period,
            "expires_at": o.expires_at, "granted_by": o.granted_by,
            "granted_at": o.granted_at, "revoked_at": o.revoked_at,
            "revoked_by": o.revoked_by, "reason": o.reason}


@router.get("/api/admin/period-overrides")
def api_overrides_active(request: Request, user=Depends(get_optional_user),
                         db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    now = _dt.utcnow().isoformat()
    rows = (db.query(ExpensePeriodOverride)
            .filter(ExpensePeriodOverride.revoked_at.is_(None),
                    ExpensePeriodOverride.expires_at > now)
            .order_by(ExpensePeriodOverride.id.desc()).all())
    return {"overrides": [_override_json(o) for o in rows]}


@router.get("/api/admin/period-overrides/all")
def api_overrides_all(request: Request, user=Depends(get_optional_user),
                      db: Session = Depends(get_db)):
    """Never deleted — revoked rows stay for audit."""
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    rows = (db.query(ExpensePeriodOverride)
            .order_by(ExpensePeriodOverride.id.desc()).all())
    return {"overrides": [_override_json(o) for o in rows]}


@router.post("/api/admin/period-overrides")
async def api_override_grant(request: Request, user=Depends(get_optional_user),
                             db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    body = await _body(request)
    period = str(body.get("period") or "").strip()
    if not _re.match(r"^\d{4}-\d{2}$", period):
        return _err(400, "period must be YYYY-MM")

    employee_id = None
    raw_emp = body.get("employee_id")
    if raw_emp not in (None, ""):
        try:
            employee_id = int(raw_emp)
            assert employee_id > 0
        except (TypeError, ValueError, AssertionError):
            return _err(400, "invalid employee_id")
        if not db.query(Employee).filter(Employee.id == employee_id).first():
            return _err(400, "employee not found")

    # expires_at_ist (wall-clock IST) wins over days_valid when both are sent.
    now = _dt.utcnow()
    raw_exp = str(body.get("expires_at_ist") or "").strip()
    if raw_exp:
        m = _re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$", raw_exp)
        if not m:
            return _err(400, "expires_at_ist must be YYYY-MM-DDTHH:MM")
        y, mo, d, hh, mm = (int(x) for x in m.groups())
        expires = _dt(y, mo, d, hh, mm) - IST          # IST wall-clock -> UTC
        if expires <= now:
            return _err(400, "expires_at_ist must be in the future")
        if expires > now + _td(days=60):
            return _err(400, "expires_at_ist cannot be more than 60 days from now")
    else:
        raw_days = body.get("days_valid")
        days = 7
        if raw_days not in (None, ""):
            try:
                days = int(raw_days)
                assert 1 <= days <= 30
            except (TypeError, ValueError, AssertionError):
                return _err(400, "days_valid must be 1–30")
        expires = now + _td(days=days)

    o = ExpensePeriodOverride(
        employee_id=employee_id, period=period,
        expires_at=expires.isoformat(timespec="seconds"),
        granted_by=_me_email(db, user), granted_at=now.isoformat(timespec="seconds"),
        reason=(str(body.get("reason") or "").strip()[:500] or None))
    db.add(o)
    db.commit()
    return {"ok": True, "id": o.id, "expires_at": o.expires_at}


@router.post("/api/admin/period-overrides/{override_id}/revoke")
def api_override_revoke(override_id: int, request: Request,
                        user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    o = (db.query(ExpensePeriodOverride)
         .filter(ExpensePeriodOverride.id == override_id,
                 ExpensePeriodOverride.revoked_at.is_(None)).first())
    if not o:
        return _err(404, "Override not found or already revoked.")
    o.revoked_at = _dt.utcnow().isoformat(timespec="seconds")
    o.revoked_by = _me_email(db, user)
    db.commit()
    return {"ok": True}


# -------------------------------------------------------- admin projects

@router.get("/api/admin/projects")
def api_admin_projects(request: Request, user=Depends(get_optional_user),
                       db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    rows = db.query(ExpenseProject).order_by(ExpenseProject.name).all()
    return {"projects": [{"id": p.id, "code": p.code, "name": p.name,
                          "is_active": 1 if p.is_active else 0} for p in rows]}


@router.post("/api/admin/projects")
async def api_admin_project_create(request: Request, user=Depends(get_optional_user),
                                   db: Session = Depends(get_db)):
    """De-dups on name (case-insensitive); an existing row is reactivated
    rather than duplicated, matching the source."""
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    body = await _body(request)
    name = str(body.get("name") or "").strip()
    code = str(body.get("code") or "").strip() or None
    if not name:
        return _err(400, "Project name is required.")
    if len(name) > 100:
        return _err(400, "Project name is too long (max 100 chars).")

    existing = next((p for p in db.query(ExpenseProject).all()
                     if (p.name or "").lower() == name.lower()), None)
    if existing:
        existing.name = name
        existing.code = code or existing.code
        existing.is_active = True
        db.commit()
        return {"ok": True, "reactivated": True,
                "project": {"id": existing.id, "code": existing.code,
                            "name": existing.name, "is_active": 1}}
    p = ExpenseProject(code=code, name=name, is_active=True)
    db.add(p)
    db.commit()
    return {"ok": True, "project": {"id": p.id, "code": p.code,
                                    "name": p.name, "is_active": 1}}


@router.put("/api/admin/projects/{project_id}")
async def api_admin_project_update(project_id: int, request: Request,
                                   user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    p = db.query(ExpenseProject).filter(ExpenseProject.id == project_id).first()
    if not p:
        return _err(404, "Project not found.")
    body = await _body(request)
    if "name" in body:
        name = str(body.get("name") or "").strip()
        if not name:
            return _err(400, "Project name is required.")
        if len(name) > 100:
            return _err(400, "Project name is too long (max 100 chars).")
        clash = next((x for x in db.query(ExpenseProject).all()
                      if x.id != p.id and (x.name or "").lower() == name.lower()), None)
        if clash:
            return _err(409, "Another project already uses that name.")
        p.name = name
    if "code" in body:
        p.code = str(body.get("code") or "").strip() or None
    if "is_active" in body:
        p.is_active = bool(int(body.get("is_active") or 0))
    db.commit()
    return {"ok": True, "project": {"id": p.id, "code": p.code, "name": p.name,
                                    "is_active": 1 if p.is_active else 0}}


@router.delete("/api/admin/projects/{project_id}")
def api_admin_project_delete(project_id: int, request: Request,
                             user=Depends(get_optional_user), db: Session = Depends(get_db)):
    """Soft delete — a project referenced by historical claims must stay
    resolvable, so it is deactivated rather than removed."""
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    p = db.query(ExpenseProject).filter(ExpenseProject.id == project_id).first()
    if not p:
        return _err(404, "Project not found.")
    p.is_active = False
    db.commit()
    return {"ok": True, "deactivated": True}


# ------------------------------------------------------- employees (read)

@router.get("/api/admin/employees")
def api_admin_employees(request: Request, all: str | None = None,
                        user=Depends(get_optional_user), db: Session = Depends(get_db)):
    """Read-only here on purpose: the portal owns employee records at /people
    (roles, module access, password resets). Mirroring create/edit/delete into
    the expense SPA would give two front doors to one roster."""
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    q = db.query(Employee)
    if all != "1":
        q = q.filter(Employee.is_active == True)  # noqa: E712
    rows = q.order_by(Employee.name).all()
    levels = {m.employee_id: m.level for m in db.query(ExpenseEmployeeMeta).all()}
    return {"employees": [{
        "id": e.id, "name": e.name, "email": e.email,
        "employee_code": e.employee_code, "designation": e.designation,
        "department": e.department, "level": levels.get(e.id, "L1"),
        "is_active": 1 if e.is_active else 0} for e in rows]}


# ============================================================================
# Slice 6 — consolidated monthly reports (the month-end deliverable)
#
#   draft --send-for-approval--> pending_mgmt --approve-mgmt--> approved
#                                      |
#                                      +--reject--> rejected
#
# HR clicking "Send for final approval" IS the HR sign-off — the report goes
# straight to Management, no separate consolidated-level HR review step.
#
# Rejection returns the underlying REGULAR claims to the employee as drafts
# with deadline_bypass set (so the closed period doesn't block the fix), but
# leaves SETTLED ADVANCES at 'settled' with a note appended — reopening a
# closed advance would unwind money that has already moved.
# ============================================================================

TERMINAL_GOOD = ("approved", "settled", "settled_offline", "archived")

def _build_consolidated(db: Session, r: ExpenseConsolidatedReport) -> str | None:
    """Render the consolidated PDF and push it to OneDrive. Fail-soft."""
    try:
        from ..routes.expense import _artifacts
        art = _artifacts()
        emp = db.query(Employee).filter(Employee.id == r.employee_id).first()
        rows = (db.query(ExpenseSubmission)
                .filter(ExpenseSubmission.id.in_(list(r.submission_ids or [])))
                .order_by(ExpenseSubmission.submitted_at_ist).all())
        pdf, pages = art.build_consolidated_pdf(
            r, {"name": emp.name if emp else "", "email": emp.email if emp else "",
                "code": emp.employee_code if emp else ""}, rows)
        safe = (emp.employee_code if emp and emp.employee_code else str(r.employee_id))
        path = (f"{art.expense_root()}/{r.period}/_Consolidated/"
                f"{safe}_{r.period}.pdf")
        info = _od.upload_to_path(pdf, path, "application/pdf")
        r.pdf_web_url = (info or {}).get("webUrl") or path
        r.pdf_page_count = pages or None
        return r.pdf_web_url
    except Exception as e:
        log.error("[consolidated-pdf] build failed for report %s: %s", r.id, e,
                  exc_info=True)
        return None




def _rollup_for_period(db: Session, period: str) -> list[dict]:
    """Port of listMonthlySummaryForPeriod, including the payable CASE:
         approved            -> +total_amount
         settled advance     -> +differential_amount (signed)
         settled non-advance -> +actuals.actual_amount, else total_amount
    Total can go negative when settlement shortfalls exceed reimbursements.
    """
    rows = (db.query(ExpenseSubmission)
            .filter(ExpenseSubmission.period == period).all())
    by_emp: dict[int, dict] = {}
    for s in rows:
        r = by_emp.setdefault(s.employee_id, {
            "employee_id": s.employee_id, "employee_name": s.employee_name,
            "employee_email": s.employee_email, "employee_code": None,
            "total": 0, "pending_count": 0, "approved_count": 0, "settled_count": 0,
            "settled_advance_count": 0, "settled_offline_count": 0,
            "archived_count": 0, "draft_count": 0, "rejected_count": 0,
            "advance_hr_verified_count": 0, "advance_mgmt_approved_count": 0,
            "advance_approved_count": 0, "approved_total": 0.0})
        r["total"] += 1
        key = f"{s.status}_count"
        if key in r:
            r[key] += 1
        if s.status == "settled" and s.form_type == "met_advance":
            r["settled_advance_count"] += 1

        if s.status == "approved":
            r["approved_total"] += float(s.total_amount or 0)
        elif s.status == "settled" and s.form_type == "met_advance":
            r["approved_total"] += float(s.differential_amount or 0)
        elif s.status == "settled":
            try:
                v = (s.actuals or {}).get("actual_amount")
            except AttributeError:
                v = None
            r["approved_total"] += float(v if v is not None else (s.total_amount or 0))

    codes = {e.id: e.employee_code for e in db.query(Employee).all()}
    out = []
    for r in by_emp.values():
        r["employee_code"] = codes.get(r["employee_id"])
        r["approved_total"] = round(r["approved_total"], 2)
        out.append(r)
    out.sort(key=lambda r: (r["employee_name"] or "").lower())
    return out


def _report_json(r: ExpenseConsolidatedReport) -> dict:
    return {
        "id": r.id, "employee_id": r.employee_id, "period": r.period,
        "status": r.status, "total_amount": r.total_amount,
        "submission_count": r.submission_count,
        "submission_ids": list(r.submission_ids or []),
        "pdf_path": r.pdf_web_url, "pdf_page_count": r.pdf_page_count,
        "generated_at": r.generated_at, "generated_by": r.generated_by,
        "hr_emailed_at": r.hr_emailed_at, "hr_approved_by": r.hr_approved_by,
        "hr_approved_at": r.hr_approved_at, "hr_rejected_reason": r.hr_rejected_reason,
        "mgmt_emailed_at": r.mgmt_emailed_at, "mgmt_approved_by": r.mgmt_approved_by,
        "mgmt_approved_at": r.mgmt_approved_at,
        "mgmt_rejected_reason": r.mgmt_rejected_reason,
        "accounts_sent_at": r.accounts_sent_at,
        "accounts_email_error": r.accounts_email_error,
    }


@router.get("/api/admin/consolidated")
def api_consolidated_list(request: Request, period: str | None = None,
                          user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    q = db.query(ExpenseConsolidatedReport)
    if period:
        q = q.filter(ExpenseConsolidatedReport.period == period.strip())
    rows = q.order_by(ExpenseConsolidatedReport.id.desc()).all()
    return {"reports": [_report_json(r) for r in rows]}


@router.get("/api/admin/consolidated/monthly-summary")
def api_monthly_summary(request: Request, period: str = "",
                        user=Depends(get_optional_user), db: Session = Depends(get_db)):
    """Per-employee rollup for the Monthly Wrap-up tab — who is ready to send
    and who is still blocked, merged with any existing report state."""
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    period = (period or "").strip()
    if not _re.match(r"^\d{4}-\d{2}$", period):
        return _err(400, "period must be YYYY-MM")
    reports = {r.employee_id: r for r in db.query(ExpenseConsolidatedReport)
               .filter(ExpenseConsolidatedReport.period == period).all()}
    rows = []
    for r in _rollup_for_period(db, period):
        cr = reports.get(r["employee_id"])
        rows.append({**r, "consolidated_report": _report_json(cr) if cr else None})
    return {"period": period, "rows": rows}


@router.get("/api/admin/consolidated/{report_id}")
def api_consolidated_get(report_id: int, request: Request,
                         user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    r = (db.query(ExpenseConsolidatedReport)
         .filter(ExpenseConsolidatedReport.id == report_id).first())
    if not r:
        return _err(404, "Not found")
    return {"report": _report_json(r)}


def _blockers(rollup: dict) -> list[str]:
    """Everything that must be cleared before a month can be sent."""
    out = []
    if rollup["pending_count"]:
        out.append(f"{rollup['pending_count']} pending")
    if rollup["draft_count"]:
        out.append(f"{rollup['draft_count']} draft")
    if rollup["advance_hr_verified_count"]:
        out.append(f"{rollup['advance_hr_verified_count']} advance awaiting Arasu")
    if rollup["advance_mgmt_approved_count"]:
        out.append(f"{rollup['advance_mgmt_approved_count']} advance awaiting Accounts payment")
    if rollup["advance_approved_count"]:
        out.append(f"{rollup['advance_approved_count']} advance awaiting settlement")
    if rollup["rejected_count"]:
        out.append(f"{rollup['rejected_count']} rejected "
                   "(must be re-submitted & approved, or excluded)")
    return out


@router.post("/api/admin/consolidated/send-for-approval")
async def api_send_for_approval(request: Request, bg: BackgroundTasks,
                                user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    body = await _body(request)
    try:
        emp_id = int(body.get("employee_id"))
        assert emp_id > 0
    except (TypeError, ValueError, AssertionError):
        return _err(400, "invalid employee_id")
    period = str(body.get("period") or "").strip()
    if not _re.match(r"^\d{4}-\d{2}$", period):
        return _err(400, "period must be YYYY-MM")

    rollup = next((r for r in _rollup_for_period(db, period)
                   if r["employee_id"] == emp_id), None)
    if not rollup:
        return _err(400, "No submissions found for that employee in that month.")
    blk = _blockers(rollup)
    if blk:
        return _err(400, f"Cannot send yet — {', '.join(blk)}. "
                         "All submissions must be approved/settled first.")
    if (rollup["approved_count"] + rollup["settled_count"]) == 0:
        return _err(400, "Nothing to send — this employee has no approved/settled "
                         "submissions for that month.")

    existing = (db.query(ExpenseConsolidatedReport)
                .filter(ExpenseConsolidatedReport.employee_id == emp_id,
                        ExpenseConsolidatedReport.period == period).first())
    if existing:
        if existing.status == "pending_mgmt":
            return _err(400, 'A report has already been sent for approval. '
                             'Use "Resend email" if Arasu didn\'t receive it.')
        if existing.status == "approved":
            return _err(400, "This report is already approved. Payment has been "
                             "sent to accounts.")
        # 'rejected' or a half-finished 'draft' may be re-sent — fall through.

    included = [s for s in db.query(ExpenseSubmission)
                .filter(ExpenseSubmission.period == period,
                        ExpenseSubmission.employee_id == emp_id).all()
                if s.status in ("approved", "settled")]
    now = _ist_now()
    r = existing or ExpenseConsolidatedReport(employee_id=emp_id, period=period)
    r.status = "pending_mgmt"
    r.total_amount = rollup["approved_total"]
    r.submission_count = len(included)
    r.submission_ids = [s.id for s in included]
    r.generated_at = now
    r.generated_by = _me_email(db, user)
    r.hr_approved_by = _me_email(db, user)      # sending IS the HR sign-off
    r.hr_approved_at = now
    r.mgmt_emailed_at = r.mgmt_emailed_at or now
    r.mgmt_rejected_reason = None
    if not existing:
        db.add(r)
    _build_consolidated(db, r)
    db.commit()
    err = None
    try:
        notify_consolidated_for_review(bg, r, rollup["employee_name"])
    except Exception as e:
        err = str(e)[:480]
        log.warning("[consolidated] review email failed: %s", e)
    return {"ok": True, "report_id": r.id, "email_ok": err is None, "email_error": err}


@router.post("/api/admin/consolidated/{report_id}/approve-mgmt")
def api_approve_mgmt(report_id: int, request: Request, bg: BackgroundTasks,
                     user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    r = (db.query(ExpenseConsolidatedReport)
         .filter(ExpenseConsolidatedReport.id == report_id).first())
    if not r:
        return _err(404, "Not found")
    if r.status != "pending_mgmt":
        return _err(400, f"Cannot Mgmt-approve: report is {r.status}")
    now = _ist_now()
    r.status = "approved"
    r.mgmt_approved_by = _me_email(db, user)
    r.mgmt_approved_at = now
    r.accounts_sent_at = r.accounts_sent_at or now
    db.commit()
    emp = db.query(Employee).filter(Employee.id == r.employee_id).first()
    try:
        notify_consolidated_to_accounts(bg, r, emp.name if emp else "")
    except Exception as e:
        r.accounts_email_error = str(e)[:480]
        db.commit()
        log.warning("[consolidated] accounts email failed: %s", e)
    return {"ok": True, "report_id": r.id, "status": "approved"}


@router.post("/api/admin/consolidated/{report_id}/reject")
async def api_reject_consolidated(report_id: int, request: Request, bg: BackgroundTasks,
                                  user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    r = (db.query(ExpenseConsolidatedReport)
         .filter(ExpenseConsolidatedReport.id == report_id).first())
    if not r:
        return _err(404, "Not found")
    if r.status != "pending_mgmt":
        return _err(400, f"Cannot reject: report is {r.status}")
    note = str((await _body(request)).get("note") or "").strip()
    if len(note) < 3:
        return _err(400, "Rejection note is required (3+ chars).")
    if len(note) > 2000:
        return _err(400, "Rejection note is too long (max 2000 chars).")

    stamp = (_dt.utcnow() + IST).strftime("%Y-%m-%d")
    attribution = f"[Consolidated report rejected by management: {note}]"
    returned_regular, touched_advances = 0, 0
    for sid in (r.submission_ids or []):
        s = db.query(ExpenseSubmission).filter(ExpenseSubmission.id == sid).first()
        if not s:
            continue
        if s.status == "settled" and s.form_type == "met_advance":
            # Money already moved — annotate, don't reopen.
            s.settlement_note = ((s.settlement_note or "") +
                                 f"\n[Consolidated rejected on {stamp}: {note[:200]}]")
            touched_advances += 1
        else:
            s.status = "draft"
            s.deadline_bypass = True      # the period is closed; let them fix it
            s.changes_required = attribution
            s.returned_at_ist = _ist_now()
            returned_regular += 1

    r.status = "rejected"
    r.mgmt_rejected_reason = note
    db.commit()
    emp = db.query(Employee).filter(Employee.id == r.employee_id).first()
    try:
        notify_consolidated_rejected(bg, r, emp.email if emp else None,
                                     emp.name if emp else "", note, returned_regular)
    except Exception as e:
        log.warning("[consolidated] rejection email failed: %s", e)
    return {"ok": True, "returned_submissions": returned_regular,
            "advances_flagged": touched_advances}


@router.post("/api/admin/consolidated/{report_id}/regenerate-pdf")
def api_regenerate_pdf(report_id: int, request: Request,
                       user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    r = (db.query(ExpenseConsolidatedReport)
         .filter(ExpenseConsolidatedReport.id == report_id).first())
    if not r:
        return _err(404, "Not found")
    if r.status != "pending_mgmt":
        return _err(400, f"Can only regenerate while pending_mgmt — report is {r.status}")
    url = _build_consolidated(db, r)
    db.commit()
    if not url:
        return _err(502, "PDF generation failed — see server logs.")
    return {"ok": True, "pdf_path": url, "pdf_page_count": r.pdf_page_count}


@router.post("/api/admin/consolidated/{report_id}/resend-email")
def api_resend_email(report_id: int, request: Request, bg: BackgroundTasks,
                     user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    r = (db.query(ExpenseConsolidatedReport)
         .filter(ExpenseConsolidatedReport.id == report_id).first())
    if not r:
        return _err(404, "Not found")
    emp = db.query(Employee).filter(Employee.id == r.employee_id).first()
    name = emp.name if emp else ""
    try:
        if r.status == "pending_mgmt":
            notify_consolidated_for_review(bg, r, name)
            target = "management"
        elif r.status == "approved":
            notify_consolidated_to_accounts(bg, r, name)
            target = "accounts"
        else:
            return _err(400, f"Nothing to resend for a report in '{r.status}'.")
    except Exception as e:
        return _err(502, f"Resend failed: {e}")
    r.mgmt_emailed_at = r.mgmt_emailed_at or _ist_now()
    db.commit()
    return {"ok": True, "resent_to": target}


# ============================================================================
# Slice 8 — spend dashboard + SMTP diagnostics
#
# Dashboard attribution rules, straight from the source:
#   amount   regular claim   -> total_amount
#            settled advance -> actuals.actual_amount (may exceed the advance)
#            open advance    -> counted only when include_pending, and always
#                               surfaced separately in the open_advances tile
#   category met_local/met_dtr -> Own Travel; met_cab -> Cab; met_accommodation
#            -> Accommodation; met_misc -> Misc; met_advance -> Travel Advances;
#            met_outstation -> split per trip category
#   project  DTR credits each ENTRY's fare to its own project; every other form
#            credits the whole amount to the submission's project
# ============================================================================

CAT_LABEL = {
    "own_travel": "Own Travel", "cab": "Cab Travel",
    "accommodation": "Accommodation", "food": "Food",
    "local_conv": "Local Conveyance", "out_travel": "Outstation Travel",
    "out_others": "Outstation Others", "misc": "Miscellaneous",
    "advance": "Travel Advances",
}


def _project_label(p) -> str:
    if not p:
        return None
    return f"{p.name} ({p.code})" if p.code and p.code != p.name else p.name


@router.get("/api/admin/dashboard")
def api_admin_dashboard(request: Request, from_: str | None = None, to: str | None = None,
                        include_pending: str | None = None,
                        user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    # The SPA sends ?from= — 'from' is a Python keyword, so read it off the query.
    frm = (request.query_params.get("from") or from_ or "")[:10]
    to = (request.query_params.get("to") or to or "")[:10]
    inc = str(include_pending or "").lower() in ("1", "true")

    statuses = (["approved", "settled", "pending", "advance_approved", "settlement_pending"]
                if inc else ["approved", "settled"])
    q = db.query(ExpenseSubmission).filter(ExpenseSubmission.status.in_(statuses))
    if frm:
        q = q.filter(ExpenseSubmission.submitted_at_ist >= frm)
    if to:
        q = q.filter(ExpenseSubmission.submitted_at_ist <= f"{to} 23:59:59")
    rows = q.order_by(ExpenseSubmission.id.desc()).all()

    projects = {p.id: p for p in db.query(ExpenseProject).all()}
    by_category, by_project, by_employee, by_status = {}, {}, {}, {}
    total_spend, total_subs = 0.0, 0
    open_adv = {"count": 0, "total_requested": 0.0}

    def add_cat(key, amt):
        if not amt or amt <= 0:
            return
        lbl = CAT_LABEL.get(key, key)
        by_category[lbl] = by_category.get(lbl, 0.0) + amt

    def add_proj(key, name, amt):
        cur = by_project.setdefault(key, {"name": name, "total": 0.0})
        cur["total"] += amt

    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        payload = r.payload or {}
        amount = 0.0

        if r.form_type == "met_advance":
            if r.status == "settled":
                try:
                    amount = float((r.actuals or {}).get("actual_amount") or 0)
                except (TypeError, ValueError, AttributeError):
                    amount = 0.0
            elif r.status == "pending":
                amount = float(r.total_amount or 0) if inc else 0.0
                if not inc:
                    open_adv["count"] += 1
                    open_adv["total_requested"] += float(r.total_amount or 0)
            elif r.status in ("advance_approved", "settlement_pending"):
                open_adv["count"] += 1
                open_adv["total_requested"] += float(r.total_amount or 0)
                amount = float(r.total_amount or 0) if inc else 0.0
        else:
            amount = float(r.total_amount or 0)

        if amount <= 0:
            continue
        total_spend += amount
        total_subs += 1

        # --- category ---
        if r.form_type in ("met_local", "met_dtr"):
            add_cat("own_travel", amount)
        elif r.form_type == "met_cab":
            add_cat("cab", amount)
        elif r.form_type == "met_accommodation":
            add_cat("accommodation", amount)
        elif r.form_type == "met_misc":
            add_cat("misc", amount)
        elif r.form_type == "met_advance":
            add_cat("advance", amount)
        elif r.form_type == "met_outstation":
            split = 0.0
            for trip in (payload.get("trips") or []):
                for cat_key, items in ((trip or {}).get("categories") or {}).items():
                    total = sum(float((it or {}).get("amount") or 0) for it in (items or []))
                    if total <= 0:
                        continue
                    split += total
                    if cat_key == "travel":
                        add_cat("out_travel", total)
                    elif cat_key == "accommodation":
                        add_cat("accommodation", total)
                    elif cat_key == "food":
                        add_cat("food", total)
                    elif cat_key in ("local_conveyance", "conveyance"):
                        add_cat("local_conv", total)
                    else:
                        add_cat("out_others", total)
            if split <= 0:                      # malformed payload — don't lose the money
                add_cat("out_travel", amount)
        else:
            add_cat("misc", amount)

        # --- project ---
        client = payload.get("client_name")
        if r.form_type == "met_dtr":
            entries = payload.get("entries") or []
            credited = 0.0
            for e in entries:
                fare = float((e or {}).get("fare") or 0)
                if fare <= 0:
                    continue
                credited += fare
                pid = _as_int((e or {}).get("project_id"))
                ecli = (e or {}).get("client_name")
                if pid:
                    add_proj(pid, _project_label(projects.get(pid)) or f"Project #{pid}", fare)
                elif ecli:
                    add_proj(f"prospect:{ecli.lower()}", f"{ecli} (Prospect)", fare)
                else:
                    add_proj("_unspecified", "No Project", fare)
            if credited <= 0:
                add_proj("_unspecified", "No Project", amount)
        else:
            pid = _as_int(payload.get("project_id"))
            if pid:
                add_proj(pid, _project_label(projects.get(pid)) or f"Project #{pid}", amount)
            elif client:
                add_proj(f"prospect:{client.lower()}", f"{client} (Prospect)", amount)
            else:
                add_proj("_unspecified", "No Project", amount)

        # --- employee ---
        if r.employee_id:
            cur = by_employee.setdefault(r.employee_id,
                                         {"name": r.employee_name or f"#{r.employee_id}",
                                          "total": 0.0})
            cur["total"] += amount

    real_projects = [k for k in by_project
                     if k != "_unspecified" and not str(k).startswith("prospect:")]
    return {
        "filters": {"from": frm, "to": to, "include_pending": inc},
        "summary": {
            "total_spend": round(total_spend, 2),
            "total_submissions": total_subs,
            "active_employees": len(by_employee),
            "active_projects": len(real_projects),
            "open_advances": {"count": open_adv["count"],
                              "total_requested": round(open_adv["total_requested"], 2)},
        },
        "by_category": sorted([{"label": k, "total": round(v, 2)}
                               for k, v in by_category.items()],
                              key=lambda x: -x["total"]),
        "by_project": sorted([{"name": v["name"], "total": round(v["total"], 2)}
                              for v in by_project.values()], key=lambda x: -x["total"]),
        "by_employee": sorted([{"name": v["name"], "total": round(v["total"], 2)}
                               for v in by_employee.values()], key=lambda x: -x["total"]),
        "by_status": by_status,
    }


# ------------------------------------------------------------ SMTP checks

@router.get("/api/admin/smtp-test")
def api_smtp_test(request: Request, user=Depends(get_optional_user),
                  db: Session = Depends(get_db)):
    """Config diagnostics only — never sends. The whitespace/length checks
    exist because credentials pasted from a web console often carry a
    trailing space or a stray control character."""
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    from ..config import get_settings
    st = get_settings()
    host = st.smtp_host or ""
    usr = st.smtp_user or ""
    cfg = {
        "host": host or None,
        "host_length": len(host),
        "host_has_whitespace": host != host.strip(),
        "port": st.smtp_port,
        "secure": bool(getattr(st, "smtp_secure", False)),
        "user": usr or None,
        "user_length": len(usr),
        "user_has_whitespace": usr != usr.strip(),
        "pass_set": bool(st.smtp_password),
        "pass_length": len(st.smtp_password or ""),
        "from_name": st.smtp_from_name or None,
        "from_email": st.smtp_from or usr or None,
    }
    missing = [k for k, v in (("SMTP_HOST", cfg["host"]),
                              ("SMTP_USER", cfg["user"]),
                              ("SMTP_PASS", cfg["pass_set"])) if not v]
    return {"ok": not missing, "config": cfg, "missing": missing}


@router.post("/api/admin/smtp-test/send")
async def api_smtp_test_send(request: Request, user=Depends(get_optional_user),
                             db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    to = str((await _body(request)).get("to") or "").strip()
    if not to or not _re.match(r"^[^@\s]+@[^@\s]+$", to):
        return _err(400, "Provide a valid recipient email in `to`.")
    try:
        # send_email() returns True as soon as it SCHEDULES the send when a
        # loop is already running — useless for a diagnostic. Await the async
        # form so the result reflects what SMTP actually did.
        from ..services.email_service import send_email_async
        sent = await send_email_async(
            to, "[Metfraa Portal] SMTP test",
            "<p>SMTP is configured correctly. "
            "This is a test message from the Expense module.</p>")
    except Exception as e:
        return JSONResponse(status_code=500,
                            content={"ok": False, "error": str(e)[:480], "code": None})
    if not sent:
        return JSONResponse(status_code=500, content={
            "ok": False, "error": "SMTP not configured — set SMTP_USER and SMTP_PASS.",
            "code": None})
    return {"ok": True, "to": to}


@router.get("/api/admin/consolidated/{report_id}/pdf")
def api_consolidated_pdf(report_id: int, request: Request,
                         user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    r = (db.query(ExpenseConsolidatedReport)
         .filter(ExpenseConsolidatedReport.id == report_id).first())
    if not r:
        return _err(404, "Not found")
    if not r.pdf_web_url:
        return _err(404, "No PDF has been generated for this report yet.")
    path = r.pdf_web_url
    if path.startswith("http"):
        # Stored as a share URL — the caller can open it directly.
        return {"pdf_path": path}
    data = _od.download_from_path(path)
    if data is None:
        return _err(404, "PDF not found in OneDrive")
    from fastapi.responses import Response as _R
    return _R(content=data, media_type="application/pdf",
              headers={"Content-Disposition":
                       f'inline; filename="consolidated-{r.period}.pdf"'})
