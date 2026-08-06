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
