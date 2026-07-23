"""Employee & access management (Phase 2C).

Page:  /people                       single screen for Superadmin + HR Admin
APIs:  GET    /people/api/list
       POST   /people/api/create     (temp password, must_reset on first login)
       PATCH  /people/api/{id}       (details + module access + roles + expense level)
       POST   /people/api/{id}/reset-password
       DELETE /people/api/{id}       hard delete ONLY if no linked data, else 409 (deactivate instead)

Role rules: only Superadmin can grant/revoke roles (incl. other superadmins);
HR Admin can manage employee details, module access, levels and passwords but
not roles. employees.is_admin is synced to (superadmin OR kpi_admin) because
existing KPI admin routes check it directly.
"""
import json
import logging
import secrets
import string

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_current_user, get_optional_user
from ..models import (
    EHSSubmission, Employee, EmployeeAccess, ExpenseEmployeeMeta, ExpenseSubmission,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/people", tags=["people"])
templates = Jinja2Templates(directory="app/templates")

ROLE_FIELDS = ["is_superadmin", "is_hr_admin", "kpi_admin", "expense_admin", "ehs_admin"]
ACCESS_FIELDS = ["kpi_access", "expense_access", "ehs_access"]


def _require_manager(db: Session, user: Employee):
    acc = get_access(db, user)
    if not acc.can_manage_employees:
        raise HTTPException(status_code=403, detail="Superadmin or HR Admin access required")
    return acc


def _temp_password(n: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _row(db: Session, e: Employee) -> dict:
    a = db.query(EmployeeAccess).filter(EmployeeAccess.employee_id == e.id).first()
    m = db.query(ExpenseEmployeeMeta).filter(ExpenseEmployeeMeta.employee_id == e.id).first()
    return {
        "id": e.id, "employee_code": e.employee_code, "name": e.name, "email": e.email or "",
        "designation": e.designation or "", "department": e.department or "",
        "is_active": bool(e.is_active), "expense_level": (m.level if m else "L1"),
        "legacy_admin": bool(e.is_admin) and a is None,
        **{f: bool(getattr(a, f)) if a else False for f in ROLE_FIELDS},
        **{f: bool(getattr(a, f)) if a else True for f in ACCESS_FIELDS},
    }


def _sync_is_admin(e: Employee, a: EmployeeAccess) -> None:
    e.is_admin = bool(a.is_superadmin or a.kpi_admin)


# ---------------------------------------------------------------- page

@router.get("/", response_class=HTMLResponse)
@router.get("", response_class=HTMLResponse, include_in_schema=False)
def people_page(request: Request, user: Employee | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    acc = _require_manager(db, user)
    return templates.TemplateResponse(request, "people.html", {
        "user": user, "is_superadmin": acc.superadmin,
    })


# ---------------------------------------------------------------- APIs

@router.get("/api/list")
def people_list(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_manager(db, user)
    emps = db.query(Employee).order_by(Employee.is_active.desc(), Employee.name).all()
    return [_row(db, e) for e in emps]


@router.post("/api/create")
async def people_create(request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_manager(db, user)
    body = await request.json()
    code = (body.get("employee_code") or "").strip().upper()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="Employee code and name are required")
    if db.query(Employee).filter(Employee.employee_code == code).first():
        raise HTTPException(status_code=409, detail=f"Employee code {code} already exists")
    temp = _temp_password()
    e = Employee(
        employee_code=code, name=name,
        email=(body.get("email") or "").strip() or None,
        designation=(body.get("designation") or "").strip() or None,
        department=(body.get("department") or "").strip() or None,
        is_active=True, is_admin=False, must_reset_password=True,
        password_hash=bcrypt.hashpw(temp.encode(), bcrypt.gensalt()).decode(),
    )
    db.add(e)
    db.flush()
    a = EmployeeAccess(employee_id=e.id)
    for f in ACCESS_FIELDS:
        if f in body:
            setattr(a, f, bool(body[f]))
    db.add(a)
    level = (body.get("expense_level") or "L1").upper()
    if level in ("L1", "L2", "L3"):
        db.add(ExpenseEmployeeMeta(employee_id=e.id, level=level))
    db.commit()
    return {"ok": True, "id": e.id, "temp_password": temp,
            "message": f"{name} created. Temp password: {temp} (they must change it on first login)."}


@router.patch("/api/{emp_id}")
async def people_update(emp_id: int, request: Request, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = _require_manager(db, user)
    e = db.query(Employee).filter(Employee.id == emp_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Employee not found")
    body = await request.json()

    # ---- details (HR + Superadmin)
    for field in ("name", "email", "designation", "department"):
        if field in body:
            setattr(e, field, (str(body[field]).strip() or None) if body[field] is not None else None)
    if "employee_code" in body:
        newcode = str(body["employee_code"]).strip().upper()
        if newcode and newcode != e.employee_code:
            if db.query(Employee).filter(Employee.employee_code == newcode).first():
                raise HTTPException(status_code=409, detail="That employee code is taken")
            e.employee_code = newcode
    if "is_active" in body:
        if emp_id == user.id and not body["is_active"]:
            raise HTTPException(status_code=400, detail="You can't deactivate yourself")
        e.is_active = bool(body["is_active"])

    # ---- expense level (HR + Superadmin)
    if "expense_level" in body:
        level = str(body["expense_level"]).upper()
        if level not in ("L1", "L2", "L3"):
            raise HTTPException(status_code=400, detail="Level must be L1/L2/L3")
        m = db.query(ExpenseEmployeeMeta).filter(ExpenseEmployeeMeta.employee_id == emp_id).first()
        if m:
            m.level = level
        else:
            db.add(ExpenseEmployeeMeta(employee_id=emp_id, level=level))

    # ---- access + roles
    a = db.query(EmployeeAccess).filter(EmployeeAccess.employee_id == emp_id).first()
    touching_roles = any(f in body for f in ROLE_FIELDS)
    touching_access = any(f in body for f in ACCESS_FIELDS)
    if touching_roles and not acc.superadmin:
        raise HTTPException(status_code=403, detail="Only a Superadmin can change roles")
    if touching_roles or touching_access:
        if a is None:
            a = EmployeeAccess(employee_id=emp_id,
                               is_superadmin=bool(e.is_admin))  # preserve legacy admin on first write
            db.add(a)
        for f in ACCESS_FIELDS:
            if f in body:
                setattr(a, f, bool(body[f]))
        for f in ROLE_FIELDS:
            if f in body:
                if f == "is_superadmin" and emp_id == user.id and not body[f]:
                    raise HTTPException(status_code=400, detail="You can't remove your own Superadmin role")
                setattr(a, f, bool(body[f]))
        _sync_is_admin(e, a)

    db.commit()
    return {"ok": True, **_row(db, e)}


@router.post("/api/{emp_id}/reset-password")
def people_reset_password(emp_id: int, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_manager(db, user)
    e = db.query(Employee).filter(Employee.id == emp_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Employee not found")
    temp = _temp_password()
    e.password_hash = bcrypt.hashpw(temp.encode(), bcrypt.gensalt()).decode()
    e.must_reset_password = True
    db.commit()
    return {"ok": True, "temp_password": temp,
            "message": f"Temp password for {e.name}: {temp} (must change on next login)."}


@router.delete("/api/{emp_id}")
def people_delete(emp_id: int, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = _require_manager(db, user)
    if not acc.superadmin:
        raise HTTPException(status_code=403, detail="Only a Superadmin can delete employees")
    if emp_id == user.id:
        raise HTTPException(status_code=400, detail="You can't delete yourself")
    e = db.query(Employee).filter(Employee.id == emp_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Employee not found")
    linked = (
        db.query(EHSSubmission).filter(EHSSubmission.submitted_by_id == emp_id).count()
        + db.query(ExpenseSubmission).filter(ExpenseSubmission.employee_id == emp_id).count()
    )
    if linked:
        raise HTTPException(status_code=409,
                            detail=f"{e.name} has {linked} linked submission(s) — deactivate instead of deleting to keep history intact")
    db.query(EmployeeAccess).filter(EmployeeAccess.employee_id == emp_id).delete()
    db.query(ExpenseEmployeeMeta).filter(ExpenseEmployeeMeta.employee_id == emp_id).delete()
    db.delete(e)
    db.commit()
    return {"ok": True}
