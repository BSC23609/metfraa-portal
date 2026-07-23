"""User-facing routes: dashboard, daily entry submission, my reports."""
from datetime import date, datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import extract

from ..database import get_db
from ..models import Employee, KPI, DailyEntry, KPIEntry, UnlockRequest
from ..deps import get_current_user
from ..services.scoring import compute_monthly_score, get_daily_kpi_trend

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: Employee = Depends(get_current_user)):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"user": user, "today": date.today().isoformat()},
    )


# ---------- API endpoints used by Alpine.js front-end ----------

@router.get("/api/me")
def api_me(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    kpis = (
        db.query(KPI)
        .filter_by(employee_id=user.id, is_active=True)
        .order_by(KPI.display_order)
        .all()
    )
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "designation": user.designation,
        "department": user.department,
        "is_admin": user.is_admin,
        "kpis": [
            {
                "id": k.id,
                "name": k.name,
                "unit": k.unit,
                "weight": k.weight,
                "target": k.monthly_target,
            } for k in kpis
        ],
    }


@router.get("/api/entry/{entry_date}")
def api_get_entry(entry_date: str, user: Employee = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Get the entry for a specific date, if it exists."""
    try:
        d = date.fromisoformat(entry_date)
    except ValueError:
        raise HTTPException(400, "Invalid date")

    entry = (
        db.query(DailyEntry)
        .filter_by(employee_id=user.id, entry_date=d)
        .first()
    )
    if not entry:
        return {"exists": False, "date": entry_date}

    values = {kv.kpi_id: kv.value for kv in entry.kpi_values}

    # Look up any unlock request for this date (most recent first)
    unlock_req = (
        db.query(UnlockRequest)
        .filter_by(employee_id=user.id, entry_date=d)
        .order_by(UnlockRequest.requested_at.desc())
        .first()
    )
    unlock_info = None
    if unlock_req:
        unlock_info = {
            "id": unlock_req.id,
            "status": unlock_req.status,
            "reason": unlock_req.reason,
            "admin_response": unlock_req.admin_response,
            "requested_at": unlock_req.requested_at.isoformat(),
            "decided_at": unlock_req.decided_at.isoformat() if unlock_req.decided_at else None,
        }

    return {
        "exists": True,
        "date": entry.entry_date.isoformat(),
        "type": entry.entry_type,
        "comments": entry.comments,
        "submitted_at": entry.submitted_at.isoformat() if entry.submitted_at else None,
        "kpi_values": values,
        "locked": entry.locked,
        "unlock_request": unlock_info,
    }


@router.post("/api/entry")
async def api_submit_entry(
    request: Request,
    user: Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit a daily entry. Locked once submitted."""
    body = await request.json()

    # Validate
    entry_date_str = body.get("date")
    entry_type = body.get("type", "work")
    comments = body.get("comments", "") or ""
    kpi_values = body.get("kpi_values", {}) or {}

    valid_types = {"work", "casual_leave", "site_remote", "sunday", "holiday"}
    if entry_type not in valid_types:
        raise HTTPException(400, f"Invalid type. Must be one of {valid_types}")

    try:
        d = date.fromisoformat(entry_date_str)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid date")

    if d > date.today():
        raise HTTPException(400, "Cannot submit a future date")

    # Check existing — allow update if unlocked (admin-approved unlock request)
    existing = (
        db.query(DailyEntry)
        .filter_by(employee_id=user.id, entry_date=d)
        .first()
    )
    if existing and existing.locked:
        raise HTTPException(409, "Entry for this date already exists and is locked")

    if existing:
        # Re-submitting after admin approved unlock request
        # Wipe old KPI values; replace with new ones
        entry = existing
        entry.entry_type = entry_type
        entry.comments = comments.strip() or None
        entry.locked = True
        entry.submitted_at = datetime.utcnow()
        # Delete old KPI values; will be recreated below
        db.query(KPIEntry).filter_by(daily_entry_id=entry.id).delete()
        db.flush()

        # Mark the unlock request as "used" — find the most recent approved one for this date
        used_req = (
            db.query(UnlockRequest)
            .filter_by(employee_id=user.id, entry_date=d, status="approved")
            .order_by(UnlockRequest.decided_at.desc())
            .first()
        )
        if used_req:
            used_req.status = "completed"
    else:
        # Create fresh entry
        entry = DailyEntry(
            employee_id=user.id,
            entry_date=d,
            entry_type=entry_type,
            comments=comments.strip() or None,
            locked=True,
        )
        db.add(entry)
        db.flush()

    if entry_type == "work":
        kpis = db.query(KPI).filter_by(employee_id=user.id, is_active=True).all()
        kpi_ids = {k.id for k in kpis}
        for k_id_str, val in kpi_values.items():
            try:
                k_id = int(k_id_str)
                v = float(val) if val not in (None, "") else 0.0
            except (TypeError, ValueError):
                continue
            if k_id not in kpi_ids:
                continue
            db.add(KPIEntry(daily_entry_id=entry.id, kpi_id=k_id, value=v))

    db.commit()
    return {"success": True, "id": entry.id}


@router.get("/api/my-summary")
def api_my_summary(
    year: Optional[int] = None,
    month: Optional[int] = None,
    user: Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Current month summary for the logged-in user."""
    today = date.today()
    year = year or today.year
    month = month or today.month
    data = compute_monthly_score(db, user.id, year, month)
    trend = get_daily_kpi_trend(db, user.id, year, month)
    return {
        "final_score": data["final_score"],
        "year": year,
        "month": month,
        "kpi_results": [
            {
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
        "trend": {
            "days": trend["days"],
            "daily_totals": trend["daily_totals"],
        },
    }


@router.get("/api/my-history")
def api_my_history(user: Employee = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """List of all my submitted entries — for the calendar/history view."""
    entries = (
        db.query(DailyEntry)
        .filter_by(employee_id=user.id)
        .order_by(DailyEntry.entry_date.desc())
        .limit(120)
        .all()
    )
    return [
        {
            "date": e.entry_date.isoformat(),
            "type": e.entry_type,
            "submitted_at": e.submitted_at.isoformat() if e.submitted_at else None,
        }
        for e in entries
    ]


# ============================================================
# Unlock Requests (employee side)
# ============================================================

@router.post("/api/unlock-request")
async def create_unlock_request(
    request: Request,
    user: Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Employee requests to unlock a previously-submitted entry."""
    body = await request.json()
    entry_date_str = body.get("entry_date")
    reason = (body.get("reason") or "").strip()

    if not entry_date_str:
        raise HTTPException(400, "entry_date is required")
    if not reason:
        raise HTTPException(400, "Reason is required")
    if len(reason) > 1000:
        raise HTTPException(400, "Reason too long (max 1000 chars)")

    try:
        entry_date = date.fromisoformat(entry_date_str)
    except ValueError:
        raise HTTPException(400, "Invalid date format")

    # Must be within last 7 days
    today = date.today()
    if entry_date > today:
        raise HTTPException(400, "Cannot request unlock for future date")
    if (today - entry_date).days > 7:
        raise HTTPException(400, "Unlock requests are only allowed within 7 days of submission")

    # Must have an existing locked entry
    entry = (
        db.query(DailyEntry)
        .filter_by(employee_id=user.id, entry_date=entry_date)
        .first()
    )
    if not entry:
        raise HTTPException(404, "No entry exists for that date — nothing to unlock")
    if not entry.locked:
        raise HTTPException(400, "This entry is already unlocked")

    # Don't allow duplicate pending requests
    existing = (
        db.query(UnlockRequest)
        .filter(
            UnlockRequest.employee_id == user.id,
            UnlockRequest.entry_date == entry_date,
            UnlockRequest.status == "pending",
        )
        .first()
    )
    if existing:
        raise HTTPException(400, "You already have a pending request for this date")

    req = UnlockRequest(
        employee_id=user.id,
        entry_date=entry_date,
        reason=reason,
        status="pending",
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return {
        "id": req.id,
        "status": req.status,
        "requested_at": req.requested_at.isoformat(),
    }


@router.get("/api/my-unlock-requests")
def list_my_unlock_requests(
    user: Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the current user's unlock requests (last 30 days)."""
    cutoff = datetime.utcnow() - timedelta(days=30)
    reqs = (
        db.query(UnlockRequest)
        .filter(
            UnlockRequest.employee_id == user.id,
            UnlockRequest.requested_at >= cutoff,
        )
        .order_by(UnlockRequest.requested_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "entry_date": r.entry_date.isoformat(),
            "reason": r.reason,
            "status": r.status,
            "admin_response": r.admin_response,
            "requested_at": r.requested_at.isoformat(),
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        }
        for r in reqs
    ]
