"""Plant Operations — labour & contractor daily attendance.

First feature of the Plant Operations module in the Metfraa portal. Records:
  * own labour — named present/absent/half per day (P / A / H)
  * contractor teams — a split skilled+helper headcount per day (no names)

Admin masters manage the labour roster (name, designation, per-day salary) and
the contractor list (name, per-day rate). Salary/rate are stored now so the
payable report the user will build later needs no schema change.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_current_user
from ..models import (Employee, PlantContractor, PlantContractorAttendance,
                      PlantContractorWorkLog, PlantLabour, PlantLabourAttendance,
                      PlantLabourWorkLog, PlantSettings)

SHIFT_END_MIN = 19 * 60   # 7:00 pm, in minutes from midnight


def _completed_half_hours(ot_till: str | None) -> int:
    """Completed 30-min slots worked AFTER 7pm. Rounds DOWN — a partial slot
    pays nothing until it completes. 7:45 -> 1 (only the 7:00-7:30 slot is
    complete); 8:00 -> 2; 8:29 -> 2; 8:30 -> 3. <=7:00 or invalid -> 0."""
    if not ot_till:
        return 0
    try:
        hh, mm = (int(x) for x in str(ot_till).split(":"))
    except (ValueError, TypeError):
        return 0
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return 0
    # OT is always evening. A plain "7:30" means 7:30 PM (19:30), not morning.
    # Treat 1..11 as PM (+12); 12 stays noon; 13..23 already 24h; 0 -> midnight
    # of the next day (rare, e.g. worked till 00:30) -> +24h.
    if 1 <= hh <= 11:
        hh += 12
    elif hh == 0:
        hh = 24
    end = hh * 60 + mm
    if end <= SHIFT_END_MIN:
        return 0
    return (end - SHIFT_END_MIN) // 30


def _labour_ot_rate(db: Session) -> float:
    row = db.query(PlantSettings).filter(PlantSettings.id == 1).first()
    return row.labour_ot_rate_per_half_hour if row else 50.0

router = APIRouter(prefix="/plant", tags=["plant"])
templates = Jinja2Templates(directory="app/templates")

VALID = {"P", "A", "H"}


def _guard(db: Session, user: Employee):
    if not get_access(db, user).can_admin_plant:
        raise HTTPException(status_code=403, detail="Plant Operations access only")


def _parse_date(s: str | None) -> date:
    if not s:
        return datetime.utcnow().date()
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date (YYYY-MM-DD)")


# ------------------------------------------------------------------ page

@router.get("/", response_class=HTMLResponse)
def page(request: Request, user: Employee = Depends(get_current_user),
         db: Session = Depends(get_db)):
    _guard(db, user)
    return templates.TemplateResponse(request, "plant.html", {"user": user})


# ---------------------------------------------------------- daily attendance

@router.get("/api/day")
def api_day(date: str | None = None, user: Employee = Depends(get_current_user),
            db: Session = Depends(get_db)):
    """The roster + contractor list for one day, pre-filled with any saved marks.
    Absent labour defaults to P (present) in the UI; unsaved contractors to 0."""
    _guard(db, user)
    d = _parse_date(date)

    labour = (db.query(PlantLabour).filter(PlantLabour.active == True)  # noqa: E712
              .order_by(PlantLabour.id).all())
    lmarks = {a.labour_id: a.status for a in
              db.query(PlantLabourAttendance)
              .filter(PlantLabourAttendance.att_date == d).all()}
    contractors = (db.query(PlantContractor).filter(PlantContractor.active == True)  # noqa: E712
                   .order_by(PlantContractor.id).all())
    cmarks = {a.contractor_id: a for a in
              db.query(PlantContractorAttendance)
              .filter(PlantContractorAttendance.att_date == d).all()}

    lrec = {a.labour_id: a for a in
            db.query(PlantLabourAttendance)
            .filter(PlantLabourAttendance.att_date == d).all()}
    return {
        "date": d.isoformat(),
        "labour_ot_rate": _labour_ot_rate(db),
        "labour": [{"id": l.id, "name": l.name, "designation": l.designation or "",
                    "status": lmarks.get(l.id, "P"),
                    "half_part": (lrec[l.id].half_part if l.id in lrec else None),
                    "ot": bool(lrec[l.id].ot) if l.id in lrec else False,
                    "ot_till": (lrec[l.id].ot_till if l.id in lrec else "") or ""}
                   for l in labour],
        "contractors": [{"id": c.id, "name": c.name,
                         "ot_rate_per_half_hour": c.ot_rate_per_half_hour,
                         "skilled": cmarks[c.id].skilled if c.id in cmarks else 0,
                         "helper": cmarks[c.id].helper if c.id in cmarks else 0,
                         "ot": bool(cmarks[c.id].ot) if c.id in cmarks else False,
                         "ot_persons": cmarks[c.id].ot_persons if c.id in cmarks else 0,
                         "ot_till": (cmarks[c.id].ot_till if c.id in cmarks else "") or ""}
                        for c in contractors],
        "labour_worklog": [{"nature_of_work": w.nature_of_work or "",
                            "skilled": w.skilled, "helper": w.helper,
                            "qty_nos": w.qty_nos, "weight_kg": w.weight_kg,
                            "remarks": w.remarks or ""}
                           for w in db.query(PlantLabourWorkLog)
                           .filter(PlantLabourWorkLog.log_date == d)
                           .order_by(PlantLabourWorkLog.seq, PlantLabourWorkLog.id).all()],
        "contractor_worklog": [{"contractor_id": w.contractor_id,
                                "nature_of_work": w.nature_of_work or "",
                                "workers": w.workers,
                                "qty_nos": w.qty_nos, "weight_kg": w.weight_kg,
                                "remarks": w.remarks or ""}
                               for w in db.query(PlantContractorWorkLog)
                               .filter(PlantContractorWorkLog.log_date == d)
                               .order_by(PlantContractorWorkLog.seq, PlantContractorWorkLog.id).all()],
        "saved": bool(lmarks or cmarks),
    }


@router.post("/api/day")
async def api_save_day(request: Request, user: Employee = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Upsert a whole day's marks. Body:
       { date, labour: [{id, status}], contractors: [{id, skilled, helper}] }"""
    _guard(db, user)
    b = await request.json()
    d = _parse_date(b.get("date"))
    now = datetime.utcnow()

    valid_labour = {row[0] for row in db.query(PlantLabour.id).all()}
    valid_contr = {row[0] for row in db.query(PlantContractor.id).all()}

    lrate = _labour_ot_rate(db)
    for row in (b.get("labour") or []):
        lid = row.get("id")
        st = (row.get("status") or "P").upper()
        if lid not in valid_labour:
            continue
        if st not in VALID:
            raise HTTPException(status_code=400, detail=f"Bad status {st!r}")
        half_part = row.get("half_part") if st == "H" else None
        if half_part not in (1, 2, None):
            half_part = None
        ot = bool(row.get("ot"))
        ot_till = (row.get("ot_till") or "").strip() if ot else None
        hh = _completed_half_hours(ot_till) if ot else 0
        amt = hh * lrate
        rec = (db.query(PlantLabourAttendance)
               .filter(PlantLabourAttendance.labour_id == lid,
                       PlantLabourAttendance.att_date == d).first())
        if rec:
            rec.status = st
            rec.half_part = half_part
            rec.ot, rec.ot_till, rec.ot_half_hours, rec.ot_amount = ot, ot_till, hh, amt
            rec.marked_by = user.employee_code
            rec.updated_at = now
        else:
            db.add(PlantLabourAttendance(labour_id=lid, att_date=d, status=st,
                                         half_part=half_part,
                                         ot=ot, ot_till=ot_till, ot_half_hours=hh,
                                         ot_amount=amt, marked_by=user.employee_code))

    def _int(v):
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0

    crates = {c.id: c.ot_rate_per_half_hour for c in db.query(PlantContractor).all()}
    for row in (b.get("contractors") or []):
        cid = row.get("id")
        if cid not in valid_contr:
            continue
        sk, hp = _int(row.get("skilled")), _int(row.get("helper"))
        ot = bool(row.get("ot"))
        ot_persons = _int(row.get("ot_persons")) if ot else 0
        ot_till = (row.get("ot_till") or "").strip() if ot else None
        chh = _completed_half_hours(ot_till) if ot else 0
        camt = ot_persons * chh * crates.get(cid, 50)
        rec = (db.query(PlantContractorAttendance)
               .filter(PlantContractorAttendance.contractor_id == cid,
                       PlantContractorAttendance.att_date == d).first())
        if rec:
            rec.skilled, rec.helper = sk, hp
            rec.ot, rec.ot_persons, rec.ot_till = ot, ot_persons, ot_till
            rec.ot_half_hours, rec.ot_amount = chh, camt
            rec.marked_by = user.employee_code
            rec.updated_at = now
        elif sk or hp or ot:
            db.add(PlantContractorAttendance(contractor_id=cid, att_date=d,
                                             skilled=sk, helper=hp, ot=ot,
                                             ot_persons=ot_persons, ot_till=ot_till,
                                             ot_half_hours=chh, ot_amount=camt,
                                             marked_by=user.employee_code))

    # Work logs: full-replace for the day (the screen edits the whole day).
    def _fnum(v):
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    if "labour_worklog" in b:
        db.query(PlantLabourWorkLog).filter(PlantLabourWorkLog.log_date == d).delete()
        for i, w in enumerate(b.get("labour_worklog") or []):
            now_row = PlantLabourWorkLog(
                log_date=d, nature_of_work=(w.get("nature_of_work") or "").strip() or None,
                skilled=_int(w.get("skilled")), helper=_int(w.get("helper")),
                qty_nos=_fnum(w.get("qty_nos")), weight_kg=_fnum(w.get("weight_kg")),
                remarks=(w.get("remarks") or "").strip() or None, seq=i,
                marked_by=user.employee_code)
            # skip wholly-empty rows
            if (now_row.nature_of_work or now_row.skilled or now_row.helper
                    or now_row.qty_nos or now_row.weight_kg or now_row.remarks):
                db.add(now_row)

    if "contractor_worklog" in b:
        db.query(PlantContractorWorkLog).filter(PlantContractorWorkLog.log_date == d).delete()
        for i, w in enumerate(b.get("contractor_worklog") or []):
            cid = w.get("contractor_id")
            cid = cid if cid in valid_contr else None
            row = PlantContractorWorkLog(
                log_date=d, contractor_id=cid,
                nature_of_work=(w.get("nature_of_work") or "").strip() or None,
                workers=_int(w.get("workers")),
                qty_nos=_fnum(w.get("qty_nos")), weight_kg=_fnum(w.get("weight_kg")),
                remarks=(w.get("remarks") or "").strip() or None, seq=i,
                marked_by=user.employee_code)
            if (row.contractor_id or row.nature_of_work or row.workers
                    or row.qty_nos or row.weight_kg or row.remarks):
                db.add(row)

    db.commit()
    return {"ok": True, "date": d.isoformat()}


# --------------------------------------------------------------- masters

@router.get("/api/labour")
def api_labour_list(include_inactive: str | None = None,
                    user: Employee = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    _guard(db, user)
    q = db.query(PlantLabour)
    if str(include_inactive or "").lower() not in ("1", "true", "yes"):
        q = q.filter(PlantLabour.active == True)  # noqa: E712
    rows = q.order_by(PlantLabour.active.desc(), PlantLabour.id).all()
    return {"labour": [{"id": l.id, "name": l.name, "designation": l.designation or "",
                        "per_day_salary": l.per_day_salary, "active": l.active}
                       for l in rows]}


@router.post("/api/labour")
async def api_labour_save(request: Request, user: Employee = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    _guard(db, user)
    b = await request.json()
    name = (b.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    def _sal(v):
        try:
            return max(0.0, float(v or 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid salary")

    lid = b.get("id")
    if lid:
        l = db.query(PlantLabour).filter(PlantLabour.id == lid).first()
        if not l:
            raise HTTPException(status_code=404, detail="Labour not found")
        l.name = name
        l.designation = (b.get("designation") or "").strip() or None
        l.per_day_salary = _sal(b.get("per_day_salary"))
        if "active" in b:
            l.active = bool(b["active"])
    else:
        db.add(PlantLabour(name=name,
                           designation=(b.get("designation") or "").strip() or None,
                           per_day_salary=_sal(b.get("per_day_salary")),
                           active=bool(b.get("active", True))))
    db.commit()
    return {"ok": True}


@router.delete("/api/labour/{lid}")
def api_labour_delete(lid: int, user: Employee = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Soft-delete: deactivate so historic attendance is preserved. A labourer
    with no attendance at all is removed outright."""
    _guard(db, user)
    l = db.query(PlantLabour).filter(PlantLabour.id == lid).first()
    if not l:
        raise HTTPException(status_code=404, detail="Not found")
    has_history = (db.query(PlantLabourAttendance)
                   .filter(PlantLabourAttendance.labour_id == lid).first() is not None)
    if has_history:
        l.active = False
        db.commit()
        return {"ok": True, "deactivated": True}
    db.delete(l)
    db.commit()
    return {"ok": True, "deleted": True}


@router.get("/api/contractors")
def api_contractor_list(include_inactive: str | None = None,
                        user: Employee = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    _guard(db, user)
    q = db.query(PlantContractor)
    if str(include_inactive or "").lower() not in ("1", "true", "yes"):
        q = q.filter(PlantContractor.active == True)  # noqa: E712
    rows = q.order_by(PlantContractor.active.desc(), PlantContractor.id).all()
    return {"contractors": [{"id": c.id, "name": c.name,
                             "per_day_rate": c.per_day_rate,
                             "ot_rate_per_half_hour": c.ot_rate_per_half_hour,
                             "active": c.active}
                            for c in rows]}


@router.post("/api/contractors")
async def api_contractor_save(request: Request,
                              user: Employee = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    _guard(db, user)
    b = await request.json()
    name = (b.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    def _rate(v):
        try:
            return max(0.0, float(v or 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid rate")

    ot_rate = _rate(b.get("ot_rate_per_half_hour")) if b.get("ot_rate_per_half_hour") not in (None, "") else 50.0
    cid = b.get("id")
    if cid:
        c = db.query(PlantContractor).filter(PlantContractor.id == cid).first()
        if not c:
            raise HTTPException(status_code=404, detail="Contractor not found")
        c.name = name
        c.per_day_rate = _rate(b.get("per_day_rate"))
        c.ot_rate_per_half_hour = ot_rate
        if "active" in b:
            c.active = bool(b["active"])
    else:
        db.add(PlantContractor(name=name, per_day_rate=_rate(b.get("per_day_rate")),
                               ot_rate_per_half_hour=ot_rate,
                               active=bool(b.get("active", True))))
    db.commit()
    return {"ok": True}


@router.delete("/api/contractors/{cid}")
def api_contractor_delete(cid: int, user: Employee = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    _guard(db, user)
    c = db.query(PlantContractor).filter(PlantContractor.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    has_history = (db.query(PlantContractorAttendance)
                   .filter(PlantContractorAttendance.contractor_id == cid)
                   .first() is not None)
    if has_history:
        c.active = False
        db.commit()
        return {"ok": True, "deactivated": True}
    db.delete(c)
    db.commit()
    return {"ok": True, "deleted": True}


# --------------------------------------------------------------- settings

@router.get("/api/settings")
def api_settings(user: Employee = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    _guard(db, user)
    return {"labour_ot_rate_per_half_hour": _labour_ot_rate(db)}


@router.post("/api/settings")
async def api_settings_save(request: Request,
                            user: Employee = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    _guard(db, user)
    b = await request.json()
    try:
        rate = max(0.0, float(b.get("labour_ot_rate_per_half_hour") or 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid rate")
    row = db.query(PlantSettings).filter(PlantSettings.id == 1).first()
    if not row:
        row = PlantSettings(id=1)
        db.add(row)
    row.labour_ot_rate_per_half_hour = rate
    row.updated_by = user.employee_code
    db.commit()
    return {"ok": True, "labour_ot_rate_per_half_hour": rate}
