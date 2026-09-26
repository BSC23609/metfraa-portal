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
from ..models import (Employee, ProjContractor, ProjContractorRate, ProjEquipment,
                      ProjPartMark, ProjSite, ProjWorkerType)

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
