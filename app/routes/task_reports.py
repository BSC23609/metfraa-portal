"""Task Report routes — daily task submission for employees.

Employees with can_submit_task_report=True use these endpoints.
Locks after 9:45 AM IST the following day. Unlock via UnlockRequest flow.
"""
import os
from datetime import date, datetime, time, timedelta

import pytz
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user_ready
from ..models import (
    AuditLog, DailyTaskItem, DailyTaskReport, Employee, UnlockRequest,
)

router = APIRouter(prefix="/task-reports", tags=["task-reports"])
templates = Jinja2Templates(directory="app/templates")

# Locking config
IST = pytz.timezone(os.getenv("TIMEZONE", "Asia/Kolkata"))
LOCK_HOUR = 9   # 9:45 AM IST next day
LOCK_MINUTE = 45


# ============================================================
# Helpers
# ============================================================

def _now_ist() -> datetime:
    return datetime.now(IST)


def _today_ist() -> date:
    return _now_ist().date()


def _lock_moment_for(report_date: date) -> datetime:
    """Return the moment (in IST) when the report for a given date locks.

    Reports lock at 9:45 AM the DAY AFTER their report_date.
    Sundays get an extended window: they lock at 9:45 AM Monday.
    """
    lock_day = report_date + timedelta(days=1)
    naive = datetime.combine(lock_day, time(LOCK_HOUR, LOCK_MINUTE))
    return IST.localize(naive)


def _is_editable(report_date: date, has_active_unlock: bool = False) -> bool:
    """A report is editable when:
      - It's for today or a future date
      - It's for yesterday and we haven't crossed 9:45 AM today yet
      - It has an approved unlock request
    """
    if has_active_unlock:
        return True
    today = _today_ist()
    if report_date >= today:
        return True
    lock_moment = _lock_moment_for(report_date)
    return _now_ist() < lock_moment


def _has_approved_unlock(db: Session, employee_id: int, report_date: date) -> bool:
    """Check whether an approved unlock request exists for this employee+date."""
    approved = (
        db.query(UnlockRequest)
        .filter(
            UnlockRequest.employee_id == employee_id,
            UnlockRequest.entry_date == report_date,
            UnlockRequest.kind == "task_report",
            UnlockRequest.status == "approved",
        )
        .first()
    )
    return approved is not None


def _has_pending_unlock(db: Session, employee_id: int, report_date: date) -> bool:
    """Check whether a pending unlock request exists for this employee+date."""
    pending = (
        db.query(UnlockRequest)
        .filter(
            UnlockRequest.employee_id == employee_id,
            UnlockRequest.entry_date == report_date,
            UnlockRequest.kind == "task_report",
            UnlockRequest.status == "pending",
        )
        .first()
    )
    return pending is not None


def _report_to_dict(report: DailyTaskReport, editable: bool, pending_unlock: bool) -> dict:
    """Serialize a report + items for JSON response."""
    return {
        "id": report.id,
        "employee_id": report.employee_id,
        "report_date": report.report_date.isoformat(),
        "tomorrow_plan": report.tomorrow_plan or "",
        "blockers": report.blockers or "",
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
        "last_edited_at": report.last_edited_at.isoformat() if report.last_edited_at else None,
        "locked": report.locked,
        "editable": editable,
        "pending_unlock": pending_unlock,
        "items": [
            {
                "id": it.id,
                "sequence": it.sequence,
                "task_description": it.task_description,
                "status": it.status,
                "project": it.project or "",
                "remarks": it.remarks or "",
            }
            for it in sorted(report.items, key=lambda i: i.sequence)
        ],
    }


def _empty_report_dict(report_date: date, editable: bool) -> dict:
    """Return a placeholder for dates where no report exists yet."""
    return {
        "id": None,
        "employee_id": None,
        "report_date": report_date.isoformat(),
        "tomorrow_plan": "",
        "blockers": "",
        "submitted_at": None,
        "last_edited_at": None,
        "locked": not editable,
        "editable": editable,
        "pending_unlock": False,
        "items": [],
    }


def _require_task_report_permission(user: Employee) -> None:
    if not user.can_submit_task_report:
        raise HTTPException(
            status_code=403,
            detail="Task report submission is not enabled for your account.",
        )


# ============================================================
# Screen — HTML page
# ============================================================

@router.get("/", response_class=HTMLResponse)
def task_report_page(
    request: Request,
    user: Employee = Depends(get_current_user_ready),
):
    """Render the daily task report screen."""
    if not user.can_submit_task_report:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        request,
        "daily_task_report.html",
        {"user": user, "today_ist": _today_ist().isoformat()},
    )


# ============================================================
# API — Load a specific date's report
# ============================================================

@router.get("/api/date/{report_date}")
def get_report_for_date(
    report_date: str,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Fetch (or create empty view of) the report for a specific date."""
    _require_task_report_permission(user)
    try:
        target = date.fromisoformat(report_date)
    except ValueError:
        raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")

    approved_unlock = _has_approved_unlock(db, user.id, target)
    pending_unlock = _has_pending_unlock(db, user.id, target)
    editable = _is_editable(target, has_active_unlock=approved_unlock)

    report = (
        db.query(DailyTaskReport)
        .filter_by(employee_id=user.id, report_date=target)
        .first()
    )
    if not report:
        return _empty_report_dict(target, editable)
    return _report_to_dict(report, editable, pending_unlock)


# ============================================================
# API — Save (create or update) a report
# ============================================================

@router.post("/api/save")
async def save_report(
    request: Request,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Create or update the task report for a given date.

    Body:
      {
        "report_date": "YYYY-MM-DD",
        "items": [ {task_description, status, project, remarks}, ... ],
        "tomorrow_plan": "...",
        "blockers": "..."
      }

    Locking rules:
      - Report for a future date  → rejected (no future submissions)
      - Report for editable date  → saved (create or update)
      - Report for locked date w/o approved unlock → rejected
    """
    _require_task_report_permission(user)
    body = await request.json()

    try:
        target = date.fromisoformat(body.get("report_date", ""))
    except ValueError:
        raise HTTPException(400, "Invalid or missing report_date")

    today = _today_ist()
    if target > today:
        raise HTTPException(400, "Cannot submit for a future date.")

    approved_unlock = _has_approved_unlock(db, user.id, target)
    editable = _is_editable(target, has_active_unlock=approved_unlock)
    if not editable:
        raise HTTPException(
            403,
            "This report is locked. Request an unlock from your admin to make changes.",
        )

    tomorrow_plan = (body.get("tomorrow_plan") or "").strip()
    blockers = (body.get("blockers") or "").strip()

    raw_items = body.get("items", []) or []
    items = []
    for i, raw in enumerate(raw_items, start=1):
        task_desc = (raw.get("task_description") or "").strip()
        if not task_desc:
            continue  # skip empty rows
        status = (raw.get("status") or "pending").strip().lower()
        if status not in ("completed", "pending"):
            status = "pending"
        items.append({
            "sequence": i,
            "task_description": task_desc,
            "status": status,
            "project": (raw.get("project") or "").strip() or None,
            "remarks": (raw.get("remarks") or "").strip() or None,
        })

    if not items and not tomorrow_plan and not blockers:
        raise HTTPException(400, "Report is empty. Add at least one task.")

    # Upsert
    report = (
        db.query(DailyTaskReport)
        .filter_by(employee_id=user.id, report_date=target)
        .first()
    )
    now_utc = datetime.utcnow()
    if not report:
        report = DailyTaskReport(
            employee_id=user.id,
            report_date=target,
            tomorrow_plan=tomorrow_plan or None,
            blockers=blockers or None,
            submitted_at=now_utc,
            last_edited_at=now_utc,
        )
        db.add(report)
        db.flush()  # get report.id
    else:
        report.tomorrow_plan = tomorrow_plan or None
        report.blockers = blockers or None
        report.last_edited_at = now_utc
        # Clear existing items (we replace them)
        db.query(DailyTaskItem).filter_by(report_id=report.id).delete()
        db.flush()

    # Insert items
    for item_data in items:
        db.add(DailyTaskItem(
            report_id=report.id,
            sequence=item_data["sequence"],
            task_description=item_data["task_description"],
            status=item_data["status"],
            project=item_data["project"],
            remarks=item_data["remarks"],
        ))

    db.add(AuditLog(
        actor_code=user.employee_code,
        actor_email=user.email,
        action="task_report_saved",
        details={
            "report_id": report.id,
            "report_date": target.isoformat(),
            "n_tasks": len(items),
        },
    ))

    db.commit()
    db.refresh(report)

    pending_unlock = _has_pending_unlock(db, user.id, target)
    editable = _is_editable(target, has_active_unlock=approved_unlock)
    return {
        "success": True,
        "report": _report_to_dict(report, editable, pending_unlock),
    }


# ============================================================
# API — History
# ============================================================

@router.get("/api/history")
def get_history(
    limit: int = 30,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Return the current user's past task reports (most recent first)."""
    _require_task_report_permission(user)
    limit = max(1, min(limit, 90))
    reports = (
        db.query(DailyTaskReport)
        .filter_by(employee_id=user.id)
        .order_by(DailyTaskReport.report_date.desc())
        .limit(limit)
        .all()
    )
    out = []
    for r in reports:
        approved_unlock = _has_approved_unlock(db, user.id, r.report_date)
        pending_unlock = _has_pending_unlock(db, user.id, r.report_date)
        editable = _is_editable(r.report_date, has_active_unlock=approved_unlock)
        out.append({
            "id": r.id,
            "report_date": r.report_date.isoformat(),
            "n_tasks": len(r.items),
            "n_completed": sum(1 for it in r.items if it.status == "completed"),
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            "last_edited_at": r.last_edited_at.isoformat() if r.last_edited_at else None,
            "editable": editable,
            "pending_unlock": pending_unlock,
        })
    return out


# ============================================================
# API — Request unlock (locked reports)
# ============================================================

@router.post("/api/request-unlock")
async def request_unlock(
    request: Request,
    user: Employee = Depends(get_current_user_ready),
    db: Session = Depends(get_db),
):
    """Request an unlock for a locked report.

    Body: {"report_date": "YYYY-MM-DD", "reason": "..."}
    """
    _require_task_report_permission(user)
    body = await request.json()
    try:
        target = date.fromisoformat(body.get("report_date", ""))
    except ValueError:
        raise HTTPException(400, "Invalid report_date")
    reason = (body.get("reason") or "").strip()
    if len(reason) < 5:
        raise HTTPException(400, "Please give a reason (at least 5 characters).")

    # No duplicate pending requests
    existing = (
        db.query(UnlockRequest)
        .filter(
            UnlockRequest.employee_id == user.id,
            UnlockRequest.entry_date == target,
            UnlockRequest.kind == "task_report",
            UnlockRequest.status == "pending",
        )
        .first()
    )
    if existing:
        raise HTTPException(400, "You already have a pending unlock request for this date.")

    req = UnlockRequest(
        employee_id=user.id,
        entry_date=target,
        kind="task_report",
        reason=reason,
        status="pending",
    )
    db.add(req)
    db.add(AuditLog(
        actor_code=user.employee_code,
        actor_email=user.email,
        action="unlock_requested",
        details={"report_date": target.isoformat(), "reason": reason},
    ))
    db.commit()

    return {"success": True, "message": "Unlock request sent to admin."}
