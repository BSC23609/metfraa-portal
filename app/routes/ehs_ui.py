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
import pathlib

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
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
