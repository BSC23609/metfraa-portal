"""Site Visit CRM routes.

- Anyone with login can create/submit visits (Q: "anyone can fill")
- Draft mode: employee saves incrementally, no email/PDF yet
- Submit: locks the record, generates PDF, uploads to OneDrive, emails VP+admin+arasu
- Q2: NO EDIT AFTER SUBMIT — any PUT to submitted visit is 403
- Employees see their own visits; admins see all
"""
import base64
import io
import os
import re
from datetime import date, datetime
from typing import Optional

from fastapi import (
    APIRouter, Depends, HTTPException, Request, UploadFile, File, Form,
)
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user_ready, require_admin
from ..models import AuditLog, Employee, SiteVisit, SiteVisitPhoto

router = APIRouter(prefix="/site-visits", tags=["site-visits"])
templates = Jinja2Templates(directory="app/templates")

MAX_PHOTOS_PER_VISIT = 10
MAX_PHOTO_SIZE_BYTES = 8 * 1024 * 1024  # 8 MB per photo
ALLOWED_MIME_PREFIXES = ("image/",)


# ============================================================
# Helpers
# ============================================================

def _generate_report_id() -> str:
    """Format: SV-YYYYMMDD-NNNN"""
    import random
    return f"SV-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"


def _sanitize_filename_component(s: str) -> str:
    """Strip spaces + special chars from a string suitable for filenames."""
    s = re.sub(r"[^\w\s-]", "", (s or "").strip())
    s = re.sub(r"[\s_-]+", "_", s).strip("_")
    return s[:60] if s else "unnamed"


def _pdf_filename(visit: SiteVisit) -> str:
    """Build: SiteVisit_YYYY-MM-DD_METxx_<Customer>.pdf"""
    date_str = (visit.visit_date or datetime.now().date()).strftime("%Y-%m-%d")
    code = "OPEN"
    if visit.employee_id:
        # We don't have a query here; caller passes emp code separately if needed
        pass
    company = _sanitize_filename_component(visit.company_name or "customer")
    return f"SiteVisit_{date_str}_{code}_{company}.pdf"


def _pdf_filename_with_code(visit: SiteVisit, employee_code: str) -> str:
    date_str = (visit.visit_date or datetime.now().date()).strftime("%Y-%m-%d")
    company = _sanitize_filename_component(visit.company_name or "customer")
    code = _sanitize_filename_component(employee_code or "OPEN")
    return f"SiteVisit_{date_str}_{code}_{company}.pdf"


def _ensure_owner_or_admin(visit: SiteVisit, user: Employee) -> None:
    if user.is_admin:
        return
    if visit.employee_id != user.id:
        raise HTTPException(403, "Not your visit")


def _visit_to_dict(visit: SiteVisit, include_photos: bool = True) -> dict:
    return {
        "id": visit.id,
        "report_id": visit.report_id,
        "employee_id": visit.employee_id,
        "visit_date": visit.visit_date.isoformat() if visit.visit_date else None,
        "visited_by": visit.visited_by or "",
        "company_name": visit.company_name or "",
        "contact_person": visit.contact_person or "",
        "contact_phone": visit.contact_phone or "",
        "contact_email": visit.contact_email or "",
        "site_address": visit.site_address or "",
        "category": visit.category or "",
        "details_json": visit.details_json or {},
        "discussion_notes": visit.discussion_notes or "",
        "next_steps": visit.next_steps or "",
        "followup_date": visit.followup_date.isoformat() if visit.followup_date else None,
        "priority": visit.priority or "",
        "status": visit.status,
        "created_at": visit.created_at.isoformat() if visit.created_at else None,
        "last_edited_at": visit.last_edited_at.isoformat() if visit.last_edited_at else None,
        "submitted_at": visit.submitted_at.isoformat() if visit.submitted_at else None,
        "pdf_filename": visit.pdf_filename,
        "pdf_onedrive_url": visit.pdf_onedrive_url,
        "photos": [
            {
                "id": p.id,
                "sequence": p.sequence,
                "caption": p.caption or "",
                "original_filename": p.original_filename,
                "size_bytes": p.size_bytes,
                "thumbnail_b64": p.thumbnail_b64 if include_photos else None,
            }
            for p in sorted(visit.photos, key=lambda x: x.sequence)
        ] if include_photos else [],
    }


# ============================================================
# Screens
# ============================================================

@router.get("/", response_class=HTMLResponse)
def site_visits_home(
    request: Request,
    user: Employee = Depends(get_current_user_ready),
):
    """List of the current user's visits + button to create a new one."""
    return templates.TemplateResponse(
        request,
        "site_visits_list.html",
        {"user": user, "is_admin": user.is_admin},
    )


@router.get("/new", response_class=HTMLResponse)
def new_site_visit_page(
    request: Request,
    user: Employee = Depends(get_current_user_ready),
):
    """Blank site visit form."""
    return templates.TemplateResponse(
        request,
        "site_visit_form.html",
        {"user": user, "visit_id": None, "mode": "new"},
    )


@router.get("/{visit_id}", response_class=HTMLResponse)
def edit_site_visit_page(
    visit_id: int,
    request: Request,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Open existing draft OR view submitted visit (read-only)."""
    visit = db.query(SiteVisit).filter_by(id=visit_id).first()
    if not visit:
        raise HTTPException(404, "Visit not found")
    _ensure_owner_or_admin(visit, user)
    mode = "view" if visit.status == "submitted" else "edit"
    return templates.TemplateResponse(
        request,
        "site_visit_form.html",
        {"user": user, "visit_id": visit_id, "mode": mode},
    )


# ============================================================
# API — list
# ============================================================

@router.get("/api/list")
def list_visits(
    all_employees: bool = False,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Return a list of visits.

    - Employees always see only their own.
    - Admins see their own by default; pass ?all_employees=true for the whole org.
    """
    q = db.query(SiteVisit).order_by(SiteVisit.created_at.desc())
    if not (user.is_admin and all_employees):
        q = q.filter(SiteVisit.employee_id == user.id)

    visits = q.limit(200).all()

    # Preload employees so we can annotate rows without N+1
    emp_ids = list({v.employee_id for v in visits if v.employee_id})
    emp_map = {}
    if emp_ids:
        emps = db.query(Employee).filter(Employee.id.in_(emp_ids)).all()
        emp_map = {e.id: e for e in emps}

    out = []
    for v in visits:
        emp = emp_map.get(v.employee_id) if v.employee_id else None
        n_photos = len(v.photos)
        out.append({
            "id": v.id,
            "report_id": v.report_id,
            "visit_date": v.visit_date.isoformat() if v.visit_date else None,
            "company_name": v.company_name or "",
            "contact_person": v.contact_person or "",
            "category": v.category or "",
            "priority": v.priority or "",
            "status": v.status,
            "employee_name": emp.name if emp else "—",
            "employee_code": emp.employee_code if emp else "—",
            "n_photos": n_photos,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "submitted_at": v.submitted_at.isoformat() if v.submitted_at else None,
            "followup_date": v.followup_date.isoformat() if v.followup_date else None,
        })
    return out


# ============================================================
# API — single visit
# ============================================================

@router.get("/api/{visit_id}")
def get_visit(
    visit_id: int,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    visit = db.query(SiteVisit).filter_by(id=visit_id).first()
    if not visit:
        raise HTTPException(404, "Visit not found")
    _ensure_owner_or_admin(visit, user)
    return _visit_to_dict(visit)


# ============================================================
# API — create draft
# ============================================================

@router.post("/api/create")
async def create_draft(
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Create a blank draft. Returns the new visit ID + report_id."""
    # Ensure unique report_id (collision extremely unlikely but retry once)
    for _ in range(5):
        rid = _generate_report_id()
        if not db.query(SiteVisit).filter_by(report_id=rid).first():
            break
    else:
        raise HTTPException(500, "Could not generate unique report ID")

    visit = SiteVisit(
        report_id=rid,
        employee_id=user.id,
        status="draft",
    )
    db.add(visit)
    db.add(AuditLog(
        actor_code=user.employee_code,
        actor_email=user.email,
        action="site_visit_draft_created",
        details={"report_id": rid},
    ))
    db.commit()
    db.refresh(visit)
    return {"success": True, "visit_id": visit.id, "report_id": visit.report_id}


# ============================================================
# API — save draft (PUT)
# ============================================================

@router.put("/api/{visit_id}")
async def save_draft(
    visit_id: int,
    request: Request,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Save/update draft fields. Refused if visit is already submitted (Q2)."""
    visit = db.query(SiteVisit).filter_by(id=visit_id).first()
    if not visit:
        raise HTTPException(404, "Visit not found")
    _ensure_owner_or_admin(visit, user)

    if visit.status == "submitted":
        raise HTTPException(403, "This visit has been submitted and cannot be edited.")

    body = await request.json()

    # Field-by-field update (all optional)
    def _set(field: str, val, cast=None):
        if val is None:
            setattr(visit, field, None)
            return
        if cast:
            try:
                val = cast(val)
            except (TypeError, ValueError):
                return
        setattr(visit, field, val)

    if "visit_date" in body:
        d = body.get("visit_date")
        try:
            visit.visit_date = date.fromisoformat(d) if d else None
        except ValueError:
            pass
    if "visited_by" in body: visit.visited_by = (body["visited_by"] or "").strip() or None
    if "company_name" in body: visit.company_name = (body["company_name"] or "").strip() or None
    if "contact_person" in body: visit.contact_person = (body["contact_person"] or "").strip() or None
    if "contact_phone" in body: visit.contact_phone = (body["contact_phone"] or "").strip() or None
    if "contact_email" in body: visit.contact_email = (body["contact_email"] or "").strip() or None
    if "site_address" in body: visit.site_address = (body["site_address"] or "").strip() or None

    if "category" in body:
        cat = (body["category"] or "").strip().lower()
        if cat not in ("", "newshed", "reroof", "extension", "other"):
            raise HTTPException(400, "Invalid category")
        visit.category = cat or None

    if "details_json" in body:
        visit.details_json = body["details_json"] if isinstance(body["details_json"], dict) else None

    if "discussion_notes" in body: visit.discussion_notes = (body["discussion_notes"] or "").strip() or None
    if "next_steps" in body: visit.next_steps = (body["next_steps"] or "").strip() or None

    if "followup_date" in body:
        d = body.get("followup_date")
        try:
            visit.followup_date = date.fromisoformat(d) if d else None
        except ValueError:
            pass

    if "priority" in body:
        p = (body["priority"] or "").strip()
        if p not in ("", "Low", "Medium", "High"):
            raise HTTPException(400, "Invalid priority")
        visit.priority = p or None

    visit.last_edited_at = datetime.utcnow()
    db.commit()
    db.refresh(visit)
    return {"success": True, "visit": _visit_to_dict(visit)}


# ============================================================
# API — upload photo
# ============================================================

@router.post("/api/{visit_id}/photos")
async def upload_photo(
    visit_id: int,
    file: UploadFile = File(...),
    caption: str = Form(""),
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Attach a photo to a visit (draft only)."""
    visit = db.query(SiteVisit).filter_by(id=visit_id).first()
    if not visit:
        raise HTTPException(404, "Visit not found")
    _ensure_owner_or_admin(visit, user)
    if visit.status == "submitted":
        raise HTTPException(403, "Visit already submitted — cannot add photos.")

    # Limits
    if len(visit.photos) >= MAX_PHOTOS_PER_VISIT:
        raise HTTPException(400, f"Max {MAX_PHOTOS_PER_VISIT} photos per visit.")
    if file.content_type and not any(file.content_type.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    data = await file.read()
    if len(data) > MAX_PHOTO_SIZE_BYTES:
        raise HTTPException(400, f"Photo exceeds max size of {MAX_PHOTO_SIZE_BYTES // (1024*1024)} MB.")

    # Small thumbnail for list rendering (best-effort — use Pillow if available)
    thumb_b64 = None
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.thumbnail((320, 240))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=70, optimize=True)
        thumb_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        # Fallback — just base64 the raw bytes if small enough
        if len(data) < 200_000:
            thumb_b64 = base64.b64encode(data).decode("ascii")

    # Upload to OneDrive (best-effort — silent on failure so draft still saves)
    onedrive_url = None
    onedrive_path = None
    try:
        from ..services import onedrive
        year_month = (visit.visit_date or datetime.now().date()).strftime("%Y-%m")
        folder = f"SiteVisits/{year_month}/photos/{visit.report_id}"
        ext = ""
        if file.filename and "." in file.filename:
            ext = "." + file.filename.rsplit(".", 1)[-1].lower()[:6]
        fname = f"photo_{len(visit.photos) + 1:02d}{ext}"
        info = onedrive.upload_file(data, fname, folder)
        if info and isinstance(info, dict):
            onedrive_url = info.get("webUrl")
            onedrive_path = f"{folder}/{fname}"
    except Exception as e:
        print(f"[site_visit] photo OneDrive upload failed: {e}")

    photo = SiteVisitPhoto(
        visit_id=visit.id,
        sequence=len(visit.photos) + 1,
        caption=(caption or "").strip() or None,
        original_filename=file.filename,
        mime_type=file.content_type,
        size_bytes=len(data),
        onedrive_url=onedrive_url,
        onedrive_path=onedrive_path,
        thumbnail_b64=thumb_b64,
    )
    db.add(photo)
    visit.last_edited_at = datetime.utcnow()
    db.commit()
    db.refresh(photo)
    return {
        "success": True,
        "photo": {
            "id": photo.id,
            "sequence": photo.sequence,
            "caption": photo.caption or "",
            "original_filename": photo.original_filename,
            "thumbnail_b64": photo.thumbnail_b64,
            "onedrive_url": photo.onedrive_url,
        },
    }


@router.put("/api/{visit_id}/photos/{photo_id}")
async def update_photo_caption(
    visit_id: int,
    photo_id: int,
    request: Request,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    visit = db.query(SiteVisit).filter_by(id=visit_id).first()
    if not visit:
        raise HTTPException(404, "Visit not found")
    _ensure_owner_or_admin(visit, user)
    if visit.status == "submitted":
        raise HTTPException(403, "Visit already submitted")
    photo = db.query(SiteVisitPhoto).filter_by(id=photo_id, visit_id=visit_id).first()
    if not photo:
        raise HTTPException(404, "Photo not found")
    body = await request.json()
    if "caption" in body:
        photo.caption = (body["caption"] or "").strip() or None
    visit.last_edited_at = datetime.utcnow()
    db.commit()
    return {"success": True}


@router.delete("/api/{visit_id}/photos/{photo_id}")
def delete_photo(
    visit_id: int,
    photo_id: int,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    visit = db.query(SiteVisit).filter_by(id=visit_id).first()
    if not visit:
        raise HTTPException(404, "Visit not found")
    _ensure_owner_or_admin(visit, user)
    if visit.status == "submitted":
        raise HTTPException(403, "Visit already submitted")
    photo = db.query(SiteVisitPhoto).filter_by(id=photo_id, visit_id=visit_id).first()
    if not photo:
        raise HTTPException(404, "Photo not found")
    db.delete(photo)
    visit.last_edited_at = datetime.utcnow()
    db.commit()
    return {"success": True}


# ============================================================
# API — submit (final)
# ============================================================

@router.post("/api/{visit_id}/submit")
async def submit_visit(
    visit_id: int,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Finalize the draft: generate PDF, upload to OneDrive, email VP+admin+arasu."""
    visit = db.query(SiteVisit).filter_by(id=visit_id).first()
    if not visit:
        raise HTTPException(404, "Visit not found")
    _ensure_owner_or_admin(visit, user)
    if visit.status == "submitted":
        raise HTTPException(400, "Already submitted.")

    # Minimum required data
    if not visit.company_name:
        raise HTTPException(400, "Please enter customer / company name before submitting.")
    if not visit.visit_date:
        visit.visit_date = datetime.now().date()
    if not visit.visited_by:
        visit.visited_by = user.name

    # Fetch employee for filename
    emp = db.query(Employee).filter_by(id=visit.employee_id).first() if visit.employee_id else None
    emp_code = emp.employee_code if emp else "OPEN"

    # Build PDF
    from ..services.site_visit_pdf import generate_site_visit_pdf
    try:
        pdf_bytes = generate_site_visit_pdf(visit, employee=emp)
    except Exception as e:
        raise HTTPException(500, f"PDF generation failed: {e}")

    filename = _pdf_filename_with_code(visit, emp_code)

    # Upload PDF to OneDrive
    year_month = visit.visit_date.strftime("%Y-%m")
    folder = f"SiteVisits/{year_month}"
    pdf_url = None
    try:
        from ..services import onedrive
        info = onedrive.upload_file(pdf_bytes, filename, folder)
        if info and isinstance(info, dict):
            pdf_url = info.get("webUrl")
    except Exception as e:
        print(f"[site_visit] PDF OneDrive upload failed: {e}")

    visit.status = "submitted"
    visit.submitted_at = datetime.utcnow()
    visit.pdf_filename = filename
    visit.pdf_onedrive_url = pdf_url
    visit.last_edited_at = datetime.utcnow()

    # Email VP + info + arasu with attachment
    # Bulletproof: always includes the 3 mandatory addresses, plus any extras from env vars
    try:
        from ..services.email_service import send_email_async

        MANDATORY_TO = "vp@metfraa.com"
        MANDATORY_CC = ["info@metfraa.com", "arasu@metfraa.com"]

        to_email = os.getenv("SITE_VISIT_TO", MANDATORY_TO).strip() or MANDATORY_TO

        # Start from mandatory list, add any from env, dedupe
        extra_cc = [
            e.strip() for e in os.getenv("SITE_VISIT_CC", "").split(",") if e.strip()
        ]
        cc_set = []
        for addr in MANDATORY_CC + extra_cc:
            if addr and addr.lower() != to_email.lower() and addr not in cc_set:
                cc_set.append(addr)

        subject = f"Site Visit — {visit.company_name} ({visit.visit_date.strftime('%d %b %Y')})"
        html = _submission_email_html(visit, emp)

        print(f"[site_visit] sending email to={to_email} cc={cc_set}")

        ok = await send_email_async(
            to=to_email,
            subject=subject,
            html_body=html,
            cc=cc_set,
            attachments=[(filename, pdf_bytes, "application/pdf")],
        )
        print(f"[site_visit] send_email_async returned: {ok}")
    except Exception as e:
        import traceback
        print(f"[site_visit] submission email failed: {e}")
        traceback.print_exc()

    db.add(AuditLog(
        actor_code=user.employee_code,
        actor_email=user.email,
        action="site_visit_submitted",
        details={
            "visit_id": visit.id,
            "report_id": visit.report_id,
            "company_name": visit.company_name,
            "category": visit.category,
            "n_photos": len(visit.photos),
        },
    ))
    db.commit()
    db.refresh(visit)

    return {"success": True, "visit": _visit_to_dict(visit)}


def _submission_email_html(visit: SiteVisit, emp: Optional[Employee]) -> str:
    date_str = visit.visit_date.strftime("%A, %d %B %Y") if visit.visit_date else "—"
    cat_labels = {
        "newshed": "New Shed",
        "reroof": "Re-roofing & Maintenance",
        "extension": "Extension / Modification",
        "other": "Other Requirement",
    }
    cat = cat_labels.get(visit.category or "", visit.category or "—")
    priority_color = {"Low": "#059669", "Medium": "#D97706", "High": "#DC2626"}.get(visit.priority or "", "#6B7280")
    emp_str = f"{emp.name} ({emp.employee_code})" if emp else "—"
    return f"""
    <html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#F9FAFB;padding:24px;margin:0">
      <div style="max-width:600px;margin:auto;background:white;border:1px solid #E5E7EB;border-radius:8px;overflow:hidden">
        <div style="background:#000;padding:22px 28px;border-bottom:3px solid #1E3A8A">
          <div style="color:#1E3A8A;font-size:11px;letter-spacing:0.14em;text-transform:uppercase;font-weight:700">Metfraa — Business Development</div>
          <h1 style="color:white;font-size:22px;margin:6px 0 0;letter-spacing:0.01em;font-weight:600">Site Visit Report</h1>
          <div style="color:#9CA3AF;font-size:12px;margin-top:6px;font-family:ui-monospace,monospace">{visit.report_id}</div>
        </div>

        <div style="padding:28px">
          <div style="font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:1px;font-weight:700">Customer</div>
          <div style="font-size:22px;font-weight:700;color:#111827;margin:4px 0 20px">{visit.company_name}</div>

          <table style="width:100%;border-collapse:collapse;font-size:14px;color:#111827;margin-bottom:20px">
            <tr><td style="padding:6px 0;color:#6B7280;width:38%;font-size:12px">Visit date</td><td style="padding:6px 0">{date_str}</td></tr>
            <tr><td style="padding:6px 0;color:#6B7280;font-size:12px">Visited by</td><td style="padding:6px 0">{emp_str}</td></tr>
            <tr><td style="padding:6px 0;color:#6B7280;font-size:12px">Contact</td><td style="padding:6px 0">{visit.contact_person or '—'}{' · ' + visit.contact_phone if visit.contact_phone else ''}</td></tr>
            <tr><td style="padding:6px 0;color:#6B7280;font-size:12px">Category</td><td style="padding:6px 0">{cat}</td></tr>
            <tr><td style="padding:6px 0;color:#6B7280;font-size:12px">Priority</td><td style="padding:6px 0"><span style="color:{priority_color};font-weight:700">{visit.priority or '—'}</span></td></tr>
            <tr><td style="padding:6px 0;color:#6B7280;font-size:12px">Follow-up</td><td style="padding:6px 0">{visit.followup_date.strftime('%d %b %Y') if visit.followup_date else '—'}</td></tr>
          </table>

          {'<div style="background:#F3F4F6;padding:14px 16px;border-radius:6px;font-size:13.5px;color:#111827;margin-bottom:18px;border-left:3px solid #1E3A8A"><div style="font-size:10px;text-transform:uppercase;color:#6B7280;font-weight:700;margin-bottom:6px;letter-spacing:1px">Next Steps</div>' + (visit.next_steps or '—').replace(chr(10),'<br>') + '</div>' if visit.next_steps else ''}

          <div style="border-top:1px solid #E5E7EB;padding-top:14px;font-size:12px;color:#6B7280">
            The full PDF report is attached with discussion notes, category-specific requirements and site photos.
          </div>
        </div>

        <div style="background:#F9FAFB;padding:14px 28px;color:#9CA3AF;font-size:11px;text-align:center;border-top:1px solid #E5E7EB">
          Metfraa Steel Buildings Pvt. Ltd.
        </div>
      </div>
    </body></html>
    """


# ============================================================
# API — delete draft
# ============================================================

@router.delete("/api/{visit_id}")
def delete_visit(
    visit_id: int,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Delete a DRAFT visit. Submitted visits can only be deleted by admin."""
    visit = db.query(SiteVisit).filter_by(id=visit_id).first()
    if not visit:
        raise HTTPException(404, "Visit not found")
    _ensure_owner_or_admin(visit, user)
    if visit.status == "submitted" and not user.is_admin:
        raise HTTPException(403, "Submitted visits can only be deleted by admin.")
    db.delete(visit)
    db.add(AuditLog(
        actor_code=user.employee_code,
        actor_email=user.email,
        action="site_visit_deleted",
        details={"visit_id": visit_id, "report_id": visit.report_id, "status": visit.status},
    ))
    db.commit()
    return {"success": True}


# ============================================================
# Download PDF
# ============================================================

@router.get("/api/{visit_id}/pdf")
def download_pdf(
    visit_id: int,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Download the submission PDF. Regenerated fresh so it always reflects current data."""
    visit = db.query(SiteVisit).filter_by(id=visit_id).first()
    if not visit:
        raise HTTPException(404, "Visit not found")
    _ensure_owner_or_admin(visit, user)

    emp = db.query(Employee).filter_by(id=visit.employee_id).first() if visit.employee_id else None
    from ..services.site_visit_pdf import generate_site_visit_pdf
    pdf_bytes = generate_site_visit_pdf(visit, employee=emp)
    filename = visit.pdf_filename or _pdf_filename_with_code(
        visit, emp.employee_code if emp else "OPEN"
    )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
