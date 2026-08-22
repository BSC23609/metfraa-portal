"""Outpass / Gatepass — ported from the BSC Tickets Portal for Metfraa.

    Outpass  — leaving for the day, no return expected.
    Gatepass — out and back; declares an in-time, so it can go overdue.

Flow: employee raises a request -> routed to their department's approver
(or its leave cover) -> approved or sent back -> for a gatepass, the employee
records their return -> if they don't, a cron nudges approver, HR and
requester on independent stamps.

Two deliberate differences from BSC: notifications go by EMAIL through the
portal's SMTP rather than WATI WhatsApp, and there is no PDF/OneDrive step
(BSC needs a printable pass at a manned gate; that can be added later).
"""
import logging
import os
import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_current_user
from ..models import DeptApprover, Employee, OutpassRequest

router = APIRouter(prefix="/gatepass", tags=["gatepass"])
log = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/templates")

IST = timedelta(hours=5, minutes=30)

# A gatepass this far past its declared in-time counts as overdue.
OVERDUE_GRACE_MIN = 30
# Passes longer than this are treated as multi-day (site trips, logistics) and
# excluded from HR alerts — BSC added this after logistics staff were flagged
# every night for legitimately long trips.
MULTI_DAY_HOURS = 16


def _now_ist() -> datetime:
    return datetime.utcnow() + IST


def _ist_str(dt: datetime | None = None) -> str:
    return (dt or _now_ist()).strftime("%Y-%m-%d %H:%M:%S")


def _next_ref(db: Session) -> str:
    """OGP/MET/YYMMDD/NNNN — mirrors BSC's scheme with a MET segment.

    Uses MAX(suffix) rather than COUNT so deleting a pass never causes a
    number to be reused.
    """
    d = _now_ist().strftime("%y%m%d")
    prefix = f"OGP/MET/{d}/"
    rows = (db.query(OutpassRequest.ref_no)
            .filter(OutpassRequest.ref_no.like(f"{prefix}%")).all())
    mx = 0
    for (r,) in rows:
        try:
            mx = max(mx, int(r.rsplit("/", 1)[1]))
        except (ValueError, IndexError):
            continue
    return f"{prefix}{mx + 1:04d}"


def _resolve_approver(db: Session, user: Employee, on_leave: bool):
    """Department head, or the leave cover when the requester flags it.

    Falls back to any expense/superadmin so a request never dead-ends because
    a department has no head configured yet.
    """
    dept = (user.department or "").strip()
    row = None
    if dept:
        row = (db.query(DeptApprover)
               .filter(DeptApprover.department.ilike(dept),
                       DeptApprover.active == True).first())  # noqa: E712
    if row:
        emp_id = row.leave_cover_emp_id if (on_leave and row.leave_cover_emp_id) else row.head_emp_id
        if emp_id and emp_id != user.id:
            emp = db.query(Employee).filter(Employee.id == emp_id,
                                            Employee.is_active == True).first()  # noqa: E712
            if emp:
                return emp, (row.department or dept)
    # Fallback: a superadmin. Better a slightly wrong approver than a stuck request.
    for e in db.query(Employee).filter(Employee.is_active == True).all():  # noqa: E712
        if e.id == user.id:
            continue
        if get_access(db, e).superadmin:
            return e, "Admin (no department head configured)"
    return None, None


def _valid_time(v: str | None) -> bool:
    """HH:MM with a real clock value. A bare regex accepts 25:99, which then
    silently produces no expected_back_at and a gatepass that can never go
    overdue — so the range check matters, not just the shape."""
    if not v or not re.match(r"^\d{1,2}:\d{2}$", v.strip()):
        return False
    hh, mm = (int(x) for x in v.strip().split(":"))
    return 0 <= hh <= 23 and 0 <= mm <= 59


def _expected_back(req_date, in_time: str | None) -> datetime | None:
    """Resolve a gatepass's declared in-time into a real UTC instant."""
    if not _valid_time(in_time):
        return None
    hh, mm = (int(x) for x in in_time.strip().split(":"))
    d = req_date if isinstance(req_date, date) else _now_ist().date()
    return datetime(d.year, d.month, d.day, hh, mm) - IST   # IST wall clock -> UTC


def _pass_span(o: OutpassRequest) -> timedelta | None:
    """How long the pass is declared for, from out-time to in-time.

    Derived from BOTH stored strings rather than mixing the stored
    expected_back_at with a recomputed out-time — those can diverge (an admin
    edit, a legacy row) and then the span is meaningless. If in-time is
    earlier than out-time the pass runs past midnight, so add a day.
    """
    if not o.out_time or not o.in_time:
        return None
    out = _expected_back(o.req_date, o.out_time)
    back = _expected_back(o.req_date, o.in_time)
    if not out or not back:
        return None
    if back <= out:
        back += timedelta(days=1)
    return back - out


def _is_multi_day(o: OutpassRequest) -> bool:
    """Long site/logistics trips shouldn't pester HR every evening — BSC added
    this after logistics staff were flagged nightly for legitimate trips."""
    span = _pass_span(o)
    return bool(span and span >= timedelta(hours=MULTI_DAY_HOURS))


def _row(o: OutpassRequest, db: Session) -> dict:
    overdue = bool(
        o.type == "gatepass" and o.status == "approved" and not o.returned_at
        and o.expected_back_at
        and datetime.utcnow() > o.expected_back_at + timedelta(minutes=OVERDUE_GRACE_MIN))
    return {
        "id": o.id, "ref_no": o.ref_no, "type": o.type, "on_duty": bool(o.on_duty),
        "req_date": o.req_date.isoformat() if o.req_date else None,
        "purpose": o.purpose, "out_time": o.out_time, "in_time": o.in_time,
        "status": o.status,
        "requester_name": o.requester.name if o.requester else "",
        "requester_code": o.requester.employee_code if o.requester else "",
        "department": o.requester.department if o.requester else "",
        "approver_name": o.approver.name if o.approver else "",
        "approver_label": o.approver_label,
        "manager_on_leave": bool(o.manager_on_leave),
        "actioned_by_name": o.actioned_by_name,
        "actioned_at": o.actioned_at_ist,
        "reject_reason": o.reject_reason,
        "expected_back_at": (o.expected_back_at + IST).strftime("%Y-%m-%d %H:%M")
                            if o.expected_back_at else None,
        "returned_at": (o.returned_at + IST).strftime("%Y-%m-%d %H:%M")
                       if o.returned_at else None,
        "returned_by_name": o.returned_by_name,
        "overdue": overdue and not _is_multi_day(o),
        "multi_day": _is_multi_day(o),
    }


def _is_admin(db: Session, user: Employee) -> bool:
    a = get_access(db, user)
    return bool(a.superadmin or a.hr_admin)


# ------------------------------------------------------------------ pages

@router.get("/", response_class=HTMLResponse)
def page(request: Request, user: Employee = Depends(get_current_user),
         db: Session = Depends(get_db)):
    pending_for_me = (db.query(OutpassRequest)
                      .filter(OutpassRequest.approver_id == user.id,
                              OutpassRequest.status == "pending").count())
    return templates.TemplateResponse(request, "gatepass.html", {
        "user": user, "is_admin": _is_admin(db, user),
        "pending_for_me": pending_for_me,
    })


# ------------------------------------------------------------------- APIs

@router.get("/api/mine")
def api_mine(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(OutpassRequest)
            .filter(OutpassRequest.requester_id == user.id)
            .order_by(OutpassRequest.id.desc()).limit(100).all())
    approver, label = _resolve_approver(db, user, False)
    return {"requests": [_row(o, db) for o in rows],
            "my_approver": approver.name if approver else None,
            "my_approver_label": label}


@router.post("/api/request")
async def api_request(request: Request, user: Employee = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    b = await request.json()
    typ = (b.get("type") or "").strip()
    if typ not in ("outpass", "gatepass"):
        raise HTTPException(status_code=400, detail="Choose Outpass or Gatepass")
    purpose = (b.get("purpose") or "").strip()
    if not purpose:
        raise HTTPException(status_code=400, detail="Purpose is required")
    if len(purpose) > 2000:
        raise HTTPException(status_code=400, detail="Purpose is too long")
    out_time = (b.get("out_time") or "").strip()
    if not _valid_time(out_time):
        raise HTTPException(status_code=400, detail="Out-time is required (HH:MM)")
    in_time = (b.get("in_time") or "").strip()
    if typ == "gatepass" and not _valid_time(in_time):
        raise HTTPException(status_code=400, detail="In-time is required for a gatepass (HH:MM)")

    raw_date = (b.get("req_date") or "").strip()
    try:
        req_date = (datetime.strptime(raw_date, "%Y-%m-%d").date() if raw_date
                    else _now_ist().date())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")

    on_leave = bool(b.get("manager_on_leave"))
    approver, label = _resolve_approver(db, user, on_leave)
    if not approver:
        raise HTTPException(status_code=400,
                            detail="No approver is configured for your department. "
                                   "Please contact HR.")

    o = OutpassRequest(
        ref_no=_next_ref(db), type=typ, on_duty=bool(b.get("on_duty")),
        req_date=req_date, requester_id=user.id, purpose=purpose,
        out_time=out_time, in_time=in_time if typ == "gatepass" else None,
        approver_id=approver.id, approver_label=label,
        manager_on_leave=on_leave, status="pending")
    db.add(o)
    db.commit()

    # Notify on both channels. WhatsApp is what people actually read; email is
    # the durable record. Neither failing may lose the request.
    from ..services import wati
    from ..services.portal_notify import notify_gatepass_requested
    for fn in (lambda: notify_gatepass_requested(approver, o, user),
               lambda: wati.outpass_request(approver, o, db)):
        try:
            fn()
        except Exception:
            log.warning("[gatepass] notify failed on %s", o.ref_no, exc_info=True)
    return {"ok": True, "ref_no": o.ref_no, "approver": approver.name,
            "whatsapp": wati.configured()}


@router.get("/api/approvals")
def api_approvals(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(OutpassRequest)
    if _is_admin(db, user):
        q = q.filter(or_(OutpassRequest.status == "pending",
                         OutpassRequest.approver_id == user.id))
    else:
        q = q.filter(OutpassRequest.approver_id == user.id)
    rows = q.order_by(OutpassRequest.id.desc()).limit(200).all()
    return {"requests": [_row(o, db) for o in rows],
            "pending": sum(1 for o in rows if o.status == "pending")}


def _load_for_action(db: Session, user: Employee, rid: int) -> OutpassRequest:
    o = db.query(OutpassRequest).filter(OutpassRequest.id == rid).first()
    if not o:
        raise HTTPException(status_code=404, detail="Request not found")
    if o.approver_id != user.id and not _is_admin(db, user):
        raise HTTPException(status_code=403, detail="This request isn't routed to you")
    if o.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already {o.status}")
    return o


@router.post("/api/{rid}/approve")
def api_approve(rid: int, user: Employee = Depends(get_current_user),
                db: Session = Depends(get_db)):
    o = _load_for_action(db, user, rid)
    o.status = "approved"
    o.actioned_by_id = user.id
    o.actioned_by_name = user.name
    o.actioned_at_ist = _ist_str()
    if o.type == "gatepass":
        o.expected_back_at = _expected_back(o.req_date, o.in_time)
    db.commit()
    from ..services import wati
    from ..services.portal_notify import notify_gatepass_decided
    for fn in (lambda: notify_gatepass_decided(o, db),
               lambda: wati.outpass_approved(o, db)):
        try:
            fn()
        except Exception:
            log.warning("[gatepass] notify failed on %s", o.ref_no, exc_info=True)
    return {"ok": True, "status": "approved"}


@router.post("/api/{rid}/reject")
async def api_reject(rid: int, request: Request,
                     user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    o = _load_for_action(db, user, rid)
    reason = ((await request.json()).get("reason") or "").strip()
    if len(reason) < 3:
        raise HTTPException(status_code=400,
                            detail="Please give a reason so the employee knows why")
    o.status = "rejected"
    o.actioned_by_id = user.id
    o.actioned_by_name = user.name
    o.actioned_at_ist = _ist_str()
    o.reject_reason = reason[:2000]
    db.commit()
    from ..services import wati
    from ..services.portal_notify import notify_gatepass_decided
    for fn in (lambda: notify_gatepass_decided(o, db),
               lambda: wati.outpass_rejected(o, db)):
        try:
            fn()
        except Exception:
            log.warning("[gatepass] notify failed on %s", o.ref_no, exc_info=True)
    return {"ok": True, "status": "rejected"}


@router.post("/api/{rid}/return")
def api_return(rid: int, user: Employee = Depends(get_current_user),
               db: Session = Depends(get_db)):
    """Record the actual return. The requester or an admin may do this."""
    o = db.query(OutpassRequest).filter(OutpassRequest.id == rid).first()
    if not o:
        raise HTTPException(status_code=404, detail="Request not found")
    if o.requester_id != user.id and not _is_admin(db, user):
        raise HTTPException(status_code=403, detail="Not your gatepass")
    if o.type != "gatepass":
        raise HTTPException(status_code=400, detail="Only a gatepass has a return")
    if o.status != "approved":
        raise HTTPException(status_code=400,
                            detail=f"Cannot record a return on a {o.status} request")
    if o.returned_at:
        raise HTTPException(status_code=409, detail="Return already recorded")
    o.returned_at = datetime.utcnow()
    o.returned_by_name = user.name
    db.commit()
    return {"ok": True,
            "returned_at": (o.returned_at + IST).strftime("%Y-%m-%d %H:%M")}


# --------------------------------------------------------------- admin API

@router.get("/api/admin/all")
def api_admin_all(user: Employee = Depends(get_current_user),
                  db: Session = Depends(get_db), status: str | None = None):
    if not _is_admin(db, user):
        raise HTTPException(status_code=403, detail="Admin only")
    q = db.query(OutpassRequest)
    if status == "open":
        q = q.filter(OutpassRequest.type == "gatepass",
                     OutpassRequest.status == "approved",
                     OutpassRequest.returned_at.is_(None))
    elif status:
        q = q.filter(OutpassRequest.status == status)
    rows = q.order_by(OutpassRequest.id.desc()).limit(500).all()
    return {"requests": [_row(o, db) for o in rows]}


@router.get("/api/admin/approvers")
def api_admin_approvers(user: Employee = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    if not _is_admin(db, user):
        raise HTTPException(status_code=403, detail="Admin only")
    depts = sorted({(e.department or "").strip()
                    for e in db.query(Employee).filter(Employee.is_active == True).all()  # noqa: E712
                    if (e.department or "").strip()})
    rows = {r.department.lower(): r for r in db.query(DeptApprover).all()}
    out = []
    for d in depts:
        r = rows.get(d.lower())
        out.append({
            "department": d,
            "head_emp_id": r.head_emp_id if r else None,
            "head_name": r.head.name if r and r.head else None,
            "leave_cover_emp_id": r.leave_cover_emp_id if r else None,
            "leave_cover_name": r.leave_cover.name if r and r.leave_cover else None,
            "active": bool(r.active) if r else False,
        })
    people = [{"id": e.id, "name": e.name, "employee_code": e.employee_code,
               "department": e.department}
              for e in db.query(Employee).filter(Employee.is_active == True)  # noqa: E712
              .order_by(Employee.name).all()]
    return {"departments": out, "employees": people}


@router.post("/api/admin/approvers")
async def api_set_approver(request: Request, user: Employee = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    if not _is_admin(db, user):
        raise HTTPException(status_code=403, detail="Admin only")
    b = await request.json()
    dept = (b.get("department") or "").strip()
    if not dept:
        raise HTTPException(status_code=400, detail="Department is required")

    def _emp(v):
        if v in (None, "", 0):
            return None
        try:
            eid = int(v)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid employee")
        if not db.query(Employee).filter(Employee.id == eid).first():
            raise HTTPException(status_code=400, detail="Employee not found")
        return eid

    head = _emp(b.get("head_emp_id"))
    cover = _emp(b.get("leave_cover_emp_id"))
    row = (db.query(DeptApprover)
           .filter(DeptApprover.department.ilike(dept)).first())
    if not row:
        row = DeptApprover(department=dept)
        db.add(row)
    row.head_emp_id = head
    row.leave_cover_emp_id = cover
    row.active = bool(b.get("active", True))
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------ overdue watch

def run_overdue_check(db: Session) -> dict:
    """Nudge approver, HR and requester about gatepasses that never came back.

    Each recipient has its own stamp so a failing send for one doesn't block
    the others, and a stamp is only set when a channel actually DELIVERED —
    otherwise the next run retries. Setting the stamp on attempt is precisely
    how BSC lost every HR alert for weeks.
    """
    from ..services import wati
    from ..services.portal_notify import (notify_gatepass_overdue,
                                          notify_gatepass_return_reminder)
    cutoff = datetime.utcnow() - timedelta(minutes=OVERDUE_GRACE_MIN)
    rows = (db.query(OutpassRequest)
            .filter(OutpassRequest.type == "gatepass",
                    OutpassRequest.status == "approved",
                    OutpassRequest.returned_at.is_(None),
                    OutpassRequest.expected_back_at.isnot(None),
                    OutpassRequest.expected_back_at < cutoff).all())
    sent = {"approver": 0, "hr": 0, "requester": 0, "checked": len(rows),
            "multi_day_skipped": 0, "whatsapp": wati.configured()}

    def _deliver(email_fn, wa_fn) -> bool:
        """True if EITHER channel got through."""
        ok = False
        for fn in (email_fn, wa_fn):
            try:
                ok = bool(fn()) or ok
            except Exception:
                log.warning("[gatepass] overdue notify failed", exc_info=True)
        return ok

    hr_name = os.getenv("GATEPASS_HR_NAME", "HR")
    hr_phone = os.getenv("GATEPASS_HR_PHONE", "")

    for o in rows:
        late = int((datetime.utcnow() - o.expected_back_at).total_seconds() // 60)
        multi = _is_multi_day(o)

        if not o.requester_reminder_at and o.requester:
            if _deliver(lambda: (notify_gatepass_return_reminder(o), True)[1],
                        lambda: wati.gatepass_return_reminder(o, late, db)):
                o.requester_reminder_at = datetime.utcnow()
                sent["requester"] += 1

        if multi:
            sent["multi_day_skipped"] += 1
            db.commit()
            continue

        if not o.overdue_alert_at and o.approver:
            ap = o.approver
            if _deliver(lambda: (notify_gatepass_overdue(o, ap.email, "approver"), True)[1],
                        lambda: wati.outpass_overdue(ap.name, ap.phone, o, late, db)):
                o.overdue_alert_at = datetime.utcnow()
                sent["approver"] += 1

        if not o.hr_alert_at:
            if _deliver(lambda: (notify_gatepass_overdue(o, None, "hr"), True)[1],
                        lambda: wati.outpass_overdue(hr_name, hr_phone, o, late, db)
                                 if hr_phone else False):
                o.hr_alert_at = datetime.utcnow()
                sent["hr"] += 1
        db.commit()
    db.commit()
    return sent


@router.get("/api/admin/wa-log")
def api_wa_log(user: Employee = Depends(get_current_user), db: Session = Depends(get_db),
               limit: int = 100):
    """Recent WhatsApp send attempts.

    Exists because BSC spent weeks believing alerts were going out. If HR says
    they got nothing, look here first — 'declined' or 'no_phone' rows tell you
    immediately whether it was WATI, the template, or a missing number.
    """
    if not _is_admin(db, user):
        raise HTTPException(status_code=403, detail="Admin only")
    from ..models import WaLog
    from ..services import wati as _w
    rows = (db.query(WaLog).order_by(WaLog.id.desc()).limit(min(limit, 500)).all())
    counts = {}
    for r in rows:
        counts[r.result] = counts.get(r.result, 0) + 1
    return {
        "configured": _w.configured(),
        "hr_phone_set": bool(os.getenv("GATEPASS_HR_PHONE")),
        "counts": counts,
        "rows": [{"id": r.id, "phone": r.phone, "template": r.template,
                  "result": r.result, "detail": r.detail,
                  "at": (r.created_at + IST).strftime("%Y-%m-%d %H:%M")
                        if r.created_at else None} for r in rows],
    }
