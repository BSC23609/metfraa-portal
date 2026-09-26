"""Project Operations — site attendance & work progress.

Stage 1: the five masters and the module shell.
  * Site / Job          (job_id + name)
  * Worker Type         (name + default hourly rate)
  * Contractor          (name + standard hours + per-type rate overrides)
  * Part Mark           (per site)
  * Equipment           (flat list)

Rate model: each worker type carries a DEFAULT hourly rate; a contractor may
override it per type. The resolved rate for (contractor, type) is the override
if present, else the type default. OT/hr = the same resolved hourly rate.
Regular pay = headcount x contractor.standard_hours x rate; OT = people x hours
x rate. (Attendance & work capture come in later stages.)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_current_user
from datetime import date, datetime

from ..models import (Employee, ProjContractor, ProjContractorRate, ProjEquipment,
                      ProjPartMark, ProjSite, ProjSiteAttendance, ProjWorkerType,
                      ProjWorkProgress, ProjReportRecipients)
from ..services import onedrive as _od

router = APIRouter(prefix="/project-ops", tags=["project-ops"])
log = logging.getLogger("project_ops")
templates = Jinja2Templates(directory="app/templates")


def _guard(db: Session, user: Employee):
    if not get_access(db, user).can_admin_project_ops:
        raise HTTPException(status_code=403, detail="Project Operations access only")


def _num(v, default=None):
    if v in (None, ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid number")




def _parse_date(sv):
    if not sv:
        return datetime.utcnow().date()
    try:
        return datetime.strptime(sv[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date (YYYY-MM-DD)")


def _resolved_rates(db, contractor_id):
    """{worker_type_id: effective hourly rate} for a contractor — override if
    present, else the worker type's default."""
    defaults = {t.id: t.rate_per_hour for t in db.query(ProjWorkerType).all()}
    ov = {r.worker_type_id: r.rate_per_hour
          for r in db.query(ProjContractorRate)
          .filter(ProjContractorRate.contractor_id == contractor_id).all()}
    return {tid: ov.get(tid, defaults.get(tid, 0)) for tid in defaults}


# ------------------------------------------------------------------ page

@router.get("/", response_class=HTMLResponse)
def page(request: Request, user: Employee = Depends(get_current_user),
         db: Session = Depends(get_db)):
    _guard(db, user)
    return templates.TemplateResponse(request, "project_ops.html", {"user": user})


# --------------------------------------------------------------- sites

@router.get("/api/sites")
def api_sites(include_inactive: str | None = None,
              user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _guard(db, user)
    q = db.query(ProjSite)
    if str(include_inactive or "").lower() not in ("1", "true", "yes"):
        q = q.filter(ProjSite.active == True)  # noqa: E712
    rows = q.order_by(ProjSite.active.desc(), ProjSite.id).all()
    return {"sites": [{"id": s.id, "job_id": s.job_id or "", "name": s.name,
                       "active": s.active} for s in rows]}


@router.post("/api/sites")
async def api_site_save(request: Request, user: Employee = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    _guard(db, user)
    b = await request.json()
    name = (b.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Site name is required")
    job_id = (b.get("job_id") or "").strip() or None
    sid = b.get("id")
    if sid:
        s = db.query(ProjSite).filter(ProjSite.id == sid).first()
        if not s:
            raise HTTPException(status_code=404, detail="Site not found")
        s.name, s.job_id = name, job_id
        if "active" in b:
            s.active = bool(b["active"])
    else:
        db.add(ProjSite(name=name, job_id=job_id, active=bool(b.get("active", True))))
    db.commit()
    return {"ok": True}


@router.delete("/api/sites/{sid}")
def api_site_delete(sid: int, user: Employee = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    _guard(db, user)
    s = db.query(ProjSite).filter(ProjSite.id == sid).first()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    # A site with part marks is deactivated (keeps its parts/history); an empty
    # one is removed.
    has_parts = db.query(ProjPartMark).filter(ProjPartMark.site_id == sid).first()
    if has_parts:
        s.active = False
        db.commit()
        return {"ok": True, "deactivated": True}
    db.delete(s)
    db.commit()
    return {"ok": True, "deleted": True}


# --------------------------------------------------------------- worker types

@router.get("/api/worker-types")
def api_worker_types(include_inactive: str | None = None,
                     user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _guard(db, user)
    q = db.query(ProjWorkerType)
    if str(include_inactive or "").lower() not in ("1", "true", "yes"):
        q = q.filter(ProjWorkerType.active == True)  # noqa: E712
    rows = q.order_by(ProjWorkerType.active.desc(), ProjWorkerType.id).all()
    return {"worker_types": [{"id": w.id, "name": w.name,
                              "rate_per_hour": w.rate_per_hour, "active": w.active}
                             for w in rows]}


@router.post("/api/worker-types")
async def api_worker_type_save(request: Request, user: Employee = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    _guard(db, user)
    b = await request.json()
    name = (b.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Worker type name is required")
    rate = _num(b.get("rate_per_hour"), 0) or 0
    wid = b.get("id")
    if wid:
        w = db.query(ProjWorkerType).filter(ProjWorkerType.id == wid).first()
        if not w:
            raise HTTPException(status_code=404, detail="Worker type not found")
        w.name, w.rate_per_hour = name, rate
        if "active" in b:
            w.active = bool(b["active"])
    else:
        db.add(ProjWorkerType(name=name, rate_per_hour=rate, active=bool(b.get("active", True))))
    db.commit()
    return {"ok": True}


@router.delete("/api/worker-types/{wid}")
def api_worker_type_delete(wid: int, user: Employee = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    _guard(db, user)
    w = db.query(ProjWorkerType).filter(ProjWorkerType.id == wid).first()
    if not w:
        raise HTTPException(status_code=404, detail="Not found")
    used = db.query(ProjContractorRate).filter(ProjContractorRate.worker_type_id == wid).first()
    if used:
        w.active = False
        db.commit()
        return {"ok": True, "deactivated": True}
    db.delete(w)
    db.commit()
    return {"ok": True, "deleted": True}


# --------------------------------------------------------------- contractors

@router.get("/api/contractors")
def api_contractors(include_inactive: str | None = None,
                    user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _guard(db, user)
    q = db.query(ProjContractor)
    if str(include_inactive or "").lower() not in ("1", "true", "yes"):
        q = q.filter(ProjContractor.active == True)  # noqa: E712
    rows = q.order_by(ProjContractor.active.desc(), ProjContractor.id).all()
    # overrides per contractor
    ov = {}
    for r in db.query(ProjContractorRate).all():
        ov.setdefault(r.contractor_id, {})[r.worker_type_id] = r.rate_per_hour
    return {"contractors": [{"id": c.id, "name": c.name,
                             "standard_hours": c.standard_hours, "active": c.active,
                             "overrides": ov.get(c.id, {})} for c in rows]}


@router.get("/api/contractors/{cid}/rates")
def api_contractor_rates(cid: int, user: Employee = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """The resolved rate table for one contractor: each active worker type with
    its default rate, this contractor's override (if any), and the effective
    rate. Feeds the rate panel in the contractor editor."""
    _guard(db, user)
    c = db.query(ProjContractor).filter(ProjContractor.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contractor not found")
    ov = {r.worker_type_id: r.rate_per_hour
          for r in db.query(ProjContractorRate)
          .filter(ProjContractorRate.contractor_id == cid).all()}
    types = (db.query(ProjWorkerType).filter(ProjWorkerType.active == True)  # noqa: E712
             .order_by(ProjWorkerType.id).all())
    return {"contractor_id": cid, "standard_hours": c.standard_hours,
            "rows": [{"worker_type_id": t.id, "name": t.name,
                      "default_rate": t.rate_per_hour,
                      "override": ov.get(t.id),
                      "effective": ov.get(t.id) if t.id in ov else t.rate_per_hour}
                     for t in types]}


@router.post("/api/contractors")
async def api_contractor_save(request: Request, user: Employee = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    """Save a contractor + its rate overrides. Body:
       {id?, name, standard_hours, overrides: {worker_type_id: rate|null}}
       A null/blank override clears it (falls back to the type default)."""
    _guard(db, user)
    b = await request.json()
    name = (b.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Contractor name is required")
    sh = _num(b.get("standard_hours"), 8) or 8
    if sh <= 0:
        sh = 8
    cid = b.get("id")
    if cid:
        c = db.query(ProjContractor).filter(ProjContractor.id == cid).first()
        if not c:
            raise HTTPException(status_code=404, detail="Contractor not found")
        c.name, c.standard_hours = name, sh
        if "active" in b:
            c.active = bool(b["active"])
    else:
        c = ProjContractor(name=name, standard_hours=sh, active=bool(b.get("active", True)))
        db.add(c)
        db.flush()
    # apply overrides
    ov = b.get("overrides") or {}
    valid_types = {row[0] for row in db.query(ProjWorkerType.id).all()}
    for k, v in ov.items():
        try:
            wt = int(k)
        except (TypeError, ValueError):
            continue
        if wt not in valid_types:
            continue
        existing = (db.query(ProjContractorRate)
                    .filter(ProjContractorRate.contractor_id == c.id,
                            ProjContractorRate.worker_type_id == wt).first())
        if v in (None, ""):
            if existing:
                db.delete(existing)          # cleared -> back to default
            continue
        try:
            rate = float(v)
        except (TypeError, ValueError):
            continue
        if existing:
            existing.rate_per_hour = rate
        else:
            db.add(ProjContractorRate(contractor_id=c.id, worker_type_id=wt,
                                      rate_per_hour=rate))
    db.commit()
    return {"ok": True, "id": c.id}


@router.delete("/api/contractors/{cid}")
def api_contractor_delete(cid: int, user: Employee = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    _guard(db, user)
    c = db.query(ProjContractor).filter(ProjContractor.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    # No attendance yet in Stage 1; a contractor with rate overrides is
    # deactivated to keep them, otherwise removed.
    has_rates = db.query(ProjContractorRate).filter(ProjContractorRate.contractor_id == cid).first()
    if has_rates:
        c.active = False
        db.commit()
        return {"ok": True, "deactivated": True}
    db.delete(c)
    db.commit()
    return {"ok": True, "deleted": True}


# --------------------------------------------------------------- part marks

@router.get("/api/part-marks")
def api_part_marks(site_id: int | None = None, include_inactive: str | None = None,
                   user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    """Part marks, optionally filtered to one site (the work-progress dropdown
    always passes site_id so only that site's parts show)."""
    _guard(db, user)
    q = db.query(ProjPartMark)
    if site_id:
        q = q.filter(ProjPartMark.site_id == site_id)
    if str(include_inactive or "").lower() not in ("1", "true", "yes"):
        q = q.filter(ProjPartMark.active == True)  # noqa: E712
    rows = q.order_by(ProjPartMark.site_id, ProjPartMark.id).all()
    smap = {s.id: (f"{s.job_id} · {s.name}" if s.job_id else s.name)
            for s in db.query(ProjSite).all()}
    return {"part_marks": [{"id": p.id, "site_id": p.site_id,
                            "site": smap.get(p.site_id, ""), "mark": p.mark,
                            "description": p.description or "", "active": p.active}
                           for p in rows]}


@router.post("/api/part-marks")
async def api_part_mark_save(request: Request, user: Employee = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    _guard(db, user)
    b = await request.json()
    mark = (b.get("mark") or "").strip()
    if not mark:
        raise HTTPException(status_code=400, detail="Part mark is required")
    site_id = b.get("site_id")
    if not db.query(ProjSite).filter(ProjSite.id == site_id).first():
        raise HTTPException(status_code=400, detail="A valid site is required")
    desc = (b.get("description") or "").strip() or None
    pid = b.get("id")
    if pid:
        p = db.query(ProjPartMark).filter(ProjPartMark.id == pid).first()
        if not p:
            raise HTTPException(status_code=404, detail="Part mark not found")
        p.mark, p.description, p.site_id = mark, desc, site_id
        if "active" in b:
            p.active = bool(b["active"])
    else:
        db.add(ProjPartMark(site_id=site_id, mark=mark, description=desc,
                            active=bool(b.get("active", True))))
    db.commit()
    return {"ok": True}


@router.delete("/api/part-marks/{pid}")
def api_part_mark_delete(pid: int, user: Employee = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    _guard(db, user)
    p = db.query(ProjPartMark).filter(ProjPartMark.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(p)          # no work lines yet in Stage 1
    db.commit()
    return {"ok": True, "deleted": True}


# --------------------------------------------------------------- equipment

@router.get("/api/equipment")
def api_equipment(include_inactive: str | None = None,
                  user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _guard(db, user)
    q = db.query(ProjEquipment)
    if str(include_inactive or "").lower() not in ("1", "true", "yes"):
        q = q.filter(ProjEquipment.active == True)  # noqa: E712
    rows = q.order_by(ProjEquipment.active.desc(), ProjEquipment.id).all()
    return {"equipment": [{"id": e.id, "name": e.name, "active": e.active} for e in rows]}


@router.post("/api/equipment")
async def api_equipment_save(request: Request, user: Employee = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    _guard(db, user)
    b = await request.json()
    name = (b.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Equipment name is required")
    eid = b.get("id")
    if eid:
        e = db.query(ProjEquipment).filter(ProjEquipment.id == eid).first()
        if not e:
            raise HTTPException(status_code=404, detail="Equipment not found")
        e.name = name
        if "active" in b:
            e.active = bool(b["active"])
    else:
        db.add(ProjEquipment(name=name, active=bool(b.get("active", True))))
    db.commit()
    return {"ok": True}


@router.delete("/api/equipment/{eid}")
def api_equipment_delete(eid: int, user: Employee = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    _guard(db, user)
    e = db.query(ProjEquipment).filter(ProjEquipment.id == eid).first()
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(e)
    db.commit()
    return {"ok": True, "deleted": True}


# --------------------------------------------------------------- site attendance

@router.get("/api/attendance")
def api_attendance_day(date: str | None = None,
                       user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    """Everything the attendance screen needs for one day: the active sites,
    contractors (each with standard_hours + resolved per-type rates), the active
    worker types, and any saved rows for the day grouped by (site, contractor)."""
    _guard(db, user)
    d = _parse_date(date)

    sites = [{"id": s.id, "job_id": s.job_id or "", "name": s.name}
             for s in db.query(ProjSite).filter(ProjSite.active == True)  # noqa: E712
             .order_by(ProjSite.id).all()]
    types = [{"id": t.id, "name": t.name, "rate_per_hour": t.rate_per_hour}
             for t in db.query(ProjWorkerType).filter(ProjWorkerType.active == True)  # noqa: E712
             .order_by(ProjWorkerType.id).all()]
    contractors = []
    for c in (db.query(ProjContractor).filter(ProjContractor.active == True)  # noqa: E712
              .order_by(ProjContractor.id).all()):
        contractors.append({"id": c.id, "name": c.name,
                            "standard_hours": c.standard_hours,
                            "rates": _resolved_rates(db, c.id)})

    saved = (db.query(ProjSiteAttendance)
             .filter(ProjSiteAttendance.att_date == d)
             .order_by(ProjSiteAttendance.site_id, ProjSiteAttendance.contractor_id).all())
    # group saved rows into {(site,contractor): {type_id: {...}}}
    groups = {}
    for a in saved:
        key = f"{a.site_id}:{a.contractor_id}"
        g = groups.setdefault(key, {"site_id": a.site_id, "contractor_id": a.contractor_id,
                                    "types": {}})
        g["types"][a.worker_type_id] = {"headcount": a.headcount, "ot": bool(a.ot),
                                        "ot_people": a.ot_people, "ot_hours": a.ot_hours}
    return {"date": d.isoformat(), "sites": sites, "contractors": contractors,
            "worker_types": types, "rows": list(groups.values()),
            "saved": bool(saved)}


@router.post("/api/attendance")
async def api_attendance_save(request: Request, user: Employee = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    """Full-replace the day. Body:
       { date, rows: [{ site_id, contractor_id,
                        types: [{worker_type_id, headcount, ot, ot_people, ot_hours}] }] }
       Regular = headcount x standard_hours x rate; OT = ot_people x ot_hours x rate."""
    _guard(db, user)
    b = await request.json()
    d = _parse_date(b.get("date"))
    now = datetime.utcnow()

    valid_sites = {r[0] for r in db.query(ProjSite.id).all()}
    valid_contr = {c.id: c for c in db.query(ProjContractor).all()}
    valid_types = {r[0] for r in db.query(ProjWorkerType.id).all()}

    def _int(v):
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0

    def _hrs(v):
        try:
            h = float(v or 0)
        except (TypeError, ValueError):
            return 0.0
        return round(h * 2) / 2 if h > 0 else 0.0

    # replace the whole day
    db.query(ProjSiteAttendance).filter(ProjSiteAttendance.att_date == d).delete()

    for row in (b.get("rows") or []):
        sid = row.get("site_id")
        cid = row.get("contractor_id")
        if sid not in valid_sites or cid not in valid_contr:
            continue
        c = valid_contr[cid]
        sh = c.standard_hours or 8
        rates = _resolved_rates(db, cid)
        for tr in (row.get("types") or []):
            wt = tr.get("worker_type_id")
            if wt not in valid_types:
                continue
            hc = _int(tr.get("headcount"))
            ot = bool(tr.get("ot"))
            otp = _int(tr.get("ot_people")) if ot else 0
            oth = _hrs(tr.get("ot_hours")) if ot else 0.0
            rate = rates.get(wt, 0)
            reg = round(hc * sh * rate, 2)
            ota = round(otp * oth * rate, 2)
            # skip wholly-empty type cells
            if not (hc or otp or oth):
                continue
            db.add(ProjSiteAttendance(
                att_date=d, site_id=sid, contractor_id=cid, worker_type_id=wt,
                headcount=hc, ot=ot, ot_people=otp, ot_hours=oth, rate_used=rate,
                regular_amount=reg, ot_amount=ota, marked_by=user.employee_code,
                updated_at=now))
    db.commit()
    return {"ok": True, "date": d.isoformat()}


# --------------------------------------------------------------- work progress

@router.get("/api/work")
def api_work_day(date: str | None = None,
                 user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    """Work-progress rows for a day + the masters the form needs (sites,
    contractors, worker types, equipment, and part marks grouped by site)."""
    _guard(db, user)
    d = _parse_date(date)
    sites = [{"id": s.id, "job_id": s.job_id or "", "name": s.name}
             for s in db.query(ProjSite).filter(ProjSite.active == True)  # noqa: E712
             .order_by(ProjSite.id).all()]
    contractors = [{"id": c.id, "name": c.name}
                   for c in db.query(ProjContractor).filter(ProjContractor.active == True)  # noqa: E712
                   .order_by(ProjContractor.id).all()]
    types = [{"id": t.id, "name": t.name}
             for t in db.query(ProjWorkerType).filter(ProjWorkerType.active == True)  # noqa: E712
             .order_by(ProjWorkerType.id).all()]
    equipment = [{"id": e.id, "name": e.name}
                 for e in db.query(ProjEquipment).filter(ProjEquipment.active == True)  # noqa: E712
                 .order_by(ProjEquipment.id).all()]
    parts_by_site = {}
    for pm in (db.query(ProjPartMark).filter(ProjPartMark.active == True)  # noqa: E712
               .order_by(ProjPartMark.site_id, ProjPartMark.id).all()):
        parts_by_site.setdefault(pm.site_id, []).append(
            {"id": pm.id, "mark": pm.mark, "description": pm.description or ""})

    rows = [{"site_id": w.site_id, "contractor_id": w.contractor_id,
             "part_mark_id": w.part_mark_id, "nature_of_work": w.nature_of_work or "",
             "workers": w.workers or {}, "qty_nos": w.qty_nos, "weight_kg": w.weight_kg,
             "start_time": w.start_time or "", "end_time": w.end_time or "",
             "equipment_ids": w.equipment_ids or [], "remarks": w.remarks or ""}
            for w in db.query(ProjWorkProgress)
            .filter(ProjWorkProgress.log_date == d)
            .order_by(ProjWorkProgress.seq, ProjWorkProgress.id).all()]
    return {"date": d.isoformat(), "sites": sites, "contractors": contractors,
            "worker_types": types, "equipment": equipment,
            "parts_by_site": parts_by_site, "rows": rows, "saved": bool(rows)}


@router.post("/api/work")
async def api_work_save(request: Request, user: Employee = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Full-replace the day's work-progress rows."""
    _guard(db, user)
    b = await request.json()
    d = _parse_date(b.get("date"))
    now = datetime.utcnow()

    valid_sites = {r[0] for r in db.query(ProjSite.id).all()}
    valid_contr = {r[0] for r in db.query(ProjContractor.id).all()}
    valid_types = {r[0] for r in db.query(ProjWorkerType.id).all()}
    valid_equip = {r[0] for r in db.query(ProjEquipment.id).all()}
    # part marks valid only for their own site
    part_site = {p.id: p.site_id for p in db.query(ProjPartMark).all()}

    def _fnum(v):
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    db.query(ProjWorkProgress).filter(ProjWorkProgress.log_date == d).delete()

    for i, w in enumerate(b.get("rows") or []):
        sid = w.get("site_id") if w.get("site_id") in valid_sites else None
        cid = w.get("contractor_id") if w.get("contractor_id") in valid_contr else None
        # part mark must belong to the chosen site
        pmid = w.get("part_mark_id")
        if pmid not in part_site or part_site.get(pmid) != sid:
            pmid = None
        # workers by type, keep only valid types with a positive count
        workers = {}
        for k, v in (w.get("workers") or {}).items():
            try:
                tid = int(k); cnt = int(v)
            except (TypeError, ValueError):
                continue
            if tid in valid_types and cnt > 0:
                workers[str(tid)] = cnt
        equip = [e for e in (w.get("equipment_ids") or []) if e in valid_equip]
        nature = (w.get("nature_of_work") or "").strip() or None
        remarks = (w.get("remarks") or "").strip() or None
        qty = _fnum(w.get("qty_nos")); wt = _fnum(w.get("weight_kg"))
        st = (w.get("start_time") or "").strip() or None
        et = (w.get("end_time") or "").strip() or None
        # skip wholly-empty rows
        if not (sid or cid or pmid or nature or workers or equip or qty or wt or st or et or remarks):
            continue
        db.add(ProjWorkProgress(
            log_date=d, site_id=sid, contractor_id=cid, part_mark_id=pmid,
            nature_of_work=nature, workers=workers or None, qty_nos=qty, weight_kg=wt,
            start_time=st, end_time=et, equipment_ids=equip or None, remarks=remarks,
            seq=i, marked_by=user.employee_code, updated_at=now))
    db.commit()
    return {"ok": True, "date": d.isoformat()}


# --------------------------------------------------------------- browse

@router.get("/api/browse/day")
def api_browse_day(date: str | None = None,
                   user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    """Read-only view of one day: attendance (with names + amounts) and the work
    lines (names, part marks, equipment resolved)."""
    _guard(db, user)
    d = _parse_date(date)
    smap = {s.id: (f"{s.job_id} · {s.name}" if s.job_id else s.name) for s in db.query(ProjSite).all()}
    cmap = {c.id: c.name for c in db.query(ProjContractor).all()}
    tmap = {t.id: t.name for t in db.query(ProjWorkerType).all()}
    emap = {e.id: e.name for e in db.query(ProjEquipment).all()}
    pmap = {p.id: p.mark for p in db.query(ProjPartMark).all()}

    att = (db.query(ProjSiteAttendance).filter(ProjSiteAttendance.att_date == d)
           .order_by(ProjSiteAttendance.site_id, ProjSiteAttendance.contractor_id).all())
    # group attendance by (site, contractor)
    ag = {}
    for a in att:
        key = (a.site_id, a.contractor_id)
        g = ag.setdefault(key, {"site": smap.get(a.site_id, "—"),
                                "contractor": cmap.get(a.contractor_id, "—"),
                                "types": [], "regular": 0.0, "ot": 0.0})
        g["types"].append({"type": tmap.get(a.worker_type_id, "—"),
                           "headcount": a.headcount, "ot_people": a.ot_people,
                           "ot_hours": a.ot_hours, "regular": a.regular_amount,
                           "ot_amount": a.ot_amount})
        g["regular"] += a.regular_amount
        g["ot"] += a.ot_amount
    attendance = [{**v, "total": round(v["regular"] + v["ot"], 2)} for v in ag.values()]

    work = []
    for w in (db.query(ProjWorkProgress)
              .filter(ProjWorkProgress.log_date == d)
              .order_by(ProjWorkProgress.seq, ProjWorkProgress.id).all()):
        workers = ", ".join(f"{tmap.get(int(k), '?')} {v}" for k, v in (w.workers or {}).items())
        work.append({"site": smap.get(w.site_id, "—"), "contractor": cmap.get(w.contractor_id, "—"),
                     "part_mark": pmap.get(w.part_mark_id, ""), "nature_of_work": w.nature_of_work or "",
                     "workers": workers, "qty_nos": w.qty_nos, "weight_kg": w.weight_kg,
                     "start_time": w.start_time or "", "end_time": w.end_time or "",
                     "equipment": ", ".join(emap.get(e, "?") for e in (w.equipment_ids or [])),
                     "remarks": w.remarks or ""})

    pay = round(sum(a["total"] for a in attendance), 2)
    return {"date": d.isoformat(), "attendance": attendance, "work": work,
            "summary": {"pay": pay, "work_lines": len(work),
                        "has_data": bool(attendance or work)}}


@router.get("/api/browse/range")
def api_browse_range(start: str | None = None, end: str | None = None,
                     user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    """Per-day roll-up over a range: labour pay, work lines, qty & weight."""
    _guard(db, user)
    e = _parse_date(end); s_ = _parse_date(start)
    if s_ > e:
        s_, e = e, s_
    from collections import defaultdict
    days = defaultdict(lambda: {"pay": 0.0, "work_lines": 0, "qty": 0.0, "weight": 0.0})
    for a in (db.query(ProjSiteAttendance)
              .filter(ProjSiteAttendance.att_date >= s_, ProjSiteAttendance.att_date <= e).all()):
        days[a.att_date.isoformat()]["pay"] += a.regular_amount + a.ot_amount
    for w in (db.query(ProjWorkProgress)
              .filter(ProjWorkProgress.log_date >= s_, ProjWorkProgress.log_date <= e).all()):
        k = w.log_date.isoformat()
        days[k]["work_lines"] += 1
        days[k]["qty"] += w.qty_nos or 0
        days[k]["weight"] += w.weight_kg or 0
    rows = [{"date": k, "pay": round(v["pay"], 2), "work_lines": v["work_lines"],
             "qty": round(v["qty"], 2), "weight": round(v["weight"], 2)} for k, v in days.items()]
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {"start": s_.isoformat(), "end": e.isoformat(), "days": rows}


# --------------------------------------------------------------- dashboard

@router.get("/api/dashboard")
def api_dashboard(start: str | None = None, end: str | None = None,
                  user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    """Range aggregates: daily pay + weight trend; pay by contractor; weight by
    site; headline totals."""
    _guard(db, user)
    e = _parse_date(end); s_ = _parse_date(start)
    if s_ > e:
        s_, e = e, s_
    from collections import defaultdict
    from datetime import timedelta
    smap = {s.id: (f"{s.job_id} · {s.name}" if s.job_id else s.name) for s in db.query(ProjSite).all()}
    cmap = {c.id: c.name for c in db.query(ProjContractor).all()}

    trend = defaultdict(lambda: {"pay": 0.0, "weight": 0.0})
    by_contractor = defaultdict(lambda: {"regular": 0.0, "ot": 0.0})
    by_site = defaultdict(lambda: {"qty": 0.0, "weight": 0.0})

    for a in (db.query(ProjSiteAttendance)
              .filter(ProjSiteAttendance.att_date >= s_, ProjSiteAttendance.att_date <= e).all()):
        trend[a.att_date.isoformat()]["pay"] += a.regular_amount + a.ot_amount
        c = by_contractor[cmap.get(a.contractor_id, "—")]
        c["regular"] += a.regular_amount; c["ot"] += a.ot_amount
    for w in (db.query(ProjWorkProgress)
              .filter(ProjWorkProgress.log_date >= s_, ProjWorkProgress.log_date <= e).all()):
        trend[w.log_date.isoformat()]["weight"] += w.weight_kg or 0
        bs = by_site[smap.get(w.site_id, "—")]
        bs["qty"] += w.qty_nos or 0; bs["weight"] += w.weight_kg or 0

    days = []
    cur = s_
    while cur <= e:
        k = cur.isoformat()
        t = trend.get(k, {"pay": 0.0, "weight": 0.0})
        days.append({"date": k, "pay": round(t["pay"], 2), "weight": round(t["weight"], 2)})
        cur += timedelta(days=1)

    contractors = sorted(({"contractor": n, "regular": round(v["regular"], 2),
                           "ot": round(v["ot"], 2), "total": round(v["regular"] + v["ot"], 2)}
                          for n, v in by_contractor.items()),
                         key=lambda r: r["total"], reverse=True)
    sites = sorted(({"site": n, "qty": round(v["qty"], 2), "weight": round(v["weight"], 2)}
                    for n, v in by_site.items()), key=lambda r: r["weight"], reverse=True)
    totals = {"pay": round(sum(d["pay"] for d in days), 2),
              "weight": round(sum(d["weight"] for d in days), 2),
              "qty": round(sum(s["qty"] for s in sites), 2)}
    return {"start": s_.isoformat(), "end": e.isoformat(), "days": days,
            "contractors": contractors, "sites": sites, "totals": totals}


PROJ_ROOT = "Project Operations/Attendance and Work"
DAILY_DIR = PROJ_ROOT + "/DAILY REPORT"
WEEKLY_DIR = PROJ_ROOT + "/WEEKLY REPORT"
DEFAULT_TO = "accounts@metfraa.com"
DEFAULT_CC = ["vp@metfraa.com", "nirmal@metfraa.com", "pc@metfraa.com",
              "arasu@metfraa.com", "info@metfraa.com"]


def _safe(name):
    return "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in (name or "x")).strip() or "x"


def _week_window(anchor=None):
    """The most recently COMPLETED Sat->Fri week. Report runs on a Saturday for
    the week that ended the day before (Friday). Returns (start_sat, end_fri)."""
    from datetime import date as _d, timedelta
    t = anchor or _d.today()
    # weekday(): Mon=0..Sun=6; Saturday=5. Find the most recent Friday (end).
    # days since last Friday:
    days_since_fri = (t.weekday() - 4) % 7   # Friday=4
    if days_since_fri == 0:
        days_since_fri = 7 if False else 0
    end_fri = t - timedelta(days=days_since_fri if days_since_fri else 0)
    if t.weekday() == 4:            # today is Friday -> last completed ended last Fri
        end_fri = t - timedelta(days=7)
    elif days_since_fri == 0:       # safety
        end_fri = t - timedelta(days=7)
    start_sat = end_fri - timedelta(days=6)
    return start_sat, end_fri


def _week_from_end(end_iso):
    from datetime import timedelta
    end = _parse_date(end_iso)
    return end - timedelta(days=6), end


def _week_label(start, end):
    if start.year == end.year:
        return f"{start.strftime('%d %b')}-{end.strftime('%d %b %Y')}"
    return f"{start.strftime('%d %b %Y')}-{end.strftime('%d %b %Y')}"


def _recipients(db):
    r = db.query(ProjReportRecipients).filter(ProjReportRecipients.id == 1).first()
    if not r:
        return DEFAULT_TO, list(DEFAULT_CC)
    cc = [x.strip() for x in (r.cc_emails or "").split(",") if x.strip()]
    return (r.to_email or DEFAULT_TO), cc


# ---- shared data assembly ----

def _att_rows_for(db, start, end, contractor_id=None):
    """Attendance rows resolved to names, within [start,end], optionally one
    contractor. Returns list of {site, contractor, contractor_id, worker_type,
    headcount, ot_text, amount, regular, ot}."""
    smap = {s.id: (f"{s.job_id} · {s.name}" if s.job_id else s.name) for s in db.query(ProjSite).all()}
    cmap = {c.id: c.name for c in db.query(ProjContractor).all()}
    tmap = {t.id: t.name for t in db.query(ProjWorkerType).all()}
    q = (db.query(ProjSiteAttendance)
         .filter(ProjSiteAttendance.att_date >= start, ProjSiteAttendance.att_date <= end))
    if contractor_id:
        q = q.filter(ProjSiteAttendance.contractor_id == contractor_id)
    out = []
    for a in q.order_by(ProjSiteAttendance.att_date, ProjSiteAttendance.site_id).all():
        ot_text = f"{a.ot_people}×{_fmt_hours(a.ot_hours)}h" if a.ot else ""
        out.append({"site": smap.get(a.site_id, "—"), "contractor": cmap.get(a.contractor_id, "—"),
                    "contractor_id": a.contractor_id, "worker_type": tmap.get(a.worker_type_id, "—"),
                    "headcount": a.headcount, "ot_text": ot_text,
                    "amount": a.regular_amount + a.ot_amount,
                    "regular": a.regular_amount, "ot": a.ot_amount})
    return out


def _fmt_hours(h):
    h = h or 0
    return str(int(h)) if h == int(h) else str(h)


def _work_rows_for(db, start, end, contractor_id=None):
    smap = {s.id: (f"{s.job_id} · {s.name}" if s.job_id else s.name) for s in db.query(ProjSite).all()}
    cmap = {c.id: c.name for c in db.query(ProjContractor).all()}
    tmap = {t.id: t.name for t in db.query(ProjWorkerType).all()}
    emap = {e.id: e.name for e in db.query(ProjEquipment).all()}
    pmap = {p.id: p.mark for p in db.query(ProjPartMark).all()}
    q = (db.query(ProjWorkProgress)
         .filter(ProjWorkProgress.log_date >= start, ProjWorkProgress.log_date <= end))
    if contractor_id:
        q = q.filter(ProjWorkProgress.contractor_id == contractor_id)
    out = []
    for w in q.order_by(ProjWorkProgress.log_date, ProjWorkProgress.seq).all():
        workers = ", ".join(f"{tmap.get(int(k), '?')} {v}" for k, v in (w.workers or {}).items())
        t = (w.start_time or "") + (("-" + w.end_time) if w.end_time else "")
        out.append({"site": smap.get(w.site_id, "—"), "contractor": cmap.get(w.contractor_id, "—"),
                    "contractor_id": w.contractor_id, "part_mark": pmap.get(w.part_mark_id, ""),
                    "nature_of_work": w.nature_of_work or "", "workers": workers,
                    "qty_nos": w.qty_nos, "weight_kg": w.weight_kg, "time": t,
                    "equipment": ", ".join(emap.get(e, "?") for e in (w.equipment_ids or []))})
    return out


# --------------------------------------------------------------- recipients master

@router.get("/api/recipients")
def api_recipients(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _guard(db, user)
    to, cc = _recipients(db)
    return {"to_email": to, "cc_emails": cc}


@router.post("/api/recipients")
async def api_recipients_save(request: Request, user: Employee = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    _guard(db, user)
    b = await request.json()
    to = (b.get("to_email") or "").strip() or DEFAULT_TO
    cc = b.get("cc_emails")
    if isinstance(cc, list):
        cc = ",".join(x.strip() for x in cc if x.strip())
    else:
        cc = (cc or "").strip()
    r = db.query(ProjReportRecipients).filter(ProjReportRecipients.id == 1).first()
    if not r:
        r = ProjReportRecipients(id=1)
        db.add(r)
    r.to_email, r.cc_emails, r.updated_by = to, cc, user.employee_code
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------- daily report

@router.post("/api/reports/daily")
async def api_daily_submit(request: Request, user: Employee = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    _guard(db, user)
    b = await request.json()
    d = _parse_date(b.get("date"))
    att = _att_rows_for(db, d, d)
    work = _work_rows_for(db, d, d)
    if not (att or work):
        return {"ok": True, "uploaded": False, "message": "Nothing recorded — nothing to submit."}
    pay = sum(a["amount"] for a in att)
    weight = sum((w["weight_kg"] or 0) for w in work)
    summary = {"pay": pay, "weight": weight, "work_lines": len(work)}
    try:
        from ..services.project_pdf import build_daily_pdf
        pdf = build_daily_pdf(d, att, work, summary)
        path = f"{DAILY_DIR}/{d.strftime('%Y-%m')}/{d.isoformat()}.pdf"
        info = _od.upload_to_path(pdf, path, "application/pdf")
        return {"ok": True, "uploaded": True, "url": (info or {}).get("webUrl"),
                "message": "Daily report submitted to OneDrive."}
    except Exception as e:
        log.error("[project-ops] daily submit failed: %s", e, exc_info=True)
        return {"ok": True, "uploaded": False, "message": f"OneDrive upload failed: {e}"}


# --------------------------------------------------------------- weekly report

def _weekly_by_contractor(db, start, end):
    """Group the week's data per contractor. Returns list of
    {contractor_id, name, att_rows, work_rows, totals}."""
    cmap = {c.id: c.name for c in db.query(ProjContractor).all()}
    att = _att_rows_for(db, start, end)
    work = _work_rows_for(db, start, end)
    ids = {a["contractor_id"] for a in att} | {w["contractor_id"] for w in work}
    out = []
    for cid in sorted(i for i in ids if i is not None):
        crows = [a for a in att if a["contractor_id"] == cid]
        wrows = [w for w in work if w["contractor_id"] == cid]
        reg = sum(a["regular"] for a in crows)
        ot = sum(a["ot"] for a in crows)
        out.append({"contractor_id": cid, "name": cmap.get(cid, "—"),
                    "att_rows": crows, "work_rows": wrows,
                    "totals": {"regular": reg, "ot": ot, "grand": reg + ot}})
    return out


@router.get("/api/reports/weekly")
def api_weekly_preview(end: str | None = None,
                       user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    """Per-contractor totals for a week. `end` = the Friday; defaults to the last
    completed week's Friday."""
    _guard(db, user)
    if end:
        start, endd = _week_from_end(end)
    else:
        start, endd = _week_window()
    groups = _weekly_by_contractor(db, start, endd)
    return {"start": start.isoformat(), "end": endd.isoformat(),
            "label": _week_label(start, endd),
            "default_end": _week_window()[1].isoformat(),
            "contractors": [{"contractor_id": g["contractor_id"], "name": g["name"],
                             "regular": g["totals"]["regular"], "ot": g["totals"]["ot"],
                             "grand": g["totals"]["grand"],
                             "work_lines": len(g["work_rows"])} for g in groups],
            "grand_total": sum(g["totals"]["grand"] for g in groups),
            "has_data": bool(groups)}


@router.post("/api/reports/weekly/submit")
async def api_weekly_submit(request: Request, user: Employee = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """Build one PDF per contractor and upload each to its contractor folder."""
    _guard(db, user)
    b = await request.json()
    if b.get("end"):
        start, end = _week_from_end(b["end"])
    else:
        start, end = _week_window()
    groups = _weekly_by_contractor(db, start, end)
    if not groups:
        return {"ok": True, "uploaded": 0, "message": "Nothing recorded for this week."}
    label = _week_label(start, end)
    from ..services.project_pdf import build_weekly_contractor_pdf
    done, errors = 0, []
    for g in groups:
        try:
            pdf = build_weekly_contractor_pdf(g["name"], label, g["att_rows"],
                                              g["work_rows"], g["totals"])
            path = f"{WEEKLY_DIR}/{_safe(g['name'])}/{label}.pdf"
            _od.upload_to_path(pdf, path, "application/pdf")
            done += 1
        except Exception as e:
            log.error("[project-ops] weekly submit failed for %s: %s", g["name"], e, exc_info=True)
            errors.append(g["name"])
    msg = f"Uploaded {done} contractor report(s) to OneDrive."
    if errors:
        msg += " Failed: " + ", ".join(errors)
    return {"ok": True, "uploaded": done, "errors": errors, "message": msg}


@router.post("/api/reports/weekly/send-hr")
async def api_weekly_send_hr(request: Request, user: Employee = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    """One email to accounts (+CC) with every contractor's weekly PDF attached."""
    _guard(db, user)
    b = await request.json()
    if b.get("end"):
        start, end = _week_from_end(b["end"])
    else:
        start, end = _week_window()
    groups = _weekly_by_contractor(db, start, end)
    if not groups:
        return {"ok": True, "sent": False, "message": "Nothing recorded for this week."}
    label = _week_label(start, end)
    from ..services.project_pdf import build_weekly_contractor_pdf
    attachments = []
    for g in groups:
        try:
            pdf = build_weekly_contractor_pdf(g["name"], label, g["att_rows"],
                                              g["work_rows"], g["totals"])
            attachments.append((f"{_safe(g['name'])} — {label}.pdf", pdf, "application/pdf"))
        except Exception as e:
            log.error("[project-ops] weekly PDF build failed for %s: %s", g["name"], e, exc_info=True)
    if not attachments:
        return {"ok": False, "sent": False, "message": "Could not build any reports."}
    to, cc = _recipients(db)
    grand = sum(g["totals"]["grand"] for g in groups)
    subject = f"[Metfraa] Project Weekly Report — {label}"
    lines = "".join(
        f"<tr><td style='padding:3px 16px 3px 0'>{g['name']}</td>"
        f"<td style='text-align:right;font-weight:600'>INR {g['totals']['grand']:,.0f}</td></tr>"
        for g in groups)
    html = f"""<div style="font-family:Arial,sans-serif;color:#0d1421;max-width:600px">
      <div style="border-top:4px solid #1F7CCB;padding-top:14px">
        <div style="font-family:monospace;font-size:11px;letter-spacing:.15em;color:#6b7689;text-transform:uppercase">Metfraa · Project Operations</div>
        <h2 style="margin:6px 0 0;font-size:20px">Weekly Contractor Reports — {label}</h2>
      </div>
      <p style="font-size:14px;line-height:1.6">Weekly contractor reports are attached (one PDF per contractor).</p>
      <table style="font-size:13px;border-collapse:collapse;margin:14px 0">{lines}
        <tr><td style="padding:6px 16px 3px 0;border-top:1px solid #d6dde6">Grand total</td>
            <td style="text-align:right;font-weight:700;font-size:15px;border-top:1px solid #d6dde6;padding-top:6px">INR {grand:,.0f}</td></tr>
      </table>
      <p style="font-size:11px;color:#6b7689;font-family:monospace;letter-spacing:.05em;border-top:1px dashed #d6dde6;padding-top:12px">METFRAA · PROJECT OPERATIONS · AUTOMATED MESSAGE</p>
    </div>"""
    try:
        from ..services.email_service import send_email_async
        ok = await send_email_async(to, subject, html, cc=cc, attachments=attachments)
        if not ok:
            return {"ok": True, "sent": False, "message": "Send failed — check SMTP config."}
        return {"ok": True, "sent": True,
                "message": f"Sent {len(attachments)} report(s) to {to}."}
    except Exception as e:
        log.error("[project-ops] weekly HR mail failed: %s", e, exc_info=True)
        return {"ok": True, "sent": False, "message": f"Send failed: {e}"}
