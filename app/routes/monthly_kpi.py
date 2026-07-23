"""Monthly KPI actuals — end-of-month submission by employees.

Submission window: last 5 days of month + first 3 days of next month.
Once submitted, no approval — self-serve like the daily task report.
Unlock requests reuse the UnlockRequest table with kind='monthly_kpi'.
"""
import calendar
import os
from datetime import date, datetime

import pytz
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user_ready
from ..models import (
    AuditLog, Employee, KPI, MonthlyKPIActual, UnlockRequest,
)

router = APIRouter(prefix="/monthly-kpi", tags=["monthly-kpi"])
templates = Jinja2Templates(directory="app/templates")

IST = pytz.timezone(os.getenv("TIMEZONE", "Asia/Kolkata"))


# ============================================================
# Window logic — last 5 days of month + first 3 of next month
# ============================================================

def _now_ist_date() -> date:
    return datetime.now(IST).date()


def _submission_window_for(target_year: int, target_month: int) -> tuple[date, date]:
    """Return (start_date, end_date) INCLUSIVE for submitting KPIs of (target_year, target_month).

    Window opens on the 26th of target month (5 days before month-end typically)
    and closes on the 3rd of the following month.
    """
    # We use 26th of target month → 3rd of the next month.
    # (25th-of-month → 25th-of-next-month is common in HR; here we take 5 days back = 26th onwards)
    last_day = calendar.monthrange(target_year, target_month)[1]
    open_day = min(last_day, last_day - 4)  # last 5 days incl. last day
    start = date(target_year, target_month, open_day)

    # End = 3rd of following month
    if target_month == 12:
        end = date(target_year + 1, 1, 3)
    else:
        end = date(target_year, target_month + 1, 3)
    return start, end


def _can_submit_now(target_year: int, target_month: int) -> bool:
    """Check if the submission window for (year, month) is currently open."""
    today = _now_ist_date()
    start, end = _submission_window_for(target_year, target_month)
    return start <= today <= end


def _submittable_periods() -> list[tuple[int, int]]:
    """Return list of (year, month) currently open for submission.

    Typically returns 1 period, but during 1st-3rd of a month, both current-1 (open)
    and current+1 (not yet open) might come into play. We only return periods that
    are ACTUALLY within window.
    """
    today = _now_ist_date()
    periods = []
    # Previous month
    if today.month == 1:
        prev_y, prev_m = today.year - 1, 12
    else:
        prev_y, prev_m = today.year, today.month - 1
    if _can_submit_now(prev_y, prev_m):
        periods.append((prev_y, prev_m))
    # Current month
    if _can_submit_now(today.year, today.month):
        periods.append((today.year, today.month))
    return periods


def _has_approved_unlock(db: Session, employee_id: int, year: int, month: int) -> bool:
    """Check for approved unlock request on this monthly KPI period."""
    # We encode year/month as a date (1st of that month) for reuse
    target_date = date(year, month, 1)
    return db.query(UnlockRequest).filter(
        UnlockRequest.employee_id == employee_id,
        UnlockRequest.entry_date == target_date,
        UnlockRequest.kind == "monthly_kpi",
        UnlockRequest.status == "approved",
    ).first() is not None


def _has_pending_unlock(db: Session, employee_id: int, year: int, month: int) -> bool:
    target_date = date(year, month, 1)
    return db.query(UnlockRequest).filter(
        UnlockRequest.employee_id == employee_id,
        UnlockRequest.entry_date == target_date,
        UnlockRequest.kind == "monthly_kpi",
        UnlockRequest.status == "pending",
    ).first() is not None


# ============================================================
# Scoring helpers
# ============================================================

def compute_achievement_pct(actual: float, target: float) -> float:
    """Return achievement % capped at 100%.

    If target is 0, return 0 (avoid divide-by-zero).
    """
    if target <= 0:
        return 0.0
    pct = (actual / target) * 100.0
    if pct > 100.0:
        pct = 100.0  # user chose (A) — cap at 100%
    if pct < 0:
        pct = 0.0
    return round(pct, 2)


def compute_weighted_score(actuals: list[MonthlyKPIActual]) -> dict:
    """Return {"final_score": X, "rows": [...]}."""
    rows = []
    total_score = 0.0
    total_weight = 0.0
    for a in actuals:
        ach_pct = compute_achievement_pct(a.actual_value, a.target_snapshot)
        weighted = (ach_pct * a.weight_snapshot) / 100.0  # weight is a % → weighted contribution
        total_score += weighted
        total_weight += a.weight_snapshot
        rows.append({
            "kpi_id": a.kpi_id,
            "actual": a.actual_value,
            "target": a.target_snapshot,
            "weight": a.weight_snapshot,
            "unit": a.unit_snapshot,
            "achievement_pct": ach_pct,
            "weighted_score": round(weighted, 2),
        })
    return {
        "final_score": round(total_score, 2),
        "total_weight": round(total_weight, 2),
        "rows": rows,
    }


# ============================================================
# Screen
# ============================================================

@router.get("/", response_class=HTMLResponse)
def monthly_kpi_page(
    request: Request,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Render the monthly KPI submission screen."""
    today = _now_ist_date()
    return templates.TemplateResponse(
        request,
        "monthly_kpi.html",
        {
            "user": user,
            "today_iso": today.isoformat(),
        },
    )


# ============================================================
# API — period + KPIs metadata
# ============================================================

@router.get("/api/period/{year}/{month}")
def get_period(
    year: int,
    month: int,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Fetch the KPIs + any existing actuals for a specific year/month."""
    if not (1 <= month <= 12):
        raise HTTPException(400, "Invalid month")

    kpis = (
        db.query(KPI)
        .filter(KPI.employee_id == user.id)
        .order_by(KPI.display_order.asc(), KPI.id.asc())
        .all()
    )

    if not kpis:
        return {
            "year": year,
            "month": month,
            "editable": False,
            "editable_reason": "You have no KPIs assigned.",
            "kpis": [],
            "already_submitted": False,
        }

    # Load existing actuals for this period
    existing = (
        db.query(MonthlyKPIActual)
        .filter(
            MonthlyKPIActual.employee_id == user.id,
            MonthlyKPIActual.year == year,
            MonthlyKPIActual.month == month,
        )
        .all()
    )
    by_kpi = {a.kpi_id: a for a in existing}
    already_submitted = len(existing) > 0

    window_open = _can_submit_now(year, month)
    approved_unlock = _has_approved_unlock(db, user.id, year, month)
    pending_unlock = _has_pending_unlock(db, user.id, year, month)
    editable = window_open or approved_unlock

    editable_reason = None
    if not editable:
        if pending_unlock:
            editable_reason = "Unlock request pending admin approval."
        else:
            start, end = _submission_window_for(year, month)
            editable_reason = (
                f"Submission window was {start.strftime('%d %b')} to {end.strftime('%d %b')}. "
                "Request an unlock from admin to submit late."
            )

    start_d, end_d = _submission_window_for(year, month)
    kpi_data = []
    for k in kpis:
        actual = by_kpi.get(k.id)
        kpi_data.append({
            "id": k.id,
            "name": k.name,
            "unit": k.unit,
            "weight": k.weight,
            "target": k.target,
            "actual_value": actual.actual_value if actual else None,
            "submitted_at": actual.submitted_at.isoformat() if actual else None,
        })

    return {
        "year": year,
        "month": month,
        "window_start": start_d.isoformat(),
        "window_end": end_d.isoformat(),
        "editable": editable,
        "editable_reason": editable_reason,
        "pending_unlock": pending_unlock,
        "already_submitted": already_submitted,
        "kpis": kpi_data,
    }


@router.get("/api/current-periods")
def current_periods(
    user: Employee = Depends(get_current_user_ready),
):
    """Return which periods are currently open for submission."""
    periods = _submittable_periods()
    return {"periods": [{"year": y, "month": m} for y, m in periods]}


# ============================================================
# API — Save
# ============================================================

@router.post("/api/save")
async def save_actuals(
    request: Request,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Save (upsert) monthly KPI actuals for an employee.

    Body:
      {"year": Y, "month": M, "actuals": [{"kpi_id": N, "value": X}, ...]}
    """
    body = await request.json()
    try:
        year = int(body.get("year"))
        month = int(body.get("month"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid year/month")
    if not (1 <= month <= 12):
        raise HTTPException(400, "Invalid month")

    approved_unlock = _has_approved_unlock(db, user.id, year, month)
    if not _can_submit_now(year, month) and not approved_unlock:
        raise HTTPException(403, "Submission window is closed. Request an unlock from admin.")

    kpis = (
        db.query(KPI)
        .filter(KPI.employee_id == user.id)
        .all()
    )
    kpi_by_id = {k.id: k for k in kpis}
    if not kpi_by_id:
        raise HTTPException(400, "You have no KPIs assigned.")

    raw_actuals = body.get("actuals", [])
    if not isinstance(raw_actuals, list) or not raw_actuals:
        raise HTTPException(400, "No actuals provided.")

    now = datetime.utcnow()
    saved = 0
    for row in raw_actuals:
        try:
            kpi_id = int(row.get("kpi_id"))
            value = float(row.get("value", 0))
        except (TypeError, ValueError):
            continue
        kpi = kpi_by_id.get(kpi_id)
        if not kpi:
            continue  # KPI doesn't belong to this employee, skip silently
        if value < 0:
            value = 0.0

        existing = (
            db.query(MonthlyKPIActual)
            .filter_by(employee_id=user.id, kpi_id=kpi_id, year=year, month=month)
            .first()
        )
        if existing:
            existing.actual_value = value
            existing.last_edited_at = now
            # Refresh snapshots so any weight/target changes are reflected
            existing.target_snapshot = kpi.target
            existing.weight_snapshot = kpi.weight
            existing.unit_snapshot = kpi.unit
        else:
            db.add(MonthlyKPIActual(
                employee_id=user.id,
                kpi_id=kpi_id,
                year=year,
                month=month,
                actual_value=value,
                target_snapshot=kpi.target,
                weight_snapshot=kpi.weight,
                unit_snapshot=kpi.unit,
                submitted_at=now,
                last_edited_at=now,
            ))
        saved += 1

    db.add(AuditLog(
        actor_code=user.employee_code,
        actor_email=user.email,
        action="monthly_kpi_saved",
        details={"year": year, "month": month, "n_actuals": saved},
    ))
    db.commit()

    return {"success": True, "saved": saved, "year": year, "month": month}


# ============================================================
# API — Score (view own scoring)
# ============================================================

@router.get("/api/score/{year}/{month}")
def get_own_score(
    year: int,
    month: int,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Get the weighted score for the current user for a given month."""
    actuals = (
        db.query(MonthlyKPIActual)
        .filter_by(employee_id=user.id, year=year, month=month)
        .all()
    )
    if not actuals:
        return {"year": year, "month": month, "final_score": 0, "rows": [], "submitted": False}

    kpis_by_id = {k.id: k for k in db.query(KPI).filter(KPI.employee_id == user.id).all()}
    result = compute_weighted_score(actuals)
    # Annotate rows with KPI names
    for row in result["rows"]:
        k = kpis_by_id.get(row["kpi_id"])
        row["name"] = k.name if k else "(deleted KPI)"
    return {
        "year": year,
        "month": month,
        "final_score": result["final_score"],
        "total_weight": result["total_weight"],
        "rows": result["rows"],
        "submitted": True,
    }


# ============================================================
# API — Request unlock
# ============================================================

@router.post("/api/request-unlock")
async def request_unlock(
    request: Request,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    body = await request.json()
    try:
        year = int(body.get("year"))
        month = int(body.get("month"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid year/month")
    reason = (body.get("reason") or "").strip()
    if len(reason) < 5:
        raise HTTPException(400, "Please provide a reason (at least 5 characters).")

    target_date = date(year, month, 1)
    existing = (
        db.query(UnlockRequest)
        .filter(
            UnlockRequest.employee_id == user.id,
            UnlockRequest.entry_date == target_date,
            UnlockRequest.kind == "monthly_kpi",
            UnlockRequest.status == "pending",
        )
        .first()
    )
    if existing:
        raise HTTPException(400, "You already have a pending unlock request for this month.")

    req = UnlockRequest(
        employee_id=user.id,
        entry_date=target_date,
        kind="monthly_kpi",
        reason=reason,
        status="pending",
    )
    db.add(req)
    db.add(AuditLog(
        actor_code=user.employee_code,
        actor_email=user.email,
        action="monthly_kpi_unlock_requested",
        details={"year": year, "month": month, "reason": reason},
    ))
    db.commit()
    return {"success": True, "message": "Unlock request sent to admin."}
