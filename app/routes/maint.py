"""Maintenance (CMMS) module — asset master, events, readings, PM.

First screen: the asset master (the machines seeded from the equipment list).
Breakdown/PM logging, readings, PM scheduling, reports and dashboard follow in
later slices. Access is gated by the maint_admin flag (superadmin implies it).
"""
import calendar
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_current_user
from ..services import onedrive as _od
from ..models import (Employee, MaintAsset, MaintEvent, MaintMachineType,
                      MaintHoliday, MaintPMPlan, MaintReading, PlantLabour)

router = APIRouter(prefix="/maint", tags=["maint"])
log = logging.getLogger("maint")
templates = Jinja2Templates(directory="app/templates")


def _guard(db: Session, user: Employee):
    if not get_access(db, user).can_admin_maint:
        raise HTTPException(status_code=403, detail="Maintenance access only")


def _iso(d):
    return d.isoformat() if d else None


def _pdate(s):
    return date.fromisoformat(s) if s else None


def _asset_json(a: MaintAsset):
    return {
        "id": a.id, "asset_code": a.asset_code, "description": a.description,
        "category": a.category, "type_id": a.type_id,
        "type_name": a.machine_type.name if a.machine_type else None,
        "type_key": a.machine_type.key if a.machine_type else None,
        "serial_model_no": a.serial_model_no, "manufacturer": a.manufacturer,
        "location": a.location, "acquisition_date": _iso(a.acquisition_date),
        "acquisition_value": a.acquisition_value, "capacity": a.capacity,
        "capacity_unit": a.capacity_unit, "mfg_year": a.mfg_year,
        "supplier": a.supplier, "warranty_until": _iso(a.warranty_until),
        "date_installed": _iso(a.date_installed), "active": a.active,
    }


class AssetIn(BaseModel):
    asset_code: str
    description: str
    category: str | None = None
    type_id: int | None = None
    serial_model_no: str | None = None
    manufacturer: str | None = None
    location: str | None = None
    acquisition_date: str | None = None
    acquisition_value: float | None = None
    capacity: float | None = None
    capacity_unit: str | None = None
    mfg_year: int | None = None
    supplier: str | None = None
    warranty_until: str | None = None
    date_installed: str | None = None
    active: bool = True


def _apply(a: MaintAsset, p: AssetIn):
    a.description = (p.description or "").strip()
    a.category = p.category
    a.type_id = p.type_id
    a.serial_model_no = p.serial_model_no
    a.manufacturer = p.manufacturer
    a.location = p.location
    a.acquisition_date = _pdate(p.acquisition_date)
    a.acquisition_value = p.acquisition_value
    a.capacity = p.capacity
    a.capacity_unit = p.capacity_unit
    a.mfg_year = p.mfg_year
    a.supplier = p.supplier
    a.warranty_until = _pdate(p.warranty_until)
    a.date_installed = _pdate(p.date_installed)
    a.active = p.active


# ------------------------------------------------------------------ page

@router.get("/", response_class=HTMLResponse)
def page(request: Request, user: Employee = Depends(get_current_user),
         db: Session = Depends(get_db)):
    _guard(db, user)
    return templates.TemplateResponse(request, "maint.html", {"user": user})


# ------------------------------------------------------------------ meta

@router.get("/api/meta")
def api_meta(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _guard(db, user)
    types = [{"id": t.id, "key": t.key, "name": t.name,
              "reading_params": t.reading_params, "meter_param": t.meter_param}
             for t in db.query(MaintMachineType).order_by(MaintMachineType.name).all()]
    locations = sorted(r[0] for r in db.query(MaintAsset.location)
                       .filter(MaintAsset.location.isnot(None)).distinct().all() if r[0])
    team = [{"id": p.id, "name": p.name} for p in
            db.query(PlantLabour).filter(PlantLabour.active.is_(True))
            .order_by(PlantLabour.name).all()]
    return {"types": types, "locations": locations, "team": team}


# ------------------------------------------------------------------ assets

@router.get("/api/assets")
def api_assets(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _guard(db, user)
    rows = db.query(MaintAsset).order_by(MaintAsset.asset_code).all()
    return [_asset_json(a) for a in rows]


@router.post("/api/assets")
def api_create_asset(payload: AssetIn, user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _guard(db, user)
    code = (payload.asset_code or "").strip()
    if not code:
        raise HTTPException(400, "Asset code is required")
    if db.query(MaintAsset).filter_by(asset_code=code).first():
        raise HTTPException(400, f"Asset code {code} already exists")
    a = MaintAsset(asset_code=code)
    _apply(a, payload)
    db.add(a); db.commit(); db.refresh(a)
    return _asset_json(a)


@router.put("/api/assets/{asset_id}")
def api_update_asset(asset_id: int, payload: AssetIn,
                     user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _guard(db, user)
    a = db.get(MaintAsset, asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    new_code = (payload.asset_code or "").strip()
    if not new_code:
        raise HTTPException(400, "Asset code is required")
    if new_code != a.asset_code and db.query(MaintAsset).filter_by(asset_code=new_code).first():
        raise HTTPException(400, f"Asset code {new_code} already exists")
    a.asset_code = new_code
    _apply(a, payload)
    db.commit(); db.refresh(a)
    return _asset_json(a)


@router.post("/api/assets/{asset_id}/toggle")
def api_toggle_asset(asset_id: int, user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _guard(db, user)
    a = db.get(MaintAsset, asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    a.active = not a.active
    db.commit()
    return {"id": a.id, "active": a.active}


# ------------------------------------------------------------------ events

VALID_CATEGORIES = {"Breakdown", "Scheduled PM", "Unscheduled PM"}


def _pdt(s):
    if not s:
        return None
    s = s.replace("T", " ").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _event_json(e: MaintEvent):
    return {
        "id": e.id, "asset_id": e.asset_id,
        "asset_code": e.asset.asset_code if e.asset else None,
        "asset_description": e.asset.description if e.asset else None,
        "event_date": _iso(e.event_date), "category": e.category, "status": e.status,
        "reported_at": e.reported_at.isoformat(timespec="minutes") if e.reported_at else None,
        "restored_at": e.restored_at.isoformat(timespec="minutes") if e.restored_at else None,
        "downtime_hrs": e.downtime_hrs, "complaint": e.complaint, "cause": e.cause,
        "action": e.action, "parts": e.parts, "cost": e.cost,
        "meter_at_event": e.meter_at_event,
        "attended_by_id": e.attended_by_id, "verified_by_id": e.verified_by_id,
        "attended_by_name": e.attended_by.name if e.attended_by else None,
        "verified_by_name": e.verified_by.name if e.verified_by else None,
        "remarks": e.remarks,
    }


class EventIn(BaseModel):
    asset_id: int
    event_date: str
    category: str
    status: str | None = None
    reported_at: str | None = None
    restored_at: str | None = None
    complaint: str | None = None
    cause: str | None = None
    action: str | None = None
    parts: str | None = None
    cost: float | None = None
    meter_at_event: float | None = None
    attended_by_id: int | None = None
    verified_by_id: int | None = None
    remarks: str | None = None


def _apply_event(e: MaintEvent, p: EventIn):
    e.asset_id = p.asset_id
    e.event_date = _pdate(p.event_date)
    e.category = p.category
    if p.category == "Breakdown":
        e.status = p.status or "Open"
        e.reported_at = _pdt(p.reported_at)
        e.restored_at = _pdt(p.restored_at)
        if e.reported_at and e.restored_at:
            e.downtime_hrs = round((e.restored_at - e.reported_at).total_seconds() / 3600, 2)
        else:
            e.downtime_hrs = None
    else:
        e.status = None
        e.reported_at = None
        e.restored_at = None
        e.downtime_hrs = None
    e.complaint = p.complaint
    e.cause = p.cause
    e.action = p.action
    e.parts = p.parts
    e.cost = p.cost
    e.meter_at_event = p.meter_at_event
    e.attended_by_id = p.attended_by_id
    e.verified_by_id = p.verified_by_id
    e.remarks = p.remarks


@router.get("/api/events")
def api_events(asset_id: int | None = None, category: str | None = None,
               status: str | None = None, limit: int = 300,
               user: Employee = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _guard(db, user)
    qy = db.query(MaintEvent)
    if asset_id:
        qy = qy.filter(MaintEvent.asset_id == asset_id)
    if category:
        qy = qy.filter(MaintEvent.category == category)
    if status:
        qy = qy.filter(MaintEvent.status == status)
    rows = qy.order_by(MaintEvent.event_date.desc(), MaintEvent.id.desc()).limit(limit).all()
    return [_event_json(e) for e in rows]


@router.post("/api/events")
def api_create_event(payload: EventIn, user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _guard(db, user)
    if payload.category not in VALID_CATEGORIES:
        raise HTTPException(400, "Invalid category")
    if not db.get(MaintAsset, payload.asset_id):
        raise HTTPException(400, "Unknown asset")
    if not _pdate(payload.event_date):
        raise HTTPException(400, "Event date is required (YYYY-MM-DD)")
    e = MaintEvent(asset_id=payload.asset_id)
    _apply_event(e, payload)
    db.add(e); db.commit(); db.refresh(e)
    return _event_json(e)


@router.put("/api/events/{event_id}")
def api_update_event(event_id: int, payload: EventIn,
                     user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _guard(db, user)
    e = db.get(MaintEvent, event_id)
    if not e:
        raise HTTPException(404, "Event not found")
    if payload.category not in VALID_CATEGORIES:
        raise HTTPException(400, "Invalid category")
    if not _pdate(payload.event_date):
        raise HTTPException(400, "Event date is required (YYYY-MM-DD)")
    _apply_event(e, payload)
    db.commit(); db.refresh(e)
    return _event_json(e)


# ------------------------------------------------------------------ readings

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _reading_json(r: MaintReading):
    return {
        "id": r.id, "asset_id": r.asset_id,
        "asset_code": r.asset.asset_code if r.asset else None,
        "reading_date": _iso(r.reading_date), "start_time": r.start_time,
        "end_time": r.end_time, "values": r.values or {},
        "meter_value": r.meter_value, "diff": r.diff,
        "remarks": r.remarks, "entered_by": r.entered_by,
    }


class ReadingIn(BaseModel):
    asset_id: int
    reading_date: str
    start_time: str | None = None
    end_time: str | None = None
    values: dict = {}
    remarks: str | None = None


def _asset_meter_param(db: Session, asset_id: int):
    a = db.get(MaintAsset, asset_id)
    return a.machine_type.meter_param if (a and a.machine_type) else None


def _recompute_readings(db: Session, asset_id: int, meter_param):
    """Recompute meter_value + diff for every reading of an asset, in true
    chronological order (date, then time, then entry order). DB-agnostic."""
    rows = db.query(MaintReading).filter(MaintReading.asset_id == asset_id).all()
    rows.sort(key=lambda r: (r.reading_date, r.start_time or "", r.id))
    prev = None
    for r in rows:
        m = _num((r.values or {}).get(meter_param)) if meter_param else None
        r.meter_value = m
        r.diff = round(m - prev, 2) if (m is not None and prev is not None) else None
        if m is not None:
            prev = m


@router.get("/api/readings")
def api_readings(asset_id: int, user: Employee = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    _guard(db, user)
    rows = db.query(MaintReading).filter(MaintReading.asset_id == asset_id).all()
    rows.sort(key=lambda r: (r.reading_date, r.start_time or "", r.id), reverse=True)
    return [_reading_json(r) for r in rows]


@router.post("/api/readings")
def api_create_reading(payload: ReadingIn, user: Employee = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    _guard(db, user)
    if not db.get(MaintAsset, payload.asset_id):
        raise HTTPException(400, "Unknown asset")
    if not _pdate(payload.reading_date):
        raise HTTPException(400, "Reading date is required (YYYY-MM-DD)")
    r = MaintReading(asset_id=payload.asset_id, reading_date=_pdate(payload.reading_date),
                     start_time=(payload.start_time or None), end_time=(payload.end_time or None),
                     values=payload.values or {}, remarks=payload.remarks,
                     entered_by=getattr(user, "name", None))
    db.add(r); db.flush()
    _recompute_readings(db, payload.asset_id, _asset_meter_param(db, payload.asset_id))
    db.commit(); db.refresh(r)
    return _reading_json(r)


@router.put("/api/readings/{reading_id}")
def api_update_reading(reading_id: int, payload: ReadingIn,
                       user: Employee = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    _guard(db, user)
    r = db.get(MaintReading, reading_id)
    if not r:
        raise HTTPException(404, "Reading not found")
    if not _pdate(payload.reading_date):
        raise HTTPException(400, "Reading date is required (YYYY-MM-DD)")
    r.reading_date = _pdate(payload.reading_date)
    r.start_time = payload.start_time or None
    r.end_time = payload.end_time or None
    r.values = payload.values or {}
    r.remarks = payload.remarks
    db.flush()
    _recompute_readings(db, r.asset_id, _asset_meter_param(db, r.asset_id))
    db.commit(); db.refresh(r)
    return _reading_json(r)


@router.delete("/api/readings/{reading_id}")
def api_delete_reading(reading_id: int, user: Employee = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    _guard(db, user)
    r = db.get(MaintReading, reading_id)
    if not r:
        raise HTTPException(404, "Reading not found")
    asset_id = r.asset_id
    db.delete(r); db.flush()
    _recompute_readings(db, asset_id, _asset_meter_param(db, asset_id))
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ PM plans

def _latest_meter(db: Session, asset_id: int):
    rows = db.query(MaintReading).filter(MaintReading.asset_id == asset_id).all()
    rows.sort(key=lambda r: (r.reading_date, r.start_time or "", r.id))
    for r in reversed(rows):
        if r.meter_value is not None:
            return r.meter_value
    return None


_QUARTER_GROUPS = ([1, 4, 7, 10], [2, 5, 8, 11], [3, 6, 9, 12])
_WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _load_holidays(db: Session):
    return {h.holiday_date for h in db.query(MaintHoliday).all()}


def _is_off(d, holidays):
    return d.weekday() == 6 or d in holidays   # Sunday = 6


def _roll_forward(d, holidays):
    guard = 0
    while _is_off(d, holidays) and guard < 60:
        d += timedelta(days=1)
        guard += 1
    return d


def _clamp_dom(y, m, dom):
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(dom, last))


def _add_month(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def _next_occurrence(p, after, holidays):
    """Next scheduled occurrence on/after `after`, rolled off Sundays & holidays.
    None if past end_date or the schedule is incomplete."""
    sd = p.start_date or date.today()
    start = after if after > sd else sd
    f = p.frequency
    occ = None
    if f == "daily":
        occ = _roll_forward(start, holidays)
    elif f == "weekly":
        wds = set(p.weekdays or [])
        if not wds:
            return None
        d = start
        for _ in range(14):
            if d.weekday() in wds:
                occ = _roll_forward(d, holidays)
                break
            d += timedelta(days=1)
    elif f == "monthly":
        dom = p.day_of_month or 1
        y, m = start.year, start.month
        occ = _roll_forward(_clamp_dom(y, m, dom), holidays)
        if occ < start:
            y, m = _add_month(y, m)
            occ = _roll_forward(_clamp_dom(y, m, dom), holidays)
    elif f == "quarterly":
        months = sorted(p.quarter_months or [])
        if not months:
            return None
        dom = (p.start_date or date.today()).day
        cands = []
        for yy in (start.year, start.year + 1):
            for mm in months:
                c = _roll_forward(_clamp_dom(yy, mm, dom), holidays)
                if c >= start:
                    cands.append(c)
        occ = min(cands) if cands else None
    if occ and p.end_date and occ > p.end_date:
        return None
    return occ


def _schedule_label(p):
    f = p.frequency
    if f == "daily":
        return "Daily (working days)"
    if f == "weekly":
        return "Weekly (" + ", ".join(_WD[w] for w in sorted(p.weekdays or [])) + ")"
    if f == "monthly":
        return f"Monthly (day {p.day_of_month})"
    if f == "quarterly":
        months = sorted(p.quarter_months or [])
        dom = p.start_date.day if p.start_date else "?"
        return "Quarterly (" + "/".join(calendar.month_abbr[m] for m in months) + f", day {dom})"
    return f or "—"


def _plan_json(db: Session, p: MaintPMPlan, holidays=None):
    if holidays is None:
        holidays = _load_holidays(db)
    today = date.today()
    after = (p.last_done_date + timedelta(days=1)) if p.last_done_date else (p.start_date or today)
    nxt = _next_occurrence(p, after, holidays)
    cur = _latest_meter(db, p.asset_id)
    ndm = (p.last_done_meter + p.interval_meter) if (p.last_done_meter is not None and p.interval_meter) else None
    due_date = bool(nxt and today >= nxt)
    due_meter = bool(ndm is not None and cur is not None and cur >= ndm)
    a = db.get(MaintAsset, p.asset_id)
    return {
        "id": p.id, "asset_id": p.asset_id,
        "asset_code": a.asset_code if a else None,
        "asset_description": a.description if a else None,
        "task": p.task, "frequency": p.frequency, "weekdays": p.weekdays,
        "day_of_month": p.day_of_month, "quarter_months": p.quarter_months,
        "start_date": _iso(p.start_date), "end_date": _iso(p.end_date),
        "schedule_label": _schedule_label(p), "interval_meter": p.interval_meter,
        "last_done_date": _iso(p.last_done_date), "last_done_meter": p.last_done_meter,
        "next_due_date": _iso(nxt), "next_due_meter": ndm, "current_meter": cur,
        "due": bool(due_date or due_meter), "due_date": due_date, "due_meter": due_meter,
        "never_done": p.last_done_date is None,
        "days_overdue": (today - nxt).days if (nxt and today >= nxt) else None,
        "meter_remaining": round(ndm - cur, 2) if (ndm is not None and cur is not None) else None,
        "active": p.active,
    }


class PMPlanIn(BaseModel):
    asset_id: int
    task: str
    frequency: str
    weekdays: list[int] | None = None
    day_of_month: int | None = None
    quarter_months: list[int] | None = None
    start_date: str | None = None
    end_date: str | None = None
    interval_meter: float | None = None
    active: bool = True


class PMDoneIn(BaseModel):
    done_date: str | None = None
    attended_by_id: int | None = None
    verified_by_id: int | None = None
    remarks: str | None = None


def _validate_plan(payload: PMPlanIn):
    if not (payload.task or "").strip():
        raise HTTPException(400, "Task is required")
    if payload.frequency not in ("daily", "weekly", "monthly", "quarterly"):
        raise HTTPException(400, "Choose a frequency")
    if not _pdate(payload.start_date):
        raise HTTPException(400, "Start date is required")
    if payload.frequency == "weekly" and not payload.weekdays:
        raise HTTPException(400, "Select at least one weekday")
    if payload.frequency == "monthly" and not (payload.day_of_month and 1 <= payload.day_of_month <= 31):
        raise HTTPException(400, "Enter a day of month (1-31)")
    if payload.frequency == "quarterly" and sorted(payload.quarter_months or []) not in [list(g) for g in _QUARTER_GROUPS]:
        raise HTTPException(400, "Choose a valid quarter group")


def _apply_plan(p: MaintPMPlan, payload: PMPlanIn):
    p.asset_id = payload.asset_id
    p.task = (payload.task or "").strip()
    p.frequency = payload.frequency
    p.weekdays = payload.weekdays or None
    p.day_of_month = payload.day_of_month
    p.quarter_months = payload.quarter_months or None
    p.start_date = _pdate(payload.start_date) or date.today()
    p.end_date = _pdate(payload.end_date)
    p.interval_meter = payload.interval_meter
    p.interval_days = None
    p.active = payload.active


@router.get("/api/pm-plans")
def api_pm_plans(asset_id: int | None = None, user: Employee = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    _guard(db, user)
    qy = db.query(MaintPMPlan)
    if asset_id:
        qy = qy.filter(MaintPMPlan.asset_id == asset_id)
    out = [_plan_json(db, p) for p in qy.all()]
    out.sort(key=lambda x: (not x["due"], not x["never_done"], x["next_due_date"] or "9999-12-31"))
    return out


@router.post("/api/pm-plans")
def api_create_plan(payload: PMPlanIn, user: Employee = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    _guard(db, user)
    if not db.get(MaintAsset, payload.asset_id):
        raise HTTPException(400, "Unknown asset")
    _validate_plan(payload)
    p = MaintPMPlan(asset_id=payload.asset_id)
    _apply_plan(p, payload)
    db.add(p); db.commit(); db.refresh(p)
    return _plan_json(db, p)


@router.put("/api/pm-plans/{plan_id}")
def api_update_plan(plan_id: int, payload: PMPlanIn,
                    user: Employee = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    _guard(db, user)
    p = db.get(MaintPMPlan, plan_id)
    if not p:
        raise HTTPException(404, "Plan not found")
    _validate_plan(payload)
    _apply_plan(p, payload)
    db.commit(); db.refresh(p)
    return _plan_json(db, p)


@router.delete("/api/pm-plans/{plan_id}")
def api_delete_plan(plan_id: int, user: Employee = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    _guard(db, user)
    p = db.get(MaintPMPlan, plan_id)
    if not p:
        raise HTTPException(404, "Plan not found")
    db.delete(p); db.commit()
    return {"ok": True}


@router.post("/api/pm-plans/{plan_id}/done")
def api_plan_done(plan_id: int, payload: PMDoneIn,
                  user: Employee = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    _guard(db, user)
    p = db.get(MaintPMPlan, plan_id)
    if not p:
        raise HTTPException(404, "Plan not found")
    dd = _pdate(payload.done_date) or date.today()
    cur = _latest_meter(db, p.asset_id)
    e = MaintEvent(asset_id=p.asset_id, event_date=dd, category="Scheduled PM",
                   complaint=p.task, action="PM completed", meter_at_event=cur,
                   attended_by_id=payload.attended_by_id, verified_by_id=payload.verified_by_id,
                   remarks=payload.remarks, pm_plan_id=p.id)
    db.add(e)
    p.last_done_date = dd
    p.last_done_meter = cur
    db.commit(); db.refresh(p)
    return _plan_json(db, p)


# ------------------------------------------------------------------ holidays

class HolidayIn(BaseModel):
    holiday_date: str
    name: str | None = None


@router.get("/api/holidays")
def api_holidays(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _guard(db, user)
    rows = db.query(MaintHoliday).order_by(MaintHoliday.holiday_date).all()
    return [{"id": h.id, "holiday_date": _iso(h.holiday_date), "name": h.name} for h in rows]


@router.post("/api/holidays")
def api_create_holiday(payload: HolidayIn, user: Employee = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    _guard(db, user)
    d = _pdate(payload.holiday_date)
    if not d:
        raise HTTPException(400, "Date is required")
    if db.query(MaintHoliday).filter_by(holiday_date=d).first():
        raise HTTPException(400, "That date is already a holiday")
    h = MaintHoliday(holiday_date=d, name=(payload.name or None))
    db.add(h); db.commit(); db.refresh(h)
    return {"id": h.id, "holiday_date": _iso(h.holiday_date), "name": h.name}


@router.delete("/api/holidays/{holiday_id}")
def api_delete_holiday(holiday_id: int, user: Employee = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    _guard(db, user)
    h = db.get(MaintHoliday, holiday_id)
    if not h:
        raise HTTPException(404, "Holiday not found")
    db.delete(h); db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ dashboard

@router.get("/api/dashboard")
def api_dashboard(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _guard(db, user)
    from collections import defaultdict
    today = date.today()
    since30 = today - timedelta(days=30)
    assets = {a.id: a for a in db.query(MaintAsset).all()}
    events = db.query(MaintEvent).all()

    def acode(aid):
        return assets[aid].asset_code if aid in assets else "?"

    def adesc(aid):
        return assets[aid].description if aid in assets else ""

    breakdowns = [e for e in events if e.category == "Breakdown"]
    pms = [e for e in events if e.category in ("Scheduled PM", "Unscheduled PM")]
    open_bd = [e for e in breakdowns if (e.status or "Open") != "Closed"]

    total_downtime = round(sum(e.downtime_hrs or 0 for e in breakdowns), 1)
    downtime_30 = round(sum(e.downtime_hrs or 0 for e in breakdowns
                            if e.event_date and e.event_date >= since30), 1)
    cost_all = round(sum(e.cost or 0 for e in events), 2)
    cost_30 = round(sum(e.cost or 0 for e in events
                        if e.event_date and e.event_date >= since30), 2)
    bd_30 = sum(1 for e in breakdowns if e.event_date and e.event_date >= since30)
    pm_30 = sum(1 for e in pms if e.event_date and e.event_date >= since30)

    open_list = sorted(
        [{"id": e.id, "asset_code": acode(e.asset_id), "asset_description": adesc(e.asset_id),
          "event_date": _iso(e.event_date), "complaint": e.complaint, "status": e.status or "Open",
          "days_open": (today - e.event_date).days if e.event_date else None} for e in open_bd],
        key=lambda x: (x["days_open"] is None, -(x["days_open"] or 0)))

    dt = defaultdict(float)
    freq = defaultdict(int)
    dates = defaultdict(list)
    for e in breakdowns:
        dt[e.asset_id] += e.downtime_hrs or 0
        freq[e.asset_id] += 1
        if e.event_date:
            dates[e.asset_id].append(e.event_date)
    downtime_by_machine = sorted(
        [{"asset_code": acode(k), "asset_description": adesc(k), "hours": round(v, 1)}
         for k, v in dt.items() if v > 0], key=lambda x: -x["hours"])[:10]
    freq_by_machine = []
    for k, c in freq.items():
        ds = sorted(dates[k])
        mtbf = None
        if len(ds) >= 2:
            span = (ds[-1] - ds[0]).days
            mtbf = round(span / (len(ds) - 1), 1) if span > 0 else 0
        freq_by_machine.append({"asset_code": acode(k), "asset_description": adesc(k),
                                "count": c, "mtbf_days": mtbf})
    freq_by_machine.sort(key=lambda x: -x["count"])
    freq_by_machine = freq_by_machine[:10]

    cost_cat = defaultdict(float)
    for e in events:
        cost_cat[e.category] += e.cost or 0
    cost_by_category = sorted([{"category": k, "amount": round(v, 2)} for k, v in cost_cat.items()],
                              key=lambda x: -x["amount"])

    plans = db.query(MaintPMPlan).filter(MaintPMPlan.active.is_(True)).all()
    due = overdue = 0
    _hols = _load_holidays(db)
    for p in plans:
        pj = _plan_json(db, p, _hols)
        if pj["due"]:
            due += 1
        if pj["days_overdue"] and pj["days_overdue"] > 0:
            overdue += 1
    active_plans = len(plans)
    compliance = round((active_plans - due) / active_plans * 100) if active_plans else None

    return {
        "open_breakdowns": len(open_bd),
        "total_downtime_hrs": total_downtime, "downtime_30_hrs": downtime_30,
        "cost_all": cost_all, "cost_30": cost_30,
        "breakdowns_30": bd_30, "pm_done_30": pm_30,
        "counts": {"assets": len(assets), "events": len(events),
                   "breakdowns": len(breakdowns), "pms": len(pms)},
        "open_list": open_list,
        "downtime_by_machine": downtime_by_machine,
        "freq_by_machine": freq_by_machine,
        "cost_by_category": cost_by_category,
        "pm": {"active_plans": active_plans, "due": due, "overdue": overdue,
               "compliance_pct": compliance, "pm_done_30": pm_30},
    }


# ------------------------------------------------------------------ PDFs

def _asset_events_sorted(db: Session, asset_id: int):
    rows = db.query(MaintEvent).filter(MaintEvent.asset_id == asset_id).all()
    rows.sort(key=lambda e: (e.event_date or date.min, e.id))
    return rows


def _breakdown_rows(db: Session, frm, to, asset_id):
    qy = db.query(MaintEvent).filter(MaintEvent.category == "Breakdown")
    if asset_id:
        qy = qy.filter(MaintEvent.asset_id == asset_id)
    df, dt = _pdate(frm), _pdate(to)
    rows = [e for e in qy.all()
            if (not df or (e.event_date and e.event_date >= df))
            and (not dt or (e.event_date and e.event_date <= dt))]
    rows.sort(key=lambda e: (e.event_date or date.min, e.id), reverse=True)
    return rows


def _range_label(frm, to):
    if frm and to:
        return f"{frm} to {to}"
    if frm:
        return f"from {frm}"
    if to:
        return f"up to {to}"
    return "All dates"


@router.get("/api/asset/pdf")
def api_asset_pdf(asset_id: int, user: Employee = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    _guard(db, user)
    a = db.get(MaintAsset, asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    from ..services.maint_pdf import build_history_card
    events = [_event_json(e) for e in _asset_events_sorted(db, asset_id)]
    pdf = build_history_card(_asset_json(a), events)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="history-{a.asset_code}.pdf"'})


@router.post("/api/asset/pdf/upload")
def api_asset_pdf_upload(asset_id: int, user: Employee = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    _guard(db, user)
    a = db.get(MaintAsset, asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    from ..services.maint_pdf import build_history_card
    events = [_event_json(e) for e in _asset_events_sorted(db, asset_id)]
    pdf = build_history_card(_asset_json(a), events)
    path = f"Maintenance/Machine History Cards/{a.asset_code}.pdf"
    info = _od.upload_to_path(pdf, path, "application/pdf")
    return {"ok": True, "url": (info or {}).get("webUrl")}


@router.get("/api/breakdown/pdf")
def api_breakdown_pdf(from_: str | None = Query(None, alias="from"),
                      to: str | None = None, asset_id: int | None = None,
                      user: Employee = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    _guard(db, user)
    from ..services.maint_pdf import build_breakdown_register
    rows = [_event_json(e) for e in _breakdown_rows(db, from_, to, asset_id)]
    pdf = build_breakdown_register(rows, _range_label(from_, to))
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="breakdown-register.pdf"'})


@router.post("/api/breakdown/pdf/upload")
def api_breakdown_pdf_upload(from_: str | None = Query(None, alias="from"),
                             to: str | None = None, asset_id: int | None = None,
                             user: Employee = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    _guard(db, user)
    from ..services.maint_pdf import build_breakdown_register
    rows = [_event_json(e) for e in _breakdown_rows(db, from_, to, asset_id)]
    pdf = build_breakdown_register(rows, _range_label(from_, to))
    path = f"Maintenance/Breakdown Register/Breakdown Register {date.today().isoformat()}.pdf"
    info = _od.upload_to_path(pdf, path, "application/pdf")
    return {"ok": True, "url": (info or {}).get("webUrl")}
