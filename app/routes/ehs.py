"""EHS module routes (Phase 1).

Pages:   /ehs/                (module home — form grid + my recent submissions)
         /ehs/form/{form_id}  (dynamic form rendered from the registry)
         /ehs/submissions     (my submissions / all for approvers)
         /ehs/approvals       (pending queue — approvers only)
         /ehs/approvals/{id}  (review one pending submission)

APIs:    POST /ehs/api/forms/{form_id}          submit (multipart, photos)
         GET  /ehs/api/photo?path=...           photo proxy (review page)
         POST /ehs/api/approvals/{id}/approve   approve (+optional edits)
         POST /ehs/api/approvals/{id}/reject    reject (reason required)
         GET/POST/PATCH /ehs/api/projects       project dropdown management

Storage: DB (ehs_submissions) is source of truth. Photos upload to OneDrive
under Metfraa-EHS/_Pending/... at submit time and move to the form's
Reports/YYYY/MM folder on approval — identical layout to the old Node app,
plus the same per-form _MasterLog.xlsx and approval PDFs.
"""
import io
import json
import logging
import os
import random
from datetime import datetime

import pytz
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from starlette.datastructures import UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db
from fastapi.templating import Jinja2Templates

from ..deps import get_current_user, get_optional_user

templates = Jinja2Templates(directory="app/templates")
from ..access import get_access
from ..ehs.forms import ALL_FORMS, FORMS_BY_ID, INSPECTORS
from ..ehs.forms import is_approver as _legacy_approver
from ..models import EHSProject, EHSSubmission, Employee
from ..services import onedrive
from ..services.ehs_excel_log import append_to_master_log, ehs_root
from ..services.ehs_pdf import generate_ehs_pdf
from ..services.portal_notify import notify_ehs_decision, notify_ehs_submitted

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ehs", tags=["ehs"])

IST = pytz.timezone("Asia/Kolkata")

DEFAULT_PROJECTS = ["AMNS Site - Oragadam", "KGISL Auditorium", "Patanjali", "Apollo"]


# ---------------------------------------------------------------- helpers

def _now_ist() -> datetime:
    return datetime.now(IST)


def _ist_string(dt: datetime | None = None) -> str:
    return (dt or _now_ist()).strftime("%Y-%m-%d %H:%M:%S")


def _gen_submission_id(form: dict) -> str:
    p = _now_ist()
    return f"{form['code']}-{p.strftime('%Y%m%d')}-{p.strftime('%H%M%S')}-{random.randint(1000, 9999)}"


def _compress_image(data: bytes) -> bytes:
    """JPEG, max 1600px, q70 — keeps every upload well under Graph's 4 MB simple-upload cap."""
    try:
        from PIL import Image as PILImage

        img = PILImage.open(io.BytesIO(data))
        img.thumbnail((1600, 1600))
        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=70, optimize=True)
        return out.getvalue()
    except Exception:
        return data


def _pending_photo_folder(form_id: str, submission_id: str) -> str:
    return f"{ehs_root()}/_Pending/{form_id}/{submission_id}/photos"


def _active_projects(db: Session) -> list[str]:
    if db.query(EHSProject).count() == 0:
        for name in DEFAULT_PROJECTS:
            db.add(EHSProject(name=name, active=True, aliases=[], created_by="system"))
        db.commit()
    return [p.name for p in db.query(EHSProject).filter(EHSProject.active == True).order_by(EHSProject.name).all()]  # noqa: E712


def _is_approver(db: Session, user: Employee) -> bool:
    return get_access(db, user).can_admin_ehs or _legacy_approver(user)


def _require_approver(db: Session, user: Employee) -> None:
    if not _is_approver(db, user):
        raise HTTPException(status_code=403, detail="EHS Admin access required")


def _require_module(db: Session, user: Employee) -> None:
    acc = get_access(db, user)
    if not (acc.ehs_access or acc.can_admin_ehs):
        raise HTTPException(status_code=403, detail="You don't have access to the EHS module")


# ---------------------------------------------------------------- pages

@router.get("/", response_class=HTMLResponse)
@router.get("", response_class=HTMLResponse, include_in_schema=False)
def ehs_home(request: Request, user: Employee | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    my_recent = (
        db.query(EHSSubmission)
        .filter(EHSSubmission.submitted_by_id == user.id)
        .order_by(EHSSubmission.id.desc())
        .limit(5)
        .all()
    )
    _require_module(db, user)
    pending_count = 0
    if _is_approver(db, user):
        pending_count = db.query(EHSSubmission).filter(EHSSubmission.status == "pending").count()
    return templates.TemplateResponse(request, "ehs/home.html", {
        "user": user,
        "forms": ALL_FORMS,
        "my_recent": my_recent,
        "is_approver": _is_approver(db, user),
        "pending_count": pending_count,
    })


@router.get("/form/{form_id}", response_class=HTMLResponse)
def ehs_form_page(form_id: str, request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_module(db, user)
    form = FORMS_BY_ID.get(form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Unknown form")
    today = _now_ist().strftime("%Y-%m-%d")
    now_hm = _now_ist().strftime("%H:%M")
    return templates.TemplateResponse(request, "ehs/form.html", {
        "user": user,
        "form": form,
        "form_json": json.dumps(form),
        "projects": _active_projects(db),
        "inspectors": INSPECTORS,
        "today": today,
        "now_hm": now_hm,
    })


@router.get("/submissions", response_class=HTMLResponse)
def ehs_submissions_page(request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(EHSSubmission)
    _require_module(db, user)
    approver = _is_approver(db, user)
    if not approver:
        q = q.filter(EHSSubmission.submitted_by_id == user.id)
    subs = q.order_by(EHSSubmission.id.desc()).limit(200).all()
    return templates.TemplateResponse(request, "ehs/submissions.html", {
        "user": user, "subs": subs, "is_approver": approver,
    })


@router.get("/approvals", response_class=HTMLResponse)
def ehs_approvals_page(request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_approver(db, user)
    subs = (
        db.query(EHSSubmission)
        .filter(EHSSubmission.status == "pending")
        .order_by(EHSSubmission.id.asc())
        .all()
    )
    return templates.TemplateResponse(request, "ehs/approvals.html", {"user": user, "subs": subs})


@router.get("/approvals/{sub_id}", response_class=HTMLResponse)
def ehs_review_page(sub_id: str, request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_approver(db, user)
    sub = db.query(EHSSubmission).filter(EHSSubmission.submission_id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    form = FORMS_BY_ID.get(sub.form_id)
    if not form:
        raise HTTPException(status_code=500, detail=f"Form config missing for {sub.form_id}")
    return templates.TemplateResponse(request, "ehs/review.html", {
        "user": user,
        "sub": sub,
        "form": form,
        "form_json": json.dumps(form),
        "sub_json": json.dumps({
            "submissionId": sub.submission_id,
            "fields": sub.fields or {},
            "checklist": sub.checklist or [],
            "photos": sub.photos or {"fields": {}, "checklist": {}},
            "status": sub.status,
        }),
    })


# ---------------------------------------------------------------- submit API

@router.post("/api/forms/{form_id}")
async def ehs_submit(form_id: str, request: Request, bg: BackgroundTasks, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_module(db, user)
    form = FORMS_BY_ID.get(form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Unknown form")

    form_data = await request.form()
    try:
        data = json.loads(form_data.get("data") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid form data JSON")

    fields = data.get("fields") or {}
    checklist = data.get("checklist") or []

    # Validate required non-photo fields
    missing = [
        f["label"] for f in form["fields"]
        if f.get("required") and f["type"] != "photo" and not str(fields.get(f["key"], "") or "").strip()
    ]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing)}")

    submission_id = _gen_submission_id(form)

    # Collect photo uploads: field name "photo:<key>" or "photo:checklist:<idx>"
    photos_by_key: dict[str, list[bytes]] = {}
    for key, value in form_data.multi_items():
        if not key.startswith("photo:") or not hasattr(value, "read"):
            continue
        raw = await value.read()
        if not raw:
            continue
        photos_by_key.setdefault(key[len("photo:"):], []).append(_compress_image(raw))

    # Required photo fields must be present
    missing_photos = [
        f["label"] for f in form["fields"]
        if f.get("required") and f["type"] == "photo" and not photos_by_key.get(f["key"])
    ]
    if missing_photos:
        raise HTTPException(status_code=400, detail=f"Missing required photos: {', '.join(missing_photos)}")

    # Upload photos to the pending folder
    photo_index: dict = {"fields": {}, "checklist": {}}
    folder = _pending_photo_folder(form["id"], submission_id)
    try:
        for key, buffers in photos_by_key.items():
            safe_key = "".join(c if (c.isalnum() or c in "_-") else "_" for c in key.replace(":", "-"))
            for i, buf in enumerate(buffers, start=1):
                fname = f"{safe_key}_{i}.jpg"
                path = f"{folder}/{fname}"
                info = onedrive.upload_to_path(buf, path, "image/jpeg")
                entry = {"filename": fname, "path": path, "webUrl": info.get("webUrl")}
                if key.startswith("checklist:"):
                    idx = key.split(":", 1)[1]
                    photo_index["checklist"].setdefault(idx, []).append(entry)
                else:
                    photo_index["fields"].setdefault(key, []).append(entry)
    except Exception as e:
        log.error(f"[ehs-submit] OneDrive upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Photo upload to OneDrive failed — please retry")

    sub = EHSSubmission(
        submission_id=submission_id,
        form_id=form["id"],
        form_code=form["code"],
        form_title=form["title"],
        submitted_by_id=user.id,
        submitted_by_name=user.name,
        submitted_by_email=user.email,
        submitted_at_ist=_ist_string(),
        fields=fields,
        checklist=checklist,
        photos=photo_index,
        status="pending",
    )
    db.add(sub)
    db.commit()
    notify_ehs_submitted(bg, sub)

    return {
        "ok": True,
        "submissionId": submission_id,
        "status": "pending",
        "message": f"{form['title']} submitted for approval.",
    }


# ---------------------------------------------------------------- photo proxy

@router.get("/api/photo")
def ehs_photo_proxy(path: str, user: Employee = Depends(get_current_user)):
    """Stream a OneDrive photo for the review/submission pages. Path must stay inside the EHS root."""
    root = ehs_root()
    clean = path.strip("/")
    if not clean.startswith(root + "/") or ".." in clean:
        raise HTTPException(status_code=400, detail="Invalid photo path")
    data = onedrive.download_from_path(clean)
    if data is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------- approval APIs

def _compute_edits(form: dict, sub, new_fields: dict, new_checklist: list) -> str:
    parts = []
    old_fields = sub.fields or {}
    for f in form["fields"]:
        if f["type"] == "photo":
            continue
        old_v = str(old_fields.get(f["key"], "") or "")
        new_v = str(new_fields.get(f["key"], "") or "")
        if old_v != new_v:
            parts.append(f"{f['label']}: '{old_v}' → '{new_v}'")
    for i, _param in enumerate(form.get("checklist") or []):
        old_i = (sub.checklist or [{}] * (i + 1))[i] if i < len(sub.checklist or []) else {}
        new_i = new_checklist[i] if i < len(new_checklist) else {}
        for k in ("result", "remarks"):
            ov, nv = str((old_i or {}).get(k, "") or ""), str((new_i or {}).get(k, "") or "")
            if ov != nv:
                parts.append(f"Checklist #{i + 1} {k}: '{ov}' → '{nv}'")
    return "; ".join(parts)


@router.post("/api/approvals/{sub_id}/approve")
async def ehs_approve(sub_id: str, request: Request, bg: BackgroundTasks, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_approver(db, user)
    sub = db.query(EHSSubmission).filter(EHSSubmission.submission_id == sub_id).with_for_update().first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already {sub.status}")

    form = FORMS_BY_ID.get(sub.form_id)
    if not form:
        raise HTTPException(status_code=500, detail=f"Form config missing for {sub.form_id}")

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    new_fields = body.get("fields") or sub.fields or {}
    new_checklist = body.get("checklist") or sub.checklist or []

    edits = _compute_edits(form, sub, new_fields, new_checklist)

    sub.fields = new_fields
    sub.checklist = new_checklist
    sub.status = "approved"
    sub.reviewed_by_name = user.name
    sub.reviewed_by_email = user.email
    sub.reviewed_at_ist = _ist_string()
    sub.edits_made = edits or None

    # ---- Move photos: _Pending → <form.folder>/Reports/YYYY/MM/Photos/<subId>/
    now = _now_ist()
    dest_base = f"{ehs_root()}/{form['folder']}/Reports/{now.strftime('%Y')}/{now.strftime('%m')}"
    photo_links: dict = {"fields": {}, "checklist": {}}
    photo_buffers: dict = {"fields": {}, "checklist": {}}
    new_index: dict = {"fields": {}, "checklist": {}}

    photos = sub.photos or {"fields": {}, "checklist": {}}
    moves = []
    for key, entries in (photos.get("fields") or {}).items():
        for e in entries:
            moves.append(("fields", key, e))
    for idx, entries in (photos.get("checklist") or {}).items():
        for e in entries:
            moves.append(("checklist", idx, e))

    for kind, key, e in moves:
        src = e.get("path")
        if not src:
            continue
        try:
            data = onedrive.download_from_path(src)
            moved = onedrive.move_item(src, f"{dest_base}/Photos/{sub.submission_id}")
            web = (moved or {}).get("webUrl") or e.get("webUrl") or ""
            new_path = f"{dest_base}/Photos/{sub.submission_id}/{e.get('filename')}"
        except Exception as ex:
            log.error(f"[ehs-approve] photo move failed for {src}: {ex}")
            data, web, new_path = None, e.get("webUrl") or "", src
        entry = {"filename": e.get("filename"), "path": new_path, "webUrl": web}
        new_index[kind].setdefault(key, []).append(entry)
        photo_links[kind].setdefault(key if kind == "fields" else _int_or(key), []).append(web)
        if data:
            photo_buffers[kind].setdefault(key if kind == "fields" else _int_or(key), []).append(data)

    sub.photos = new_index

    # ---- Generate + upload PDF
    pdf_link = None
    try:
        pdf_bytes = generate_ehs_pdf(form, sub, photo_buffers)
        safe_title = form["title"].replace(" ", "-").replace("/", "-")
        pdf_name = f"{sub.submission_id}_{safe_title}.pdf"
        info = onedrive.upload_to_path(pdf_bytes, f"{dest_base}/{pdf_name}", "application/pdf")
        pdf_link = info.get("webUrl")
        sub.pdf_web_url = pdf_link
    except Exception as ex:
        log.error(f"[ehs-approve] PDF generation/upload failed: {ex}", exc_info=True)

    # ---- Master log
    try:
        append_to_master_log(form, sub, photo_links, pdf_link)
    except Exception as ex:
        log.error(f"[ehs-approve] master log append failed: {ex}", exc_info=True)

    # ---- Clean pending folder
    try:
        onedrive.delete_by_path(f"{ehs_root()}/_Pending/{form['id']}/{sub.submission_id}")
    except Exception:
        pass

    db.commit()
    notify_ehs_decision(bg, sub)
    return {"ok": True, "status": "approved", "pdf": pdf_link, "edits": edits}


def _int_or(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


@router.post("/api/approvals/{sub_id}/reject")
async def ehs_reject(sub_id: str, request: Request, bg: BackgroundTasks, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_approver(db, user)
    sub = db.query(EHSSubmission).filter(EHSSubmission.submission_id == sub_id).with_for_update().first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already {sub.status}")

    form = FORMS_BY_ID.get(sub.form_id)
    body = await request.json()
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A rejection reason is required")

    sub.status = "rejected"
    sub.reviewed_by_name = user.name
    sub.reviewed_by_email = user.email
    sub.reviewed_at_ist = _ist_string()
    sub.reject_reason = reason

    if form:
        try:
            append_to_master_log(form, sub, {"fields": {}, "checklist": {}}, None)
        except Exception as ex:
            log.error(f"[ehs-reject] master log append failed: {ex}", exc_info=True)
        try:
            onedrive.delete_by_path(f"{ehs_root()}/_Pending/{form['id']}/{sub.submission_id}")
        except Exception:
            pass

    db.commit()
    notify_ehs_decision(bg, sub)
    return {"ok": True, "status": "rejected"}


# ---------------------------------------------------------------- projects API

@router.get("/api/projects")
def ehs_projects(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _active_projects(db)  # seeds defaults on first call
    return [
        {"id": p.id, "name": p.name, "active": p.active}
        for p in db.query(EHSProject).order_by(EHSProject.name).all()
    ]


@router.post("/api/projects")
async def ehs_add_project(request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_approver(db, user)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name required")
    if db.query(EHSProject).filter(EHSProject.name == name).first():
        raise HTTPException(status_code=409, detail="Project already exists")
    p = EHSProject(name=name, active=True, aliases=[], created_by=user.email or user.employee_code)
    db.add(p)
    db.commit()
    return {"ok": True, "id": p.id}


@router.patch("/api/projects/{project_id}")
async def ehs_toggle_project(project_id: int, request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_approver(db, user)
    p = db.query(EHSProject).filter(EHSProject.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    body = await request.json()
    if "active" in body:
        p.active = bool(body["active"])
    if body.get("name"):
        p.name = str(body["name"]).strip()
    db.commit()
    return {"ok": True}
