"""Admin routes — KPI master CRUD, view all employees' performance, add new employees."""
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import extract

from ..database import get_db
from ..models import Employee, KPI, DailyEntry, KPIEntry, UnlockRequest, AuditLog, PasswordResetRequest, MonthlyKPIActual
from ..deps import require_admin
from ..services.scoring import compute_monthly_score, get_daily_kpi_trend

router = APIRouter(prefix="/admin", tags=["admin"])


def _kpi_count(db: Session, employee_id: int) -> int:
    """Return KPI count for an employee via raw SQL.

    Uses raw SQL to bypass ORM-level schema mismatches on the kpis table
    (e.g. missing 'target' column from earlier schema drift).
    """
    from sqlalchemy import text
    return int(
        db.execute(
            text("SELECT COUNT(*) FROM kpis WHERE employee_id = :eid"),
            {"eid": employee_id},
        ).scalar() or 0
    )
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def admin_home(request: Request, user: Employee = Depends(require_admin)):
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"user": user},
    )


# ---------- API: employees ----------

@router.get("/api/employees")
def list_employees(
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    emps = db.query(Employee).filter_by(is_active=True).order_by(Employee.name).all()
    today = date.today()
    out = []
    for e in emps:
        # Use raw SQL to check whether the employee has KPIs — bypasses ORM
        # schema drift on kpis.target column.
        kpi_n = _kpi_count(db, e.id)
        if kpi_n == 0:
            current_score = 0
            attendance = None
        else:
            try:
                data = compute_monthly_score(db, e.id, today.year, today.month)
                current_score = data["final_score"]
                attendance = data["attendance"]
            except Exception:
                current_score = 0
                attendance = None
        out.append({
            "id": e.id,
            "name": e.name,
            "email": e.email,
            "designation": e.designation,
            "department": e.department,
            "is_admin": e.is_admin,
            "is_active": e.is_active,
            "current_month_score": current_score,
            "attendance": attendance,
            "kpi_count": kpi_n,
        })
    return out


@router.post("/api/employees")
async def create_employee(
    request: Request,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    body = await request.json()
    email = (body.get("email") or "").lower().strip()
    name = (body.get("name") or "").strip()
    designation = (body.get("designation") or "").strip()
    department = (body.get("department") or "").strip() or None
    reports_to = (body.get("reports_to") or "").strip() or None
    is_admin = bool(body.get("is_admin", False))
    jrr_text = body.get("jrr_text") or None

    if not email or not name or not designation:
        raise HTTPException(400, "email, name, designation are required")

    if db.query(Employee).filter(Employee.email.ilike(email)).first():
        raise HTTPException(409, "Email already exists")

    emp = Employee(
        email=email, name=name, designation=designation,
        department=department, reports_to=reports_to,
        is_admin=is_admin, is_active=True, jrr_text=jrr_text,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return {"id": emp.id, "email": emp.email, "name": emp.name}


@router.put("/api/employees/{emp_id}")
async def update_employee(
    emp_id: int,
    request: Request,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).filter_by(id=emp_id).first()
    if not emp:
        raise HTTPException(404, "Employee not found")
    body = await request.json()
    for fld in ["name", "designation", "department", "reports_to", "jrr_text"]:
        if fld in body:
            setattr(emp, fld, body[fld])
    if "is_admin" in body:
        emp.is_admin = bool(body["is_admin"])
    if "is_active" in body:
        emp.is_active = bool(body["is_active"])
    db.commit()
    return {"success": True}


# ---------- API: KPI master ----------

@router.get("/api/employees/{emp_id}/kpis")
def list_kpis(
    emp_id: int,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kpis = (
        db.query(KPI)
        .filter_by(employee_id=emp_id)
        .order_by(KPI.display_order)
        .all()
    )
    return [
        {
            "id": k.id,
            "name": k.name,
            "unit": k.unit,
            "weight": k.weight,
            "target": k.monthly_target,
            "display_order": k.display_order,
            "is_active": k.is_active,
        }
        for k in kpis
    ]


@router.post("/api/employees/{emp_id}/kpis")
async def add_kpi(
    emp_id: int,
    request: Request,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).filter_by(id=emp_id).first()
    if not emp:
        raise HTTPException(404, "Employee not found")
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Name required")
    max_order = db.query(KPI).filter_by(employee_id=emp_id).count()
    kpi = KPI(
        employee_id=emp_id,
        name=name,
        unit=(body.get("unit") or "Count").strip(),
        weight=float(body.get("weight", 10)),
        monthly_target=float(body.get("target", 0)),
        display_order=max_order,
        is_active=True,
    )
    db.add(kpi)
    db.commit()
    db.refresh(kpi)
    return {"id": kpi.id}


@router.put("/api/kpis/{kpi_id}")
async def update_kpi(
    kpi_id: int,
    request: Request,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kpi = db.query(KPI).filter_by(id=kpi_id).first()
    if not kpi:
        raise HTTPException(404, "KPI not found")
    body = await request.json()
    if "name" in body:
        kpi.name = str(body["name"]).strip()
    if "unit" in body:
        kpi.unit = str(body["unit"]).strip()
    if "weight" in body:
        try:
            kpi.weight = float(body["weight"])
        except (TypeError, ValueError):
            raise HTTPException(400, "weight must be a number")
    if "target" in body:
        try:
            kpi.target = float(body["target"])
        except (TypeError, ValueError):
            raise HTTPException(400, "target must be a number")
    if "display_order" in body:
        try:
            kpi.display_order = int(body["display_order"])
        except (TypeError, ValueError):
            pass
    db.add(AuditLog(
        actor_code=user.employee_code,
        actor_email=user.email,
        action="kpi_updated",
        details={"kpi_id": kpi.id, "employee_id": kpi.employee_id, "name": kpi.name,
                 "weight": kpi.weight, "target": kpi.target},
    ))
    db.commit()
    return {"success": True, "kpi": {
        "id": kpi.id, "name": kpi.name, "unit": kpi.unit,
        "weight": kpi.weight, "target": kpi.target,
    }}


@router.delete("/api/kpis/{kpi_id}")
def delete_kpi(
    kpi_id: int,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kpi = db.query(KPI).filter_by(id=kpi_id).first()
    if not kpi:
        raise HTTPException(404, "KPI not found")
    db.delete(kpi)
    db.commit()
    return {"success": True}


# ---------- API: per-employee performance for admin dashboard ----------

@router.get("/api/employees/{emp_id}/performance")
def employee_performance(
    emp_id: int,
    year: Optional[int] = None,
    month: Optional[int] = None,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    data = compute_monthly_score(db, emp_id, year, month)
    trend = get_daily_kpi_trend(db, emp_id, year, month)
    return {
        "employee": {
            "id": data["employee"].id,
            "name": data["employee"].name,
            "designation": data["employee"].designation,
            "email": data["employee"].email,
            "is_admin": data["employee"].is_admin,
        },
        "year": year, "month": month,
        "final_score": data["final_score"],
        "kpi_results": [
            {
                "id": r["kpi"].id,
                "name": r["kpi"].name,
                "unit": r["kpi"].unit,
                "actual": r["actual"],
                "target": r["target"],
                "weight": r["weight"],
                "achievement_pct": r["achievement_pct"],
                "weighted_score": r["weighted_score"],
            }
            for r in data["kpi_results"]
        ],
        "attendance": data["attendance"],
        "trend": trend,
    }


@router.get("/api/overview")
def admin_overview(
    year: Optional[int] = None,
    month: Optional[int] = None,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Top-level company KPI overview for current month."""
    today = date.today()
    year = year or today.year
    month = month or today.month
    emps = db.query(Employee).filter_by(is_active=True).order_by(Employee.name).all()
    rows = []
    for e in emps:
        if _kpi_count(db, e.id) == 0:
            continue
        d = compute_monthly_score(db, e.id, year, month)
        rows.append({
            "employee_id": e.id,
            "name": e.name,
            "designation": e.designation,
            "score": d["final_score"],
            "work_days": d["attendance"]["work_days"],
            "missed_days": d["attendance"]["missed_days"],
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return {
        "year": year,
        "month": month,
        "company_avg": round(sum(r["score"] for r in rows) / len(rows), 2) if rows else 0,
        "employee_count": len(rows),
        "leaderboard": rows,
    }


# ============================================================
# Daily Activity Dashboard (admin)
# ============================================================

@router.get("/api/daily-activity")
def daily_activity(
    target_date: str | None = None,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Per-employee submission status for a given date."""
    if target_date:
        try:
            target = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")
    else:
        target = date.today()

    is_sunday = target.weekday() == 6

    employees = (
        db.query(Employee)
        .filter(Employee.is_active.is_(True))
        .order_by(Employee.name)
        .all()
    )

    rows = []
    submitted_count = 0
    pending_count = 0
    leave_count = 0
    site_count = 0
    sunday_count = 0
    holiday_count = 0

    for emp in employees:
        emp_kpi_total = _kpi_count(db, emp.id)
        # Skip pure admin accounts with no KPIs from KPI dashboard totals
        if emp_kpi_total == 0:
            continue

        entry = (
            db.query(DailyEntry)
            .filter_by(employee_id=emp.id, entry_date=target)
            .first()
        )

        if entry:
            kpi_count_filled = (
                db.query(KPIEntry)
                .filter_by(daily_entry_id=entry.id)
                .count()
            )
            kpi_total = emp_kpi_total
            row_status = entry.entry_type
            submitted_at = entry.submitted_at.isoformat() if entry.submitted_at else None

            if entry.entry_type == "work":
                submitted_count += 1
            elif entry.entry_type == "casual_leave":
                leave_count += 1
            elif entry.entry_type == "site_remote":
                site_count += 1
            elif entry.entry_type == "sunday":
                sunday_count += 1
            elif entry.entry_type == "holiday":
                holiday_count += 1
        else:
            kpi_count_filled = 0
            kpi_total = emp_kpi_total
            row_status = "pending"
            submitted_at = None
            pending_count += 1

        rows.append({
            "id": emp.id,
            "name": emp.name,
            "email": emp.email,
            "designation": emp.designation,
            "department": emp.department,
            "status": row_status,
            "submitted_at": submitted_at,
            "kpi_filled": kpi_count_filled,
            "kpi_total": kpi_total,
            "comments": entry.comments if entry else None,
        })

    return {
        "date": target.isoformat(),
        "weekday": target.strftime("%A"),
        "is_sunday": is_sunday,
        "is_today": target == date.today(),
        "is_future": target > date.today(),
        "stats": {
            "total": len(rows),
            "submitted": submitted_count,
            "pending": pending_count,
            "leave": leave_count,
            "site_remote": site_count,
            "sunday": sunday_count,
            "holiday": holiday_count,
        },
        "rows": rows,
    }


@router.get("/api/employee-entry/{emp_id}/{target_date}")
def get_employee_entry(
    emp_id: int,
    target_date: str,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get a specific employee's entry for a date - for the modal preview."""
    try:
        target = date.fromisoformat(target_date)
    except ValueError:
        raise HTTPException(400, "Invalid date")

    emp = db.query(Employee).filter_by(id=emp_id).first()
    if not emp:
        raise HTTPException(404, "Employee not found")

    entry = (
        db.query(DailyEntry)
        .filter_by(employee_id=emp_id, entry_date=target)
        .first()
    )
    if not entry:
        return {
            "exists": False,
            "employee": {"name": emp.name, "designation": emp.designation, "email": emp.email},
            "date": target.isoformat(),
        }

    kpi_values = (
        db.query(KPIEntry, KPI)
        .join(KPI, KPIEntry.kpi_id == KPI.id)
        .filter(KPIEntry.daily_entry_id == entry.id)
        .order_by(KPI.display_order)
        .all()
    )
    kpi_data = [
        {
            "name": kpi.name,
            "unit": kpi.unit,
            "value": kpi_entry.value,
        }
        for kpi_entry, kpi in kpi_values
    ]

    return {
        "exists": True,
        "employee": {"name": emp.name, "designation": emp.designation, "email": emp.email},
        "date": target.isoformat(),
        "type": entry.entry_type,
        "submitted_at": entry.submitted_at.isoformat() if entry.submitted_at else None,
        "comments": entry.comments,
        "kpi_values": kpi_data,
    }


# ============================================================
# Unlock Requests (admin side)
# ============================================================

@router.get("/api/unlock-requests")
def list_unlock_requests(
    status: Optional[str] = None,  # pending | approved | denied | None=all
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List unlock requests, optionally filtered by status."""
    q = db.query(UnlockRequest, Employee).join(Employee, UnlockRequest.employee_id == Employee.id)
    if status:
        q = q.filter(UnlockRequest.status == status)
    q = q.order_by(UnlockRequest.requested_at.desc())
    rows = q.limit(200).all()

    pending_count = (
        db.query(UnlockRequest)
        .filter(UnlockRequest.status == "pending")
        .count()
    )

    out = []
    for req, emp in rows:
        req_kind = getattr(req, "kind", None) or "legacy_entry"
        entry_type = None
        entry_locked = None
        if req_kind == "legacy_entry":
            # Legacy path — look up the DailyEntry for context
            entry = (
                db.query(DailyEntry)
                .filter_by(employee_id=emp.id, entry_date=req.entry_date)
                .first()
            )
            entry_type = entry.entry_type if entry else None
            entry_locked = entry.locked if entry else None
        out.append({
            "id": req.id,
            "kind": req_kind,
            "employee": {
                "id": emp.id,
                "code": emp.employee_code,
                "name": emp.name,
                "designation": emp.designation,
                "email": emp.email,
            },
            "entry_date": req.entry_date.isoformat(),
            "entry_type": entry_type,
            "entry_locked": entry_locked,
            "reason": req.reason,
            "status": req.status,
            "admin_response": req.admin_response,
            "decided_by_email": req.decided_by_email,
            "requested_at": req.requested_at.isoformat(),
            "decided_at": req.decided_at.isoformat() if req.decided_at else None,
        })
    return {"pending_count": pending_count, "requests": out}


@router.post("/api/unlock-requests/{req_id}/approve")
async def approve_unlock_request(
    req_id: int,
    request: Request,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Approve an unlock request — unlocks the corresponding daily entry."""
    body = {}
    try:
        if await request.body():
            body = await request.json()
    except Exception:
        body = {}
    admin_response = (body.get("admin_response") or "").strip() or None

    req = db.query(UnlockRequest).filter_by(id=req_id).first()
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, f"Request is already {req.status}")

    req_kind = getattr(req, "kind", None) or "legacy_entry"

    if req_kind in ("task_report", "monthly_kpi"):
        # For task reports and monthly KPI, "unlocking" just means marking
        # the request approved. The respective route helpers check for status='approved'.
        req.status = "approved"
        req.admin_response = admin_response
        req.decided_by_email = user.email
        req.decided_by_code = user.employee_code
        req.decided_at = datetime.utcnow()
        db.add(AuditLog(
            actor_email=user.email,
            actor_code=user.employee_code,
            action=f"{req_kind}_unlock_approved",
            details={
                "request_id": req.id,
                "employee_id": req.employee_id,
                "target_date": req.entry_date.isoformat(),
                "reason": req.reason,
                "admin_response": admin_response,
            },
        ))
        db.commit()
        return {"success": True}

    # Legacy path — unlock the DailyEntry row
    entry = (
        db.query(DailyEntry)
        .filter_by(employee_id=req.employee_id, entry_date=req.entry_date)
        .first()
    )
    if not entry:
        req.status = "approved"
        req.admin_response = (admin_response or "") + " (note: original entry no longer exists)"
        req.decided_by_email = user.email
        req.decided_by_code = user.employee_code
        req.decided_at = datetime.utcnow()
        db.commit()
        return {"success": True, "warning": "Entry no longer exists"}

    entry.locked = False
    req.status = "approved"
    req.admin_response = admin_response
    req.decided_by_email = user.email
    req.decided_by_code = user.employee_code
    req.decided_at = datetime.utcnow()

    db.add(AuditLog(
        actor_email=user.email,
        actor_code=user.employee_code,
        action="unlock_request_approved",
        details={
            "request_id": req.id,
            "employee_id": req.employee_id,
            "entry_date": req.entry_date.isoformat(),
            "reason": req.reason,
            "admin_response": admin_response,
        },
    ))
    db.commit()
    return {"success": True}


@router.post("/api/unlock-requests/{req_id}/deny")
async def deny_unlock_request(
    req_id: int,
    request: Request,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Deny an unlock request."""
    body = {}
    try:
        if await request.body():
            body = await request.json()
    except Exception:
        body = {}
    admin_response = (body.get("admin_response") or "").strip()
    if not admin_response:
        raise HTTPException(400, "Please provide a reason for denial")

    req = db.query(UnlockRequest).filter_by(id=req_id).first()
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, f"Request is already {req.status}")

    req.status = "denied"
    req.admin_response = admin_response
    req.decided_by_email = user.email
    req.decided_by_code = user.employee_code
    req.decided_at = datetime.utcnow()

    db.add(AuditLog(
        actor_email=user.email,
        action="unlock_request_denied",
        details={
            "request_id": req.id,
            "employee_id": req.employee_id,
            "entry_date": req.entry_date.isoformat(),
            "reason": req.reason,
            "admin_response": admin_response,
        },
    ))
    db.commit()
    return {"success": True}


# ============================================================
# Stale employee cleanup (admin)
# ============================================================

@router.get("/api/inactive-employees")
def list_inactive_employees(
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List deactivated employees that may be blocking new records with the same email."""
    rows = (
        db.query(Employee)
        .filter(Employee.is_active.is_(False))
        .order_by(Employee.email)
        .all()
    )
    return [
        {
            "id": e.id,
            "name": e.name,
            "email": e.email,
            "designation": e.designation,
            "department": e.department,
        }
        for e in rows
    ]


@router.delete("/api/employees/{emp_id}/purge")
def purge_employee(
    emp_id: int,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Permanently delete an employee record AND all related data (entries, KPIs, requests).
    Use only to clean up stale/orphaned records that block re-adding the same email.
    """
    emp = db.query(Employee).filter_by(id=emp_id).first()
    if not emp:
        raise HTTPException(404, "Employee not found")

    name = emp.name
    email = emp.email

    # Cascade-delete related rows (most relations have ondelete=CASCADE
    # but we do explicit cleanup to be safe even if some don't)
    daily_entry_ids = [
        de.id for de in db.query(DailyEntry).filter_by(employee_id=emp_id).all()
    ]
    if daily_entry_ids:
        db.query(KPIEntry).filter(KPIEntry.daily_entry_id.in_(daily_entry_ids)).delete(synchronize_session=False)
    db.query(DailyEntry).filter_by(employee_id=emp_id).delete(synchronize_session=False)
    db.query(KPI).filter_by(employee_id=emp_id).delete(synchronize_session=False)
    db.query(UnlockRequest).filter_by(employee_id=emp_id).delete(synchronize_session=False)

    db.add(AuditLog(
        actor_email=user.email,
        action="employee_purged",
        details={"employee_id": emp_id, "name": name, "email": email},
    ))
    db.delete(emp)
    db.commit()
    return {"success": True, "purged": {"id": emp_id, "name": name, "email": email}}


@router.post("/api/purge-by-email")
async def purge_by_email(
    request: Request,
    user: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Purge ALL records (active or inactive) matching a given email.
    Useful for cleaning up an email collision blocking new employee creation.
    Body: {"email": "ppc@metfraa.com"}
    """
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "email is required in body")

    matches = db.query(Employee).filter(Employee.email == email).all()
    if not matches:
        return {"success": True, "purged_count": 0, "message": f"No records found for {email}"}

    purged = []
    for emp in matches:
        emp_id = emp.id
        name = emp.name
        # Cascade
        daily_entry_ids = [
            de.id for de in db.query(DailyEntry).filter_by(employee_id=emp_id).all()
        ]
        if daily_entry_ids:
            db.query(KPIEntry).filter(KPIEntry.daily_entry_id.in_(daily_entry_ids)).delete(synchronize_session=False)
        db.query(DailyEntry).filter_by(employee_id=emp_id).delete(synchronize_session=False)
        db.query(KPI).filter_by(employee_id=emp_id).delete(synchronize_session=False)
        db.query(UnlockRequest).filter_by(employee_id=emp_id).delete(synchronize_session=False)
        db.delete(emp)
        purged.append({"id": emp_id, "name": name})

    db.add(AuditLog(
        actor_email=user.email,
        action="purge_by_email",
        details={"email": email, "purged": purged},
    ))
    db.commit()
    return {"success": True, "purged_count": len(purged), "purged": purged}



# ============================================================
# Sub-batch 1C — Admin password/task-report management
# ============================================================

DEFAULT_PASSWORD = "Metfraa@123"


def _hash_password(plain: str) -> str:
    import bcrypt as _bcrypt
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


@router.post("/api/employees/{emp_id}/reset-password")
def admin_reset_employee_password(
    emp_id: int,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin-triggered password reset. Resets to Metfraa@123, forces change on next login."""
    emp = db.query(Employee).filter_by(id=emp_id).first()
    if not emp:
        raise HTTPException(404, "Employee not found")

    emp.password_hash = _hash_password(DEFAULT_PASSWORD)
    emp.must_reset_password = True

    db.add(AuditLog(
        actor_code=admin.employee_code,
        actor_email=admin.email,
        action="admin_password_reset",
        details={"target_employee_id": emp.id, "target_code": emp.employee_code, "target_name": emp.name},
    ))
    db.commit()
    return {
        "success": True,
        "message": f"Password reset to Metfraa@123 for {emp.name} ({emp.employee_code}).",
        "employee": {"id": emp.id, "code": emp.employee_code, "name": emp.name},
    }


@router.post("/api/employees/{emp_id}/toggle-task-report")
async def toggle_task_report(
    emp_id: int,
    request: Request,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Toggle can_submit_task_report on/off for an employee. Body: {"enabled": true|false}"""
    body = await request.json()
    enabled = bool(body.get("enabled", True))

    emp = db.query(Employee).filter_by(id=emp_id).first()
    if not emp:
        raise HTTPException(404, "Employee not found")

    old_value = emp.can_submit_task_report
    emp.can_submit_task_report = enabled

    db.add(AuditLog(
        actor_code=admin.employee_code,
        actor_email=admin.email,
        action="toggle_task_report",
        details={"target_employee_id": emp.id, "old": old_value, "new": enabled},
    ))
    db.commit()
    return {
        "success": True,
        "employee_id": emp.id,
        "can_submit_task_report": enabled,
    }


@router.get("/api/password-reset-requests")
def list_password_reset_requests(
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all password reset requests (pending first)."""
    reqs = (
        db.query(PasswordResetRequest)
        .order_by(PasswordResetRequest.requested_at.desc())
        .limit(100)
        .all()
    )
    out = []
    for r in reqs:
        emp = r.employee
        out.append({
            "id": r.id,
            "employee_id": r.employee_id,
            "employee_name": emp.name if emp else "(deleted)",
            "employee_code": emp.employee_code if emp else "?",
            "reason": r.reason,
            "status": r.status,
            "requested_at": r.requested_at.isoformat() if r.requested_at else None,
            "fulfilled_at": r.fulfilled_at.isoformat() if r.fulfilled_at else None,
            "fulfilled_by_code": r.fulfilled_by_code,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "token": r.token,
        })
    return out


@router.post("/api/password-reset-requests/{req_id}/approve")
def admin_approve_reset_request(
    req_id: int,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Approve a pending reset request from admin panel (no email link needed)."""
    from datetime import datetime as _dt

    req = db.query(PasswordResetRequest).filter_by(id=req_id).first()
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, f"Request is already {req.status}")

    emp = req.employee
    if not emp:
        raise HTTPException(404, "Employee no longer exists")

    emp.password_hash = _hash_password(DEFAULT_PASSWORD)
    emp.must_reset_password = True
    req.status = "fulfilled"
    req.fulfilled_at = _dt.utcnow()
    req.fulfilled_by_code = admin.employee_code

    db.add(AuditLog(
        actor_code=admin.employee_code,
        actor_email=admin.email,
        action="password_reset_approved_in_admin",
        details={"target_employee_id": emp.id, "target_code": emp.employee_code, "request_id": req.id},
    ))
    db.commit()
    return {"success": True, "employee_name": emp.name, "employee_code": emp.employee_code}


@router.post("/api/password-reset-requests/{req_id}/deny")
def admin_deny_reset_request(
    req_id: int,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Deny a pending reset request."""
    from datetime import datetime as _dt

    req = db.query(PasswordResetRequest).filter_by(id=req_id).first()
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, f"Request is already {req.status}")

    req.status = "denied"
    req.fulfilled_at = _dt.utcnow()
    req.fulfilled_by_code = admin.employee_code

    db.add(AuditLog(
        actor_code=admin.employee_code,
        actor_email=admin.email,
        action="password_reset_denied_in_admin",
        details={"target_employee_id": req.employee_id, "request_id": req.id},
    ))
    db.commit()
    return {"success": True}



# ============================================================
# Sub-batch 2B — Daily consolidated task report Excel
# ============================================================

@router.get("/api/daily-task-excel/{report_date}")
async def download_daily_task_excel(
    report_date: str,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Generate the consolidated Excel for a specific date and return as download.

    Does NOT email or upload. For admin ad-hoc use.
    """
    from ..services.daily_task_excel import build_excel
    from fastapi.responses import Response as FastAPIResponse

    try:
        target = date.fromisoformat(report_date)
    except ValueError:
        raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")

    xlsx_bytes, stats = build_excel(target, db)
    filename = f"MetfraaTasks_{target.strftime('%Y-%m-%d')}.xlsx"
    return FastAPIResponse(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/api/daily-task-excel/{report_date}/send")
async def send_daily_task_excel(
    report_date: str,
    admin: Employee = Depends(require_admin),
):
    """Manually trigger the daily task Excel + email dispatch for a specific date.

    Same code path as the 10 AM cron. Useful when the cron missed or a re-send is needed.
    """
    from ..services.daily_task_excel import generate_and_dispatch

    try:
        target = date.fromisoformat(report_date)
    except ValueError:
        raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")

    result = await generate_and_dispatch(target)

    return {
        "success": True,
        "result": result,
    }



# ============================================================
# Sub-batch 3 — Monthly KPI admin dashboard
# ============================================================

@router.get("/api/monthly-kpi/{year}/{month}")
def admin_monthly_kpi_dashboard(
    year: int,
    month: int,
    admin: Employee = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all KPI-tracked employees and their scoring status for the given month.

    Returns:
      [
        {
          "employee": {...},
          "n_kpis": N,
          "n_submitted": M,
          "final_score": X,
          "actuals": [{kpi, target, actual, weight, achievement_pct, weighted_score}, ...],
        },
        ...
      ]
    """
    if not (1 <= month <= 12):
        raise HTTPException(400, "Invalid month")

    from ..routes.monthly_kpi import compute_weighted_score

    emps = (
        db.query(Employee)
        .filter(Employee.is_active.is_(True))
        .order_by(Employee.name.asc())
        .all()
    )

    out = []
    for e in emps:
        n_kpis = _kpi_count(db, e.id)
        if n_kpis == 0:
            continue
        actuals = (
            db.query(MonthlyKPIActual)
            .filter_by(employee_id=e.id, year=year, month=month)
            .all()
        )
        n_submitted = len(actuals)
        if n_submitted > 0:
            score_data = compute_weighted_score(actuals)
        else:
            score_data = {"final_score": 0, "total_weight": 0, "rows": []}

        # Annotate rows with KPI names
        kpis_by_id = {k.id: k for k in db.query(KPI).filter_by(employee_id=e.id).all()}
        for row in score_data["rows"]:
            k = kpis_by_id.get(row["kpi_id"])
            row["name"] = k.name if k else "(deleted KPI)"

        out.append({
            "employee": {
                "id": e.id,
                "code": e.employee_code,
                "name": e.name,
                "designation": e.designation,
                "department": e.department,
            },
            "n_kpis": n_kpis,
            "n_submitted": n_submitted,
            "fully_submitted": n_submitted >= n_kpis,
            "final_score": score_data["final_score"],
            "total_weight": score_data["total_weight"],
            "actuals": score_data["rows"],
        })
    return out
