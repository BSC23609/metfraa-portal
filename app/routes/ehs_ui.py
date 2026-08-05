"""EHS UI parity layer.

Serves the transplanted reference frontend (app/static/ehs/*.html) and the
exact JSON contract its JS expects. The reference app served these pages from
Express at root paths; inside the portal they live under /ehs/ because the
root namespace is already taken by KPI / Site Visits / Expense.

The HTML/CSS/JS under app/static/ehs are byte-identical to the reference
except for a scripted path-prefix rewrite (138 lines, all reversible):
    /css/... /js/... /img/... /api/... /submissions /approvals /form/... etc.
        -> the same path prefixed with /ehs
    /auth/logout -> /logout   (the portal owns logout)

login.html and the Passport auth layer are deliberately absent — the portal's
own session is the auth layer, exactly as the restore spec requires.

Error bodies are {"error": "..."} (not FastAPI's default {"detail": ...})
because the reference JS reads err.error.
"""
import os
import re
import pathlib

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_optional_user
from ..ehs.forms import ALL_FORMS, FORMS_BY_ID, INSPECTORS
from ..models import EHSProject, EHSSubmission, Employee

router = APIRouter(prefix="/ehs", tags=["ehs-ui"])

PAGES = pathlib.Path("app/static/ehs")


# ------------------------------------------------------------------ helpers

def _err(status: int, message: str, **extra):
    return JSONResponse(status_code=status, content={"error": message, **extra})


def _page(name: str) -> FileResponse:
    return FileResponse(PAGES / name, media_type="text/html")


class EhsUser:
    """Adapter: portal Employee -> the req.user shape EHS reads.

    The restore spec pins these field names (email, name, picture, isAdmin,
    isApprover); the frontend breaks if they are renamed.
    """

    def __init__(self, db: Session, emp: Employee):
        acc = get_access(db, emp)
        self.email = (emp.email or "").lower()
        self.name = emp.name or emp.employee_code
        self.picture = ""  # portal has no avatars
        self.is_admin = bool(acc.can_admin_ehs or acc.superadmin)
        self.is_approver = bool(self.is_admin or _env_approver(self.email))
        self.has_module = bool(acc.ehs_access or acc.can_admin_ehs or acc.superadmin)

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "email": self.email,
            "picture": self.picture,
            "isAdmin": self.is_admin,
            "isApprover": self.is_approver,
            "inspectors": INSPECTORS,
        }


def _env_approver(email: str) -> bool:
    raw = os.getenv("EHS_APPROVER_EMAILS", "varadharaj@metfraa.com,nirmal@metfraa.com")
    return email in [e.strip().lower() for e in raw.split(",") if e.strip()]


def _me(db: Session, emp: Employee | None) -> EhsUser | None:
    return EhsUser(db, emp) if emp else None


# ------------------------------------------------------------- page routes
# Mirrors the reference route table one-for-one (minus /login).

def _guard(request: Request, user, db):
    """requireAuth + module access. JSON for /api, redirect for pages."""
    is_api = "/api/" in request.url.path
    if not user:
        if is_api:
            return _err(401, "Not authenticated", loginUrl="/auth/login")
        return RedirectResponse("/auth/login", status_code=303)
    if not _me(db, user).has_module:
        if is_api:
            return _err(403, "You don't have access to the EHS module")
        return RedirectResponse("/", status_code=303)
    return None


def _admin_guard(request: Request, user, db):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    if not _me(db, user).is_admin:
        if "/api/" in request.url.path:
            return _err(403, "Admin only")
        return RedirectResponse("/ehs/", status_code=303)
    return None


@router.get("/", include_in_schema=False)
@router.get("", include_in_schema=False)
def page_dashboard(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    return _guard(request, user, db) or _page("dashboard.html")


@router.get("/form/{form_id}", include_in_schema=False)
def page_form(form_id: str, request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    return _guard(request, user, db) or _page("form.html")


@router.get("/submissions", include_in_schema=False)
def page_submissions(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    return _guard(request, user, db) or _page("submissions.html")


@router.get("/approvals", include_in_schema=False)
def page_approvals(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    return _guard(request, user, db) or _page("approvals.html")


@router.get("/approvals/{form_id}/{sub_id}", include_in_schema=False)
def page_approval_review(form_id: str, sub_id: str, request: Request,
                         user=Depends(get_optional_user), db: Session = Depends(get_db)):
    return _guard(request, user, db) or _page("approval-review.html")


@router.get("/admin-dashboard", include_in_schema=False)
def page_admin_dashboard(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    return _admin_guard(request, user, db) or _page("admin-dashboard.html")


@router.get("/admin-charts", include_in_schema=False)
def page_admin_charts(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    return _admin_guard(request, user, db) or _page("admin-charts.html")


@router.get("/admin-settings", include_in_schema=False)
def page_admin_settings(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    return _admin_guard(request, user, db) or _page("admin-settings.html")


@router.get("/admin", include_in_schema=False)
def page_admin(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    return _admin_guard(request, user, db) or _page("admin.html")


# --------------------------------------------------------------- core APIs

@router.get("/api/me")
def api_me(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    return _me(db, user).to_json()


@router.get("/api/forms")
def api_forms(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    return [
        {"id": f["id"], "code": f["code"], "title": f["title"],
         "category": f["category"], "icon": f["icon"]}
        for f in ALL_FORMS
    ]


@router.get("/api/forms/{form_id}")
def api_form(form_id: str, request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    form = FORMS_BY_ID.get(form_id)
    if not form:
        return _err(404, "Form not found")
    return form


@router.get("/api/my-pending-count")
def api_my_pending_count(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    n = (
        db.query(EHSSubmission)
        .filter(EHSSubmission.status == "pending",
                EHSSubmission.submitted_by_id == user.id)
        .count()
    )
    return {"count": n}


@router.get("/api/projects")
def api_projects(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    """Active projects only, {id, name} — feeds the `type: 'project'` dropdown."""
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    rows = (
        db.query(EHSProject)
        .filter(EHSProject.active == True)  # noqa: E712
        .order_by(EHSProject.name)
        .all()
    )
    return [{"id": p.id, "name": p.name} for p in rows]


@router.get("/admin/api/info")
def api_admin_info(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _admin_guard(request, user, db)
    if blocked:
        return blocked
    me = _me(db, user)
    return {
        "user": {"name": me.name, "email": me.email},
        "isAdmin": me.is_admin,
        "formCount": len(ALL_FORMS),
        "inspectors": INSPECTORS,
    }


# ============================================================================
# Slice 2 — Submissions, Approvals, PDF
#
# Reference behaviour, re-expressed against Postgres:
#   - the reference read approved/rejected rows out of each form's
#     _MasterLog.xlsx and merged live pending JSONs on top;
#   - the portal has all three states in ehs_submissions, so one query
#     replaces that merge. The JSON that reaches the browser is the same.
# ============================================================================

from fastapi import BackgroundTasks  # noqa: E402
from starlette.responses import StreamingResponse  # noqa: E402

from . import ehs as ehs_api  # noqa: E402
from ..ehs.forms import ALL_FORMS as _ALL  # noqa: E402
from ..services import onedrive  # noqa: E402
from ..services.ehs_excel_log import ehs_root  # noqa: E402

# Same precedence the reference used to pick a row's display identifier.
KEY_FIELDS = ["equipment_no", "project_name", "site_name",
              "employee_name", "meeting_no", "permit_no"]
KEY_LABELS = {"equipment_no": "Equipment No.", "project_name": "Project Name",
              "site_name": "Site Name", "employee_name": "Employee / Worker Name",
              "meeting_no": "Meeting No.", "permit_no": "Permit No."}


def _key_of(fields: dict) -> tuple[str, str]:
    for k in KEY_FIELDS:
        v = (fields or {}).get(k)
        if v:
            return KEY_LABELS[k], str(v)
    return "Identifier", ""


def _status_title(s: str) -> str:
    """DB stores lowercase; the reference frontend matches Title-case."""
    return {"pending": "Pending", "approved": "Approved", "rejected": "Rejected"}.get(s, "Approved")


def _row(sub: EHSSubmission, include_pdf: bool) -> dict:
    form = FORMS_BY_ID.get(sub.form_id) or {}
    label, value = _key_of(sub.fields)
    row = {
        "formId": sub.form_id,
        "formCode": sub.form_code,
        "formTitle": sub.form_title,
        "formCategory": form.get("category", ""),
        "submissionId": sub.submission_id,
        "submittedAt": sub.submitted_at_ist or "",
        "submittedByName": sub.submitted_by_name or "",
        "submittedByEmail": sub.submitted_by_email or "",
        "keyLabel": label,
        "keyValue": value,
        "status": _status_title(sub.status),
        "reviewerName": sub.reviewed_by_name or "",
        "reviewedAt": sub.reviewed_at_ist or "",
        "rejectReason": sub.reject_reason or "",
    }
    # Reference strips the OneDrive link for non-admins.
    row["pdfLink"] = (sub.pdf_web_url or "") if include_pdf else ""
    return row


@router.get("/api/submissions")
def api_submissions(request: Request, formId: str | None = None, submitter: str | None = None,
                    startDate: str | None = None, endDate: str | None = None,
                    status: str | None = None, limit: int = 200,
                    user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    me = _me(db, user)
    limit = min(limit or 200, 1000)

    q = db.query(EHSSubmission)
    if formId:
        if formId not in FORMS_BY_ID:
            return {"isAdmin": me.is_admin, "total": 0, "truncated": False, "rows": [],
                    "submitters": [], "statusCounts": {"all": 0, "pending": 0, "approved": 0, "rejected": 0},
                    "forms": [{"id": f["id"], "code": f["code"], "title": f["title"],
                               "category": f["category"]} for f in _ALL]}
        q = q.filter(EHSSubmission.form_id == formId)
    if not me.is_admin:
        q = q.filter(EHSSubmission.submitted_by_email == me.email)
    elif submitter:
        q = q.filter(EHSSubmission.submitted_by_email == submitter.lower())
    if startDate:
        q = q.filter(EHSSubmission.submitted_at_ist >= startDate)
    if endDate:
        q = q.filter(EHSSubmission.submitted_at_ist <= f"{endDate} 23:59:59")

    # statusCounts are computed BEFORE the status filter (reference behaviour)
    pre_status = q.all()
    counts = {"all": len(pre_status), "pending": 0, "approved": 0, "rejected": 0}
    for s in pre_status:
        counts[s.status if s.status in counts else "approved"] += 1

    rows_src = pre_status
    if status:
        rows_src = [s for s in pre_status if (s.status or "approved").lower() == status.lower()]
    rows_src.sort(key=lambda s: s.submitted_at_ist or "", reverse=True)

    submitters = []
    if me.is_admin:
        seen = {}
        for s in db.query(EHSSubmission).all():
            k = (s.submitted_by_email or "").lower()
            if k and k not in seen:
                seen[k] = {"name": s.submitted_by_name, "email": s.submitted_by_email}
        submitters = sorted(seen.values(), key=lambda x: (x["name"] or ""))

    return {
        "isAdmin": me.is_admin,
        "total": len(rows_src),
        "truncated": len(rows_src) > limit,
        "rows": [_row(s, me.is_admin) for s in rows_src[:limit]],
        "submitters": submitters,
        "statusCounts": counts,
        "forms": [{"id": f["id"], "code": f["code"], "title": f["title"],
                   "category": f["category"]} for f in _ALL],
    }


@router.post("/api/submissions/cache-clear")
def api_submissions_cache_clear(request: Request, user=Depends(get_optional_user),
                                db: Session = Depends(get_db)):
    # The portal reads live from Postgres — there is no cache to bust. The
    # endpoint stays so the reference "Refresh" button behaves identically.
    return _guard(request, user, db) or {"ok": True}


@router.get("/api/pdf/{form_id}/{submission_id}")
def api_pdf(form_id: str, submission_id: str, request: Request, inline: str | None = None,
            user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    me = _me(db, user)
    sub = db.query(EHSSubmission).filter(
        EHSSubmission.submission_id == submission_id,
        EHSSubmission.form_id == form_id).first()
    if not sub:
        return _err(404, "Submission not found")
    if not me.is_admin and (sub.submitted_by_email or "").lower() != me.email:
        return _err(403, "Forbidden — you can only view your own submissions")

    form = FORMS_BY_ID.get(form_id) or {}
    m = re.match(r"^(\d{4})-(\d{2})", sub.submitted_at_ist or "")
    if not m:
        return _err(500, "Could not parse submission date")
    folder = f"{ehs_root()}/{form.get('folder', form_id)}/Reports/{m.group(1)}/{m.group(2)}"
    try:
        items = onedrive.list_children_by_path(folder) or []
    except Exception as ex:
        return _err(500, f"Failed to locate PDF in OneDrive: {ex}")
    match = next((i for i in items
                  if (i.get("name") or "").endswith(".pdf") and submission_id in i.get("name", "")), None)
    if not match:
        return _err(404, "PDF not found in OneDrive")
    try:
        data = onedrive.download_from_path(f"{folder}/{match['name']}")
    except Exception as ex:
        return _err(500, f"Failed to download PDF: {ex}")
    disp = "inline" if inline == "1" else "attachment"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="{match["name"]}"'})


# ------------------------------------------------------------ approvals

def _approver_guard(request: Request, user, db):
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    if not _me(db, user).is_approver:
        return _err(403, "Approver access required")
    return None


@router.get("/api/approvals")
def api_approvals(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _approver_guard(request, user, db)
    if blocked:
        return blocked
    subs = (db.query(EHSSubmission)
            .filter(EHSSubmission.status == "pending")
            .order_by(EHSSubmission.submitted_at_ist.desc()).all())
    rows = []
    for s in subs:
        form = FORMS_BY_ID.get(s.form_id) or {}
        rows.append({
            "formId": s.form_id,
            "formCode": form.get("code", s.form_code),
            "formTitle": form.get("title", s.form_title),
            "submissionId": s.submission_id,
            "submittedAt": s.submitted_at_ist,
            "submittedByName": s.submitted_by_name or "",
            "submittedByEmail": s.submitted_by_email or "",
            "keyValue": _key_of(s.fields)[1],
        })
    return {"count": len(rows), "rows": rows}


@router.get("/api/approvals/{form_id}/{sub_id}")
def api_approval_detail(form_id: str, sub_id: str, request: Request,
                        user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _approver_guard(request, user, db)
    if blocked:
        return blocked
    form = FORMS_BY_ID.get(form_id)
    if not form:
        return _err(404, "Unknown form")
    s = db.query(EHSSubmission).filter(
        EHSSubmission.submission_id == sub_id,
        EHSSubmission.form_id == form_id).first()
    if not s or s.status != "pending":
        return _err(404, "Pending submission not found (may have been already handled)")
    return {
        "form": {"id": form["id"], "code": form["code"], "title": form["title"],
                 "category": form["category"], "fields": form["fields"],
                 "checklist": form.get("checklist")},
        "submission": {
            "submissionId": s.submission_id,
            "formId": s.form_id,
            "formCode": s.form_code,
            "formTitle": s.form_title,
            "submittedAt": s.submitted_at_ist,
            "user": {"name": s.submitted_by_name, "email": s.submitted_by_email},
            "fields": s.fields or {},
            "checklist": s.checklist or [],
            "photos": s.photos or {"fields": {}, "checklist": {}},
            "status": "pending",
        },
    }


@router.get("/api/approvals/{form_id}/{sub_id}/photo/{filename}")
def api_approval_photo(form_id: str, sub_id: str, filename: str, request: Request,
                       user=Depends(get_optional_user), db: Session = Depends(get_db)):
    blocked = _approver_guard(request, user, db)
    if blocked:
        return blocked
    path = f"{ehs_root()}/_Pending/{form_id}/{sub_id}/photos/{filename}"
    try:
        data = onedrive.download_from_path(path)
    except Exception:
        return _err(404, "Photo not found")
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=300"})


async def _decide(kind: str, form_id: str, sub_id: str, request: Request,
                  bg: BackgroundTasks, user, db):
    blocked = _approver_guard(request, user, db)
    if blocked:
        return blocked
    if form_id not in FORMS_BY_ID:
        return _err(404, "Unknown form")
    s = db.query(EHSSubmission).filter(
        EHSSubmission.submission_id == sub_id,
        EHSSubmission.form_id == form_id).first()
    if not s:
        return _err(404, "Pending submission not found")
    if s.status != "pending":
        return _err(409, "Already handled by another reviewer")
    try:
        fn = ehs_api.ehs_approve if kind == "approve" else ehs_api.ehs_reject
        result = await fn(sub_id, request, bg, user, db)
    except HTTPException as ex:
        return _err(ex.status_code, str(ex.detail))
    if kind == "approve":
        return {"ok": True, "submissionId": sub_id, "status": "Approved",
                "pdfUrl": result.get("pdf"),
                "editsCount": len([e for e in (result.get("edits") or "").split(";") if e.strip()])}
    db.refresh(s)
    return {"ok": True, "submissionId": sub_id, "status": "Rejected",
            "reason": s.reject_reason or ""}


@router.post("/api/approvals/{form_id}/{sub_id}/approve")
async def api_approve(form_id: str, sub_id: str, request: Request, bg: BackgroundTasks,
                      user=Depends(get_optional_user), db: Session = Depends(get_db)):
    return await _decide("approve", form_id, sub_id, request, bg, user, db)


@router.post("/api/approvals/{form_id}/{sub_id}/reject")
async def api_reject(form_id: str, sub_id: str, request: Request, bg: BackgroundTasks,
                     user=Depends(get_optional_user), db: Session = Depends(get_db)):
    return await _decide("reject", form_id, sub_id, request, bg, user, db)


@router.post("/api/submit/{form_id}")
async def api_submit(form_id: str, request: Request, bg: BackgroundTasks,
                     user=Depends(get_optional_user), db: Session = Depends(get_db)):
    """Reference path for form submission; delegates to the existing handler."""
    blocked = _guard(request, user, db)
    if blocked:
        return blocked
    try:
        return await ehs_api.ehs_submit(form_id, request, bg, user, db)
    except HTTPException as ex:
        return _err(ex.status_code, str(ex.detail))
