"""Expense module routes (Phase 2) — Metfraa-only port of bsg-portal.

Pages:  /expense/                 module home (form tiles + my claims)
        /expense/form/{form_type} dynamic row-based form
        /expense/review           HR/admin queue (pending)
        /expense/review/{ref}     review one submission

APIs:   POST /expense/api/submit/{form_type}     multipart: data + bill:<n> files
        POST /expense/api/review/{ref}/approve   (advance → advance_approved)
        POST /expense/api/review/{ref}/return    reject-to-draft with changes_required
        GET  /expense/api/bill?path=…            bill proxy
        GET/POST/PATCH /expense/api/projects
        GET/POST /expense/api/level/{employee_id}   set L1/L2/L3 (admin)
        GET/POST /expense/api/payments              monthly payment mark-paid (admin)

Statuses: pending → approved | draft (returned; employee resubmits) ; advance:
pending → advance_approved → (settlement in Phase 2B).
"""
import io
import json
import logging
import random
import string
from datetime import datetime

import pytz
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, get_optional_user
from ..expense.policy import FORM_META, POLICY, PURPOSE_CATEGORIES
from ..expense.validators import validate
from ..models import (
    Employee, ExpenseAttachment, ExpenseEmployeeMeta, ExpenseMonthlyPayment,
    ExpenseProject, ExpenseSubmission,
)
from ..services import onedrive
from ..services.expense_artifacts import (
    append_expense_log, expense_root, generate_expense_pdf, submission_folder,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/expense", tags=["expense"])
templates = Jinja2Templates(directory="app/templates")

IST = pytz.timezone("Asia/Kolkata")
DEFAULT_PROJECTS = [("AMNS", "AMNS Site - Oragadam"), ("KGISL", "KGISL Auditorium"), ("PTJ", "Patanjali"), ("APL", "Apollo")]


def _ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


def _reference(code: str) -> str:
    d = datetime.now(IST).strftime("%y%m%d")
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"MET-{code}-{d}-{tail}"


def _level_of(db: Session, employee_id: int) -> str:
    m = db.query(ExpenseEmployeeMeta).filter(ExpenseEmployeeMeta.employee_id == employee_id).first()
    return m.level if m else "L1"


def _projects(db: Session) -> list[ExpenseProject]:
    if db.query(ExpenseProject).count() == 0:
        for code, name in DEFAULT_PROJECTS:
            db.add(ExpenseProject(code=code, name=name, is_active=True))
        db.commit()
    return db.query(ExpenseProject).order_by(ExpenseProject.name).all()


def _compress(data: bytes, mime: str) -> tuple[bytes, str]:
    if not mime.startswith("image/"):
        return data, mime  # PDFs etc. pass through
    try:
        from PIL import Image as PILImage

        img = PILImage.open(io.BytesIO(data))
        img.thumbnail((1600, 1600))
        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=70, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return data, mime


# ---------------------------------------------------------------- pages

@router.get("/", response_class=HTMLResponse)
@router.get("", response_class=HTMLResponse, include_in_schema=False)
def expense_home(request: Request, user: Employee | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    mine = (db.query(ExpenseSubmission)
            .filter(ExpenseSubmission.employee_id == user.id)
            .order_by(ExpenseSubmission.id.desc()).limit(10).all())
    pending = db.query(ExpenseSubmission).filter(ExpenseSubmission.status == "pending").count() if user.is_admin else 0
    return templates.TemplateResponse(request, "expense/home.html", {
        "user": user, "forms": FORM_META, "mine": mine,
        "level": _level_of(db, user.id), "pending": pending,
    })


@router.get("/form/{form_type}", response_class=HTMLResponse)
def expense_form_page(form_type: str, request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    meta = FORM_META.get(form_type)
    if not meta:
        raise HTTPException(status_code=404, detail="Unknown form")
    level = _level_of(db, user.id)
    policy_form = POLICY["forms"].get(meta["policy"], {})
    projects = [{"id": p.id, "name": p.name} for p in _projects(db) if p.is_active]
    # Resubmit-from-draft support: ?draft=<reference>
    draft = None
    ref = request.query_params.get("draft")
    if ref:
        d = db.query(ExpenseSubmission).filter(
            ExpenseSubmission.reference == ref,
            ExpenseSubmission.employee_id == user.id,
            ExpenseSubmission.status == "draft",
        ).first()
        if d:
            draft = {"reference": d.reference, "payload": d.payload, "changes_required": d.changes_required}
    return templates.TemplateResponse(request, "expense/form.html", {
        "user": user, "form_type": form_type, "meta": meta, "level": level,
        "policy_form": policy_form, "policy_json": json.dumps(policy_form),
        "projects_json": json.dumps(projects),
        "purposes_json": json.dumps(PURPOSE_CATEGORIES),
        "draft_json": json.dumps(draft),
        "current_period": datetime.now(IST).strftime("%Y-%m"),
    })


@router.get("/review", response_class=HTMLResponse)
def expense_review_queue(request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    subs = (db.query(ExpenseSubmission)
            .filter(ExpenseSubmission.status == "pending")
            .order_by(ExpenseSubmission.id.asc()).all())
    return templates.TemplateResponse(request, "expense/review_queue.html", {"user": user, "subs": subs, "forms": FORM_META})


@router.get("/review/{reference}", response_class=HTMLResponse)
def expense_review_one(reference: str, request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = db.query(ExpenseSubmission).filter(ExpenseSubmission.reference == reference).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Not found")
    if not user.is_admin and sub.employee_id != user.id:
        raise HTTPException(status_code=403, detail="Not yours")
    return templates.TemplateResponse(request, "expense/review.html", {
        "user": user, "sub": sub, "meta": FORM_META.get(sub.form_type, {}),
        "payload_json": json.dumps(sub.payload or {}), "is_admin": user.is_admin,
    })


# ---------------------------------------------------------------- submit

@router.post("/api/submit/{form_type}")
async def expense_submit(form_type: str, request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    meta = FORM_META.get(form_type)
    if not meta:
        raise HTTPException(status_code=404, detail="Unknown form")

    form_data = await request.form()
    try:
        raw = json.loads(form_data.get("data") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid form data JSON")

    # Gather bill files first (DTR needs to know which rows have bills)
    bills: list[tuple[str, bytes, str, str]] = []   # (field_key, bytes, mime, filename)
    for key, value in form_data.multi_items():
        if key.startswith("bill:") and hasattr(value, "read"):
            data = await value.read()
            if data:
                bills.append((key[len("bill:"):], data, value.content_type or "application/octet-stream",
                              value.filename or "bill"))
    if form_type == "met_dtr":
        with_bill = {k for k, *_ in bills if k.isdigit()}
        for i, e in enumerate(raw.get("entries") or []):
            (e or {})["has_bill"] = str(i) in with_bill

    level = _level_of(db, user.id)
    ok, payload_or_err, total = validate(form_type, raw, level)
    if not ok:
        raise HTTPException(status_code=400, detail=payload_or_err)
    payload = payload_or_err

    resubmit_ref = form_data.get("resubmit_reference")
    if resubmit_ref:
        sub = db.query(ExpenseSubmission).filter(
            ExpenseSubmission.reference == resubmit_ref,
            ExpenseSubmission.employee_id == user.id,
            ExpenseSubmission.status == "draft",
        ).first()
        if not sub:
            raise HTTPException(status_code=404, detail="Draft not found for resubmission")
        sub.payload = payload
        sub.total_amount = total
        sub.period = payload.get("period") or sub.period
        sub.status = "pending"
        sub.changes_required = None
    else:
        sub = ExpenseSubmission(
            reference=_reference(meta["code"]),
            employee_id=user.id, employee_name=user.name, employee_email=user.email,
            employee_level=level, form_type=form_type,
            period=payload.get("period") or None,
            payload=payload, total_amount=total, status="pending",
            submitted_at_ist=_ist(),
        )
        db.add(sub)
        db.flush()

    # Upload bills to OneDrive
    folder = f"{submission_folder(sub)}/Bills"
    try:
        for key, data, mime, fname in bills:
            data, mime = _compress(data, mime)
            ext = ".jpg" if mime == "image/jpeg" else ("." + (fname.rsplit(".", 1)[-1] if "." in fname else "bin"))
            row_idx = int(key) if key.isdigit() else None
            safe = f"{'row' + key if key.isdigit() else key}_{len(sub.attachments) + 1}{ext}"
            path = f"{folder}/{safe}"
            info = onedrive.upload_to_path(data, path, mime)
            db.add(ExpenseAttachment(
                submission_id=sub.id, filename=fname, onedrive_path=path,
                web_url=info.get("webUrl"), mime_type=mime, size_bytes=len(data), row_idx=row_idx,
            ))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        log.error(f"[expense-submit] bill upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Bill upload to OneDrive failed — please retry")

    db.commit()
    return {"ok": True, "reference": sub.reference, "total": total, "status": "pending",
            "message": f"{meta['title']} submitted — ₹{total:,.2f} claimed, awaiting HR review."}


# ---------------------------------------------------------------- bill proxy

@router.get("/api/bill")
def expense_bill_proxy(path: str, user: Employee = Depends(get_current_user)):
    root = expense_root()
    clean = path.strip("/")
    if not clean.startswith(root + "/") or ".." in clean:
        raise HTTPException(status_code=400, detail="Invalid path")
    data = onedrive.download_from_path(clean)
    if data is None:
        raise HTTPException(status_code=404, detail="Not found")
    mt = "application/pdf" if clean.lower().endswith(".pdf") else "image/jpeg"
    return Response(content=data, media_type=mt, headers={"Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------- review actions

@router.post("/api/review/{reference}/approve")
async def expense_approve(reference: str, request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    sub = db.query(ExpenseSubmission).filter(ExpenseSubmission.reference == reference).with_for_update().first()
    if not sub:
        raise HTTPException(status_code=404, detail="Not found")
    if sub.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already {sub.status}")

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    sub.status = "advance_approved" if sub.form_type == "met_advance" else "approved"
    sub.reviewed_by = user.email or user.name
    sub.reviewed_at_ist = _ist()
    sub.review_note = (body.get("note") or "").strip() or None

    meta = FORM_META.get(sub.form_type, {})
    pdf_link = None
    try:
        pdf_bytes = generate_expense_pdf(sub, meta.get("title", sub.form_type))
        info = onedrive.upload_to_path(pdf_bytes, f"{submission_folder(sub)}/{sub.reference}.pdf", "application/pdf")
        pdf_link = info.get("webUrl")
        sub.pdf_web_url = pdf_link
    except Exception as e:
        log.error(f"[expense-approve] PDF failed: {e}", exc_info=True)
    try:
        bill_links = [a.web_url for a in sub.attachments if a.web_url]
        append_expense_log(sub, meta.get("code", "X"), bill_links, pdf_link)
    except Exception as e:
        log.error(f"[expense-approve] log failed: {e}", exc_info=True)

    db.commit()
    return {"ok": True, "status": sub.status, "pdf": pdf_link}


@router.post("/api/review/{reference}/return")
async def expense_return(reference: str, request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    """Reject-to-draft: employee gets it back with a 'what to change' note."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    sub = db.query(ExpenseSubmission).filter(ExpenseSubmission.reference == reference).with_for_update().first()
    if not sub:
        raise HTTPException(status_code=404, detail="Not found")
    if sub.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already {sub.status}")
    body = await request.json()
    changes = (body.get("changes_required") or "").strip()
    if not changes:
        raise HTTPException(status_code=400, detail="Describe what needs to change")
    sub.status = "draft"
    sub.changes_required = changes
    sub.returned_at_ist = _ist()
    sub.reviewed_by = user.email or user.name
    sub.reviewed_at_ist = _ist()
    db.commit()
    return {"ok": True, "status": "draft"}


# ---------------------------------------------------------------- projects / levels / payments

@router.get("/api/projects")
def expense_projects(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": p.id, "code": p.code, "name": p.name, "is_active": p.is_active} for p in _projects(db)]


@router.post("/api/projects")
async def expense_add_project(request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    p = ExpenseProject(code=(body.get("code") or "").strip() or None, name=name, is_active=True)
    db.add(p)
    db.commit()
    return {"ok": True, "id": p.id}


@router.patch("/api/projects/{project_id}")
async def expense_toggle_project(project_id: int, request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    p = db.query(ExpenseProject).filter(ExpenseProject.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    body = await request.json()
    if "is_active" in body:
        p.is_active = bool(body["is_active"])
    if body.get("name"):
        p.name = str(body["name"]).strip()
    db.commit()
    return {"ok": True}


@router.post("/api/level/{employee_id}")
async def expense_set_level(employee_id: int, request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    body = await request.json()
    level = (body.get("level") or "").strip().upper()
    if level not in ("L1", "L2", "L3"):
        raise HTTPException(status_code=400, detail="Level must be L1, L2 or L3")
    m = db.query(ExpenseEmployeeMeta).filter(ExpenseEmployeeMeta.employee_id == employee_id).first()
    if m:
        m.level = level
    else:
        db.add(ExpenseEmployeeMeta(employee_id=employee_id, level=level))
    db.commit()
    return {"ok": True, "level": level}


@router.get("/api/payments")
def expense_payments(year: int, month: int, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    period = f"{year:04d}-{month:02d}"
    subs = (db.query(ExpenseSubmission)
            .filter(ExpenseSubmission.period == period,
                    ExpenseSubmission.status.in_(["approved", "advance_approved", "settled"]))
            .all())
    totals: dict[int, dict] = {}
    for s in subs:
        t = totals.setdefault(s.employee_id, {"employee_id": s.employee_id, "name": s.employee_name,
                                              "total": 0.0, "count": 0})
        t["total"] = round(t["total"] + s.total_amount, 2)
        t["count"] += 1
    paid = {p.employee_id: p for p in db.query(ExpenseMonthlyPayment)
            .filter(ExpenseMonthlyPayment.year == year, ExpenseMonthlyPayment.month == month).all()}
    for t in totals.values():
        p = paid.get(t["employee_id"])
        t["paid"] = bool(p)
        t["paid_at"] = p.paid_at_ist if p else None
    return list(totals.values())


@router.post("/api/payments")
async def expense_mark_paid(request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    body = await request.json()
    try:
        employee_id, year, month = int(body["employee_id"]), int(body["year"]), int(body["month"])
        amount = float(body["amount"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="employee_id, year, month, amount required")
    if db.query(ExpenseMonthlyPayment).filter_by(employee_id=employee_id, year=year, month=month).first():
        raise HTTPException(status_code=409, detail="Already marked paid for this month")
    db.add(ExpenseMonthlyPayment(employee_id=employee_id, year=year, month=month,
                                 amount_paid=amount, paid_by=user.email or user.name, paid_at_ist=_ist()))
    db.commit()
    return {"ok": True}
