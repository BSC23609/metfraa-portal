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
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_current_user
from ..models import DeptApprover, Employee, EmployeeApprover, OutpassRequest

router = APIRouter(prefix="/gatepass", tags=["gatepass"])
log = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/templates")

IST = timedelta(hours=5, minutes=30)

# How long past the declared in-time before the APPROVER and HR are escalated.
# The requester is nudged at their return time regardless (see run_overdue_check).
# Tunable without a deploy via the env var — drop to 10 at a sharp-return site,
# raise it where a short overrun is normal.
OVERDUE_GRACE_MIN = int(os.getenv("GATEPASS_OVERDUE_GRACE_MIN", "15"))
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
    """Who approves this person's passes.

    Order: their own assigned approver, then their department's head, then any
    superadmin. The fallbacks matter — a request that can't be routed is a
    request nobody can action, so we never dead-end.
    """
    # 1. per-employee (the primary mechanism)
    row = (db.query(EmployeeApprover)
           .filter(EmployeeApprover.employee_id == user.id).first())
    if row:
        emp_id = (row.leave_cover_emp_id if (on_leave and row.leave_cover_emp_id)
                  else row.approver_emp_id)
        if emp_id and emp_id != user.id:
            emp = db.query(Employee).filter(Employee.id == emp_id,
                                            Employee.is_active == True).first()  # noqa: E712
            if emp:
                return emp, ("Leave cover" if (on_leave and row.leave_cover_emp_id)
                             else "Approver")

    # 2. department fallback — covers a new joiner before anyone sets them up
    dept = (user.department or "").strip()
    if dept:
        d = (db.query(DeptApprover)
             .filter(DeptApprover.department.ilike(dept),
                     DeptApprover.active == True).first())  # noqa: E712
        if d:
            emp_id = (d.leave_cover_emp_id if (on_leave and d.leave_cover_emp_id)
                      else d.head_emp_id)
            if emp_id and emp_id != user.id:
                emp = db.query(Employee).filter(Employee.id == emp_id,
                                                Employee.is_active == True).first()  # noqa: E712
                if emp:
                    return emp, (d.department or dept)

    # 3. last resort — better a slightly wrong approver than a stuck request
    for e in db.query(Employee).filter(Employee.is_active == True).all():  # noqa: E712
        if e.id == user.id:
            continue
        if get_access(db, e).superadmin:
            return e, "Admin (no approver configured)"
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
        "returned_via": o.returned_via,
        "return_verified": bool(o.return_verified),
        "return_distance_m": o.return_distance_m,
        "alerted_requester": bool(o.requester_reminder_at),
        "alerted_approver": bool(o.overdue_alert_at),
        "alerted_hr": bool(o.hr_alert_at),
        "overdue_min": (max(0, int((datetime.utcnow() - o.expected_back_at).total_seconds() // 60))
                        if o.expected_back_at else None),
        "grace_min": OVERDUE_GRACE_MIN,
        "overdue": overdue and not _is_multi_day(o),
        "multi_day": _is_multi_day(o),
    }


def _is_admin(db: Session, user: Employee) -> bool:
    return bool(get_access(db, user).can_admin_gatepass)


# ------------------------------------------------------------------ pages

@router.get("/", response_class=HTMLResponse)
def page(request: Request, user: Employee = Depends(get_current_user),
         db: Session = Depends(get_db)):
    # If the tables aren't migrated yet the page must still render and SAY SO,
    # rather than returning an opaque 500 that gives nobody anything to act on.
    schema_ready, pending_for_me = True, 0
    try:
        pending_for_me = (db.query(OutpassRequest)
                          .filter(OutpassRequest.approver_id == user.id,
                                  OutpassRequest.status == "pending").count())
    except Exception:
        db.rollback()
        schema_ready = False
        log.error("[gatepass] schema not ready — run the migrations", exc_info=True)
    return templates.TemplateResponse(request, "gatepass.html", {
        "user": user, "is_admin": _is_admin(db, user),
        "pending_for_me": pending_for_me, "schema_ready": schema_ready,
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
        manager_on_leave=on_leave, status="pending",
        action_token=secrets.token_hex(20))
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



# --- shared approve/reject ------------------------------------------------
# Both the in-app buttons and the one-tap WhatsApp links call these, so the two
# paths can never drift apart — the BSC code has the same split for the same
# reason.

def apply_approve(db: Session, o: OutpassRequest, actor_id, actor_name: str) -> None:
    o.status = "approved"
    o.actioned_by_id = actor_id
    o.actioned_by_name = actor_name
    o.actioned_at_ist = _ist_str()
    o.action_token = None                       # single use
    o.pdf_token = secrets.token_hex(16)         # link to the printable pass
    if o.type == "gatepass":
        o.expected_back_at = _expected_back(o.req_date, o.in_time)
        o.return_token = secrets.token_hex(16)  # one-tap "I'm back"
    db.commit()
    from ..services import wati
    from ..services.portal_notify import notify_gatepass_decided
    for fn in (lambda: notify_gatepass_decided(o, db),
               lambda: wati.outpass_approved(o, db)):
        try:
            fn()
        except Exception:
            log.warning("[gatepass] approve notify failed on %s", o.ref_no, exc_info=True)


def apply_reject(db: Session, o: OutpassRequest, actor_id, actor_name: str,
                 reason: str | None) -> None:
    o.status = "rejected"
    o.actioned_by_id = actor_id
    o.actioned_by_name = actor_name
    o.actioned_at_ist = _ist_str()
    o.reject_reason = (reason or "")[:2000] or None
    o.action_token = None
    db.commit()
    from ..services import wati
    from ..services.portal_notify import notify_gatepass_decided
    for fn in (lambda: notify_gatepass_decided(o, db),
               lambda: wati.outpass_rejected(o, db)):
        try:
            fn()
        except Exception:
            log.warning("[gatepass] reject notify failed on %s", o.ref_no, exc_info=True)



# --- gate geofence ---------------------------------------------------------
# A return is "verified" only if the phone reports a position inside the gate
# radius. The radius is padded by the reading's own accuracy so an honest but
# fuzzy fix at the gate isn't rejected — but never by more than 100m of slop,
# or the geofence stops meaning anything.

# When True (the default) a return is REFUSED unless the phone reports a
# position inside the gate radius — the same rule BSC enforces. Set
# GATEPASS_REQUIRE_GPS=false to fall back to recording it as unverified.
def require_gps() -> bool:
    return (os.getenv("GATEPASS_REQUIRE_GPS", "true").strip().lower()
            not in ("false", "0", "no", "off"))


def gate_config() -> dict:
    def _f(name):
        v = os.getenv(name)
        try:
            return float(v) if v not in (None, "") else None
        except ValueError:
            return None
    return {"lat": _f("GATE_LAT"), "lng": _f("GATE_LNG"),
            "radius": _f("GATE_RADIUS_M") or 150.0}


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    from math import asin, cos, radians, sin, sqrt
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2)
    return 2 * 6371000 * asin(sqrt(a))


def check_geofence(lat, lng, accuracy) -> dict:
    """-> {verified, distance_m, reason}. Never raises; an unconfigured gate
    means we simply can't verify, not that the return is refused."""
    cfg = gate_config()
    if cfg["lat"] is None or cfg["lng"] is None:
        return {"verified": False, "distance_m": None,
                "reason": "gate location not configured"}
    if lat is None or lng is None:
        return {"verified": False, "distance_m": None,
                "reason": "no location provided"}
    dist = round(haversine_m(lat, lng, cfg["lat"], cfg["lng"]))
    allow = cfg["radius"] + min(float(accuracy or 0), 100.0)
    if dist > allow:
        return {"verified": False, "distance_m": dist,
                "reason": f"{dist} m from the gate"}
    return {"verified": True, "distance_m": dist, "reason": None}


def apply_return(db: Session, o: OutpassRequest, by_name: str, via: str = "self",
                 lat=None, lng=None, accuracy=None) -> dict:
    """Record the actual return. Shared by the in-app button, the one-tap link
    and admin, so the paths can't drift.

    The pass ALWAYS closes. Location only decides whether it closes *verified*.
    Refusing to close a pass because someone's GPS is off would recreate the
    exact problem this feature exists to solve — people not recording returns.
    """
    geo = check_geofence(lat, lng, accuracy)
    o.returned_at = datetime.utcnow()
    o.returned_by_name = by_name
    o.returned_via = via
    o.return_verified = bool(geo["verified"])
    o.return_lat = lat
    o.return_lng = lng
    o.return_accuracy_m = accuracy
    o.return_distance_m = geo["distance_m"]
    o.return_token = None          # single use
    db.commit()
    return geo


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
    apply_approve(db, o, user.id, user.name)
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
    apply_reject(db, o, user.id, user.name, reason)
    return {"ok": True, "status": "rejected"}


@router.post("/api/{rid}/return")
async def api_return(rid: int, request: Request,
                     user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Record the actual return.

    An employee closing their OWN pass is held to the same geofence as the
    WhatsApp link — otherwise the in-app button is a way straight round it.
    An admin closing someone else's pass is the deliberate override and is
    recorded as such.
    """
    o = db.query(OutpassRequest).filter(OutpassRequest.id == rid).first()
    if not o:
        raise HTTPException(status_code=404, detail="Request not found")
    is_own = o.requester_id == user.id
    if not is_own and not _is_admin(db, user):
        raise HTTPException(status_code=403, detail="Not your gatepass")
    if o.type != "gatepass":
        raise HTTPException(status_code=400, detail="Only a gatepass has a return")
    if o.status != "approved":
        raise HTTPException(status_code=400,
                            detail=f"Cannot record a return on a {o.status} request")
    if o.returned_at:
        raise HTTPException(status_code=409, detail="Return already recorded")

    body = {}
    try:
        body = await request.json() or {}
    except Exception:
        pass

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    lat, lng, acc = _num(body.get("lat")), _num(body.get("lng")), _num(body.get("accuracy"))

    if is_own and require_gps():
        geo = check_geofence(lat, lng, acc)
        if not geo["verified"]:
            if geo["distance_m"] is not None:
                detail = (f"You appear to be {geo['distance_m']} m from the gate. "
                          "Please try again once you're back at the gate.")
            elif geo["reason"] == "gate location not configured":
                detail = ("The gate location hasn't been set up yet, so your return "
                          "can't be confirmed. Please ask HR to record it.")
            else:
                detail = ("Your location couldn't be read. Please allow location "
                          "access and try again at the gate, or ask HR to record "
                          "your return.")
            raise HTTPException(status_code=422, detail=detail)

    via = ("gps" if (is_own and lat is not None) else "self" if is_own else "admin")
    geo = apply_return(db, o, user.name, via=via, lat=lat, lng=lng, accuracy=acc)
    return {"ok": True, "verified": geo["verified"], "distance_m": geo["distance_m"],
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

    Two different clocks:
      - The REQUESTER is reminded the moment they pass their own declared
        return time (expected_back_at), with no grace window — nudge them at
        the time they themselves said they'd be back, not a quarter-hour later.
      - The APPROVER and HR only escalate once the pass is genuinely overdue —
        past expected_back_at + OVERDUE_GRACE_MIN. Unchanged.
    So the query selects anything past its declared return time, and the grace
    gate lives inside the loop guarding only the approver/HR legs.

    Each recipient has its own stamp so a failing send for one doesn't block
    the others, and a stamp is only set when a channel actually DELIVERED —
    otherwise the next run retries. Setting the stamp on attempt is precisely
    how BSC lost every HR alert for weeks.
    """
    from ..services import wati
    from ..services.portal_notify import (notify_gatepass_overdue,
                                          notify_gatepass_return_reminder)
    now = datetime.utcnow()
    # Anything past its DECLARED return time — the grace gate moved into the
    # loop (see below) so the requester leg can fire before it.
    rows = (db.query(OutpassRequest)
            .filter(OutpassRequest.type == "gatepass",
                    OutpassRequest.status == "approved",
                    OutpassRequest.returned_at.is_(None),
                    OutpassRequest.expected_back_at.isnot(None),
                    OutpassRequest.expected_back_at < now).all())
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
        late = int((now - o.expected_back_at).total_seconds() // 60)
        multi = _is_multi_day(o)
        overdue = late >= OVERDUE_GRACE_MIN

        # Requester — reminded at their own declared return time, no grace.
        if not o.requester_reminder_at and o.requester:
            if _deliver(lambda: (notify_gatepass_return_reminder(o), True)[1],
                        lambda: wati.gatepass_return_reminder(o, late, db)):
                o.requester_reminder_at = now
                sent["requester"] += 1

        # Approver + HR — escalate only once genuinely overdue. A pass past its
        # return time but still inside the grace is reminder-only for now.
        if not overdue:
            db.commit()
            continue

        if multi:
            sent["multi_day_skipped"] += 1
            db.commit()
            continue

        if not o.overdue_alert_at and o.approver:
            ap = o.approver
            if _deliver(lambda: (notify_gatepass_overdue(o, ap.email, "approver"), True)[1],
                        lambda: wati.outpass_overdue(ap.name, ap.phone, o, late, db)):
                o.overdue_alert_at = now
                sent["approver"] += 1

        if not o.hr_alert_at:
            if _deliver(lambda: (notify_gatepass_overdue(o, None, "hr"), True)[1],
                        lambda: wati.outpass_overdue(hr_name, hr_phone, o, late, db)
                                 if hr_phone else False):
                o.hr_alert_at = now
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


# ------------------------------------------------- per-employee approvers

@router.get("/api/admin/employee-approvers")
def api_employee_approvers(user: Employee = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """Every active employee with their assigned approver, and what they'd fall
    back to if none is set — so an admin can see who is genuinely unconfigured."""
    if not _is_admin(db, user):
        raise HTTPException(status_code=403, detail="Admin only")
    # The overrides table is newer than the rest of the module. If it hasn't
    # been migrated yet, still list everyone — an empty roster looks like a
    # bug, whereas "nobody has an override" is the honest reading.
    schema_ready = True
    try:
        rows = {r.employee_id: r for r in db.query(EmployeeApprover).all()}
    except Exception:
        db.rollback()
        rows = {}
        schema_ready = False
        log.error("[gatepass] gatepass_employee_approvers missing — run the migrations",
                  exc_info=True)
    try:
        depts = {(d.department or "").lower(): d
                 for d in db.query(DeptApprover).all()}
    except Exception:
        db.rollback()
        depts = {}
    people = (db.query(Employee).filter(Employee.is_active == True)  # noqa: E712
              .order_by(Employee.name).all())
    by_id = {e.id: e for e in people}
    out = []
    for e in people:
        r = rows.get(e.id)
        d = depts.get((e.department or "").strip().lower())
        fallback = by_id.get(d.head_emp_id).name if (d and d.head_emp_id
                                                     and d.head_emp_id in by_id) else None
        out.append({
            "id": e.id, "name": e.name, "employee_code": e.employee_code,
            "department": e.department or "",
            "designation": e.designation or "",
            "approver_emp_id": r.approver_emp_id if r else None,
            "approver_name": (by_id.get(r.approver_emp_id).name
                              if r and r.approver_emp_id in by_id else None),
            "leave_cover_emp_id": r.leave_cover_emp_id if r else None,
            "leave_cover_name": (by_id.get(r.leave_cover_emp_id).name
                                 if r and r.leave_cover_emp_id in by_id else None),
            "fallback_name": fallback,
            "updated_by": r.updated_by if r else None,
        })
    return {"employees": out, "schema_ready": schema_ready,
            "choices": [{"id": e.id, "name": e.name,
                         "employee_code": e.employee_code,
                         "department": e.department or ""} for e in people]}


@router.post("/api/admin/employee-approvers")
async def api_set_employee_approver(request: Request,
                                    user: Employee = Depends(get_current_user),
                                    db: Session = Depends(get_db)):
    if not _is_admin(db, user):
        raise HTTPException(status_code=403, detail="Admin only")
    b = await request.json()
    try:
        emp_id = int(b.get("employee_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Valid employee_id required")
    target = db.query(Employee).filter(Employee.id == emp_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")

    def _emp(v):
        if v in (None, "", 0, "0"):
            return None
        try:
            eid = int(v)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid approver")
        if eid == emp_id:
            raise HTTPException(status_code=400,
                                detail="Someone can't approve their own pass")
        if not db.query(Employee).filter(Employee.id == eid,
                                         Employee.is_active == True).first():  # noqa: E712
            raise HTTPException(status_code=400, detail="Approver not found or inactive")
        return eid

    approver = _emp(b.get("approver_emp_id"))
    cover = _emp(b.get("leave_cover_emp_id"))

    row = (db.query(EmployeeApprover)
           .filter(EmployeeApprover.employee_id == emp_id).first())
    if approver is None and cover is None:
        # Clearing both removes the override and restores the department fallback.
        if row:
            db.delete(row)
            db.commit()
        return {"ok": True, "cleared": True}
    if not row:
        row = EmployeeApprover(employee_id=emp_id)
        db.add(row)
    row.approver_emp_id = approver
    row.leave_cover_emp_id = cover
    row.updated_by = user.employee_code
    db.commit()
    return {"ok": True}


def _send_alerts_for(db: Session, o: OutpassRequest, force: bool) -> dict:
    """Send the overdue alerts for one pass.

    force=True ignores the grace period AND the per-recipient stamps, so an
    admin can push the alerts out immediately — for a genuinely urgent pass,
    or to prove the WhatsApp path works without waiting for the cron.
    """
    from ..services import wati
    from ..services.portal_notify import (notify_gatepass_overdue,
                                          notify_gatepass_return_reminder)
    late = 0
    if o.expected_back_at:
        late = max(0, int((datetime.utcnow() - o.expected_back_at).total_seconds() // 60))
    hr_name = os.getenv("GATEPASS_HR_NAME", "HR")
    hr_phone = os.getenv("GATEPASS_HR_PHONE", "")
    out = {"requester": False, "approver": False, "hr": False, "errors": []}

    def _try(label, email_fn, wa_fn):
        ok = False
        for fn in (email_fn, wa_fn):
            try:
                ok = bool(fn()) or ok
            except Exception as e:
                out["errors"].append(f"{label}: {e}")
                log.warning("[gatepass] manual alert %s failed on %s", label,
                            o.ref_no, exc_info=True)
        out[label] = ok
        return ok

    if o.requester and (force or not o.requester_reminder_at):
        if _try("requester",
                lambda: (notify_gatepass_return_reminder(o), True)[1],
                lambda: wati.gatepass_return_reminder(o, late, db)):
            o.requester_reminder_at = datetime.utcnow()
    if o.approver and (force or not o.overdue_alert_at):
        ap = o.approver
        if _try("approver",
                lambda: (notify_gatepass_overdue(o, ap.email, "approver"), True)[1],
                lambda: wati.outpass_overdue(ap.name, ap.phone, o, late, db)):
            o.overdue_alert_at = datetime.utcnow()
    if force or not o.hr_alert_at:
        if _try("hr",
                lambda: (notify_gatepass_overdue(o, None, "hr"), True)[1],
                lambda: (wati.outpass_overdue(hr_name, hr_phone, o, late, db)
                         if hr_phone else False)):
            o.hr_alert_at = datetime.utcnow()
    db.commit()
    out["overdue_min"] = late
    return out


@router.post("/api/admin/{rid}/send-alerts")
def api_send_alerts(rid: int, user: Employee = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Push the overdue alerts for one pass right now."""
    if not _is_admin(db, user):
        raise HTTPException(status_code=403, detail="Admin only")
    o = db.query(OutpassRequest).filter(OutpassRequest.id == rid).first()
    if not o:
        raise HTTPException(status_code=404, detail="Pass not found")
    if o.type != "gatepass":
        raise HTTPException(status_code=400, detail="Only a gatepass has a return to chase")
    if o.returned_at:
        raise HTTPException(status_code=400, detail="This pass has already been returned")
    if o.status != "approved":
        raise HTTPException(status_code=400, detail=f"This pass is {o.status}")
    res = _send_alerts_for(db, o, force=True)
    sent = [k for k in ("requester", "approver", "hr") if res[k]]
    return {"ok": True, "sent": sent, "overdue_min": res["overdue_min"],
            "errors": res["errors"][:3],
            "message": ("Alerts sent to " + ", ".join(sent)) if sent
                       else "Nothing could be sent — check the delivery log below."}


@router.post("/api/admin/run-overdue")
def api_run_overdue(user: Employee = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Run the scheduled sweep immediately — useful to confirm the job works
    without waiting up to 15 minutes for GitHub Actions."""
    if not _is_admin(db, user):
        raise HTTPException(status_code=403, detail="Admin only")
    return {"ok": True, **run_overdue_check(db)}
