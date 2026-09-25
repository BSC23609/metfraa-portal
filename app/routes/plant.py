"""Plant Operations — labour & contractor daily attendance.

First feature of the Plant Operations module in the Metfraa portal. Records:
  * own labour — named present/absent/half per day (P / A / H)
  * contractor teams — a split skilled+helper headcount per day (no names)

Admin masters manage the labour roster (name, designation, per-day salary) and
the contractor list (name, per-day rate). Salary/rate are stored now so the
payable report the user will build later needs no schema change.
"""
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_current_user
from ..models import (Employee, PlantContractor, PlantContractorAttendance,
                      PlantContractorWorkLog, PlantJob, PlantLabour, PlantLabourAttendance,
                      PlantLabourWorkLog)
from ..services import onedrive as _od

PLANT_ROOT = "Plant Operation/Attendance and Work Log"
DAILY_DIR = PLANT_ROOT + "/DAILY REPORT"
MONTHLY_DIR = PLANT_ROOT + "/MONTHLY REPORT"

router = APIRouter(prefix="/plant", tags=["plant"])
log = logging.getLogger("plant")
templates = Jinja2Templates(directory="app/templates")

VALID = {"P", "A", "H"}


def _ot_hours(v):
    """Snap OT hours to the nearest 0.5, non-negative."""
    try:
        h = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(h * 2) / 2 if h > 0 else 0.0


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
    lwh = {l.id: l.working_hours for l in labour}
    return {
        "date": d.isoformat(),
        "labour": [{"id": l.id, "name": l.name, "designation": l.designation or "",
                    "status": lmarks.get(l.id, "P"),
                    "half_part": (lrec[l.id].half_part if l.id in lrec else None),
                    "per_day_salary": l.per_day_salary, "working_hours": l.working_hours,
                    "ot_category": l.ot_category, "ot_flat_rate": l.ot_flat_rate,
                    "ot": bool(lrec[l.id].ot) if l.id in lrec else False,
                    "ot_hours": (lrec[l.id].ot_hours if l.id in lrec else 0)}
                   for l in labour],
        "contractors": [{"id": c.id, "name": c.name,
                         "per_day_rate": c.per_day_rate, "working_hours": c.working_hours,
                         "skilled": cmarks[c.id].skilled if c.id in cmarks else 0,
                         "helper": cmarks[c.id].helper if c.id in cmarks else 0,
                         "ot": bool(cmarks[c.id].ot) if c.id in cmarks else False,
                         "ot_persons": cmarks[c.id].ot_persons if c.id in cmarks else 0,
                         "ot_hours": (cmarks[c.id].ot_hours if c.id in cmarks else 0)}
                        for c in contractors],
        "jobs": [{"id": j.id, "code": j.job_code or "", "name": j.name}
                 for j in db.query(PlantJob).filter(PlantJob.active == True)  # noqa: E712
                 .order_by(PlantJob.id).all()],
        "labour_worklog": [{"job_id": w.job_id, "nature_of_work": w.nature_of_work or "",
                            "skilled": w.skilled, "helper": w.helper,
                            "qty_nos": w.qty_nos, "weight_kg": w.weight_kg,
                            "remarks": w.remarks or ""}
                           for w in db.query(PlantLabourWorkLog)
                           .filter(PlantLabourWorkLog.log_date == d)
                           .order_by(PlantLabourWorkLog.seq, PlantLabourWorkLog.id).all()],
        "contractor_worklog": [{"contractor_id": w.contractor_id, "job_id": w.job_id,
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
    return _save_day(db, b, user)


def _save_day(db: Session, b: dict, user: Employee) -> dict:
    d = _parse_date(b.get("date"))
    now = datetime.utcnow()

    valid_labour = {row[0] for row in db.query(PlantLabour.id).all()}
    valid_contr = {row[0] for row in db.query(PlantContractor.id).all()}
    valid_jobs = {row[0] for row in db.query(PlantJob.id).all()}

    lmap = {l.id: l for l in db.query(PlantLabour).all()}
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
        oth = _ot_hours(row.get("ot_hours")) if ot else 0.0
        lab = lmap.get(lid)
        if lab and lab.ot_category == "flat":
            rate = lab.ot_flat_rate or 100          # ₹/hour, flat
        else:
            wh = (lab.working_hours or 8) if lab else 8
            rate = (lab.per_day_salary or 0) / wh if (lab and wh) else 0
        amt = round(rate * oth, 2)
        rec = (db.query(PlantLabourAttendance)
               .filter(PlantLabourAttendance.labour_id == lid,
                       PlantLabourAttendance.att_date == d).first())
        if rec:
            rec.status = st
            rec.half_part = half_part
            rec.ot, rec.ot_hours, rec.ot_amount = ot, oth, amt
            rec.marked_by = user.employee_code
            rec.updated_at = now
        else:
            db.add(PlantLabourAttendance(labour_id=lid, att_date=d, status=st,
                                         half_part=half_part, ot=ot, ot_hours=oth,
                                         ot_amount=amt, marked_by=user.employee_code))

    def _int(v):
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0

    cmap = {c.id: c for c in db.query(PlantContractor).all()}
    for row in (b.get("contractors") or []):
        cid = row.get("id")
        if cid not in valid_contr:
            continue
        sk, hp = _int(row.get("skilled")), _int(row.get("helper"))
        ot = bool(row.get("ot"))
        ot_persons = _int(row.get("ot_persons")) if ot else 0
        oth = _ot_hours(row.get("ot_hours")) if ot else 0.0
        c_ = cmap.get(cid)
        wh = (c_.working_hours or 8) if c_ else 8
        rate = (c_.per_day_rate or 0) / wh if (c_ and wh) else 0
        camt = round(ot_persons * rate * oth, 2)
        rec = (db.query(PlantContractorAttendance)
               .filter(PlantContractorAttendance.contractor_id == cid,
                       PlantContractorAttendance.att_date == d).first())
        if rec:
            rec.skilled, rec.helper = sk, hp
            rec.ot, rec.ot_persons, rec.ot_hours, rec.ot_amount = ot, ot_persons, oth, camt
            rec.marked_by = user.employee_code
            rec.updated_at = now
        elif sk or hp or ot:
            db.add(PlantContractorAttendance(contractor_id=cid, att_date=d,
                                             skilled=sk, helper=hp, ot=ot,
                                             ot_persons=ot_persons, ot_hours=oth,
                                             ot_amount=camt, marked_by=user.employee_code))

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
                log_date=d, job_id=(w.get("job_id") if w.get("job_id") in valid_jobs else None),
                nature_of_work=(w.get("nature_of_work") or "").strip() or None,
                skilled=_int(w.get("skilled")), helper=_int(w.get("helper")),
                qty_nos=_fnum(w.get("qty_nos")), weight_kg=_fnum(w.get("weight_kg")),
                remarks=(w.get("remarks") or "").strip() or None, seq=i,
                marked_by=user.employee_code)
            # skip wholly-empty rows
            if (now_row.job_id or now_row.nature_of_work or now_row.skilled or now_row.helper
                    or now_row.qty_nos or now_row.weight_kg or now_row.remarks):
                db.add(now_row)

    if "contractor_worklog" in b:
        db.query(PlantContractorWorkLog).filter(PlantContractorWorkLog.log_date == d).delete()
        for i, w in enumerate(b.get("contractor_worklog") or []):
            cid = w.get("contractor_id")
            cid = cid if cid in valid_contr else None
            row = PlantContractorWorkLog(
                log_date=d, contractor_id=cid, job_id=(w.get("job_id") if w.get("job_id") in valid_jobs else None),
                nature_of_work=(w.get("nature_of_work") or "").strip() or None,
                workers=_int(w.get("workers")),
                qty_nos=_fnum(w.get("qty_nos")), weight_kg=_fnum(w.get("weight_kg")),
                remarks=(w.get("remarks") or "").strip() or None, seq=i,
                marked_by=user.employee_code)
            if (row.contractor_id or row.job_id or row.nature_of_work or row.workers
                    or row.qty_nos or row.weight_kg or row.remarks):
                db.add(row)

    db.commit()
    return {"ok": True, "date": d.isoformat()}


def _gather_day(db: Session, d):
    """Assemble the daily report data (resolved names, computed summary)."""
    lmap = {l.id: l for l in db.query(PlantLabour).all()}
    la = (db.query(PlantLabourAttendance)
          .filter(PlantLabourAttendance.att_date == d)
          .order_by(PlantLabourAttendance.labour_id).all())
    labour = [{"name": lmap[a.labour_id].name if a.labour_id in lmap else "—",
               "designation": (lmap[a.labour_id].designation or "") if a.labour_id in lmap else "",
               "status": a.status, "half_part": a.half_part, "ot": bool(a.ot),
               "ot_hours": a.ot_hours, "ot_amount": a.ot_amount} for a in la]
    cmap = {c.id: c for c in db.query(PlantContractor).all()}
    ca = (db.query(PlantContractorAttendance)
          .filter(PlantContractorAttendance.att_date == d)
          .order_by(PlantContractorAttendance.contractor_id).all())
    contractors = [{"name": cmap[a.contractor_id].name if a.contractor_id in cmap else "—",
                    "skilled": a.skilled, "helper": a.helper, "ot": bool(a.ot),
                    "ot_persons": a.ot_persons, "ot_hours": a.ot_hours,
                    "ot_amount": a.ot_amount} for a in ca]
    jmap = {j.id: (f"{j.job_code} · {j.name}" if j.job_code else j.name)
            for j in db.query(PlantJob).all()}
    lwl = [{"job": jmap.get(w.job_id, ""), "nature_of_work": w.nature_of_work or "",
            "skilled": w.skilled, "helper": w.helper, "qty_nos": w.qty_nos,
            "weight_kg": w.weight_kg, "remarks": w.remarks or ""}
           for w in db.query(PlantLabourWorkLog)
           .filter(PlantLabourWorkLog.log_date == d)
           .order_by(PlantLabourWorkLog.seq, PlantLabourWorkLog.id).all()]
    cwl = [{"contractor": cmap[w.contractor_id].name if w.contractor_id in cmap else "—",
            "job": jmap.get(w.job_id, ""),
            "nature_of_work": w.nature_of_work or "", "workers": w.workers,
            "qty_nos": w.qty_nos, "weight_kg": w.weight_kg, "remarks": w.remarks or ""}
           for w in db.query(PlantContractorWorkLog)
           .filter(PlantContractorWorkLog.log_date == d)
           .order_by(PlantContractorWorkLog.seq, PlantContractorWorkLog.id).all()]
    summary = {"present": sum(1 for a in la if a.status == "P"),
               "half": sum(1 for a in la if a.status == "H"),
               "absent": sum(1 for a in la if a.status == "A"),
               "ot_amount": sum(a.ot_amount for a in la) + sum(a.ot_amount for a in ca)}
    return labour, contractors, lwl, cwl, summary, bool(la or ca or lwl or cwl)


@router.post("/api/day/submit")
async def api_submit_day(request: Request, user: Employee = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Save the day then render its PDF and upload to OneDrive under
    DAILY REPORT/YYYY-MM/YYYY-MM-DD.pdf."""
    _guard(db, user)
    b = await request.json()
    save_res = _save_day(db, b, user)   # commits the day
    d = _parse_date(save_res["date"])

    labour, contractors, lwl, cwl, summary, has_data = _gather_day(db, d)
    if not has_data:
        return {"ok": True, "date": d.isoformat(), "uploaded": False,
                "message": "Saved. Nothing to submit — the day is empty."}
    try:
        from ..services.plant_pdf import build_daily_pdf
        pdf = build_daily_pdf(d, labour, contractors, lwl, cwl, summary)
        path = f"{DAILY_DIR}/{d.strftime('%Y-%m')}/{d.isoformat()}.pdf"
        info = _od.upload_to_path(pdf, path, "application/pdf")
        url = (info or {}).get("webUrl")
        return {"ok": True, "date": d.isoformat(), "uploaded": True,
                "url": url, "message": "Saved and submitted to OneDrive."}
    except Exception as e:
        log.error("[plant] daily submit failed for %s: %s", d, e, exc_info=True)
        return {"ok": True, "date": d.isoformat(), "uploaded": False,
                "message": f"Saved, but the OneDrive upload failed: {e}"}


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
                        "per_day_salary": l.per_day_salary,
                        "working_hours": l.working_hours,
                        "ot_category": l.ot_category, "ot_flat_rate": l.ot_flat_rate,
                        "active": l.active}
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

    def _wh_l(v):
        try:
            h = float(v) if v not in (None, "") else 8.0
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid working hours")
        return h if h > 0 else 8.0

    def _flat_l(v):
        try:
            r = float(v) if v not in (None, "") else 100.0
        except (TypeError, ValueError):
            return 100.0
        return r if r > 0 else 100.0

    lid = b.get("id")
    if lid:
        l = db.query(PlantLabour).filter(PlantLabour.id == lid).first()
        if not l:
            raise HTTPException(status_code=404, detail="Labour not found")
        l.name = name
        l.designation = (b.get("designation") or "").strip() or None
        l.per_day_salary = _sal(b.get("per_day_salary"))
        l.working_hours = _wh_l(b.get("working_hours"))
        l.ot_category = "flat" if (b.get("ot_category") == "flat") else "salary"
        l.ot_flat_rate = _flat_l(b.get("ot_flat_rate"))
        if "active" in b:
            l.active = bool(b["active"])
    else:
        db.add(PlantLabour(name=name,
                           designation=(b.get("designation") or "").strip() or None,
                           per_day_salary=_sal(b.get("per_day_salary")),
                           working_hours=_wh_l(b.get("working_hours")),
                           ot_category=("flat" if b.get("ot_category") == "flat" else "salary"),
                           ot_flat_rate=_flat_l(b.get("ot_flat_rate")),
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
                             "working_hours": c.working_hours,
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

    def _wh(v):
        try:
            h = float(v) if v not in (None, "") else 8.0
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid working hours")
        return h if h > 0 else 8.0
    wh = _wh(b.get("working_hours"))
    cid = b.get("id")
    if cid:
        c = db.query(PlantContractor).filter(PlantContractor.id == cid).first()
        if not c:
            raise HTTPException(status_code=404, detail="Contractor not found")
        c.name = name
        c.per_day_rate = _rate(b.get("per_day_rate"))
        c.working_hours = wh
        if "active" in b:
            c.active = bool(b["active"])
    else:
        db.add(PlantContractor(name=name, per_day_rate=_rate(b.get("per_day_rate")),
                               working_hours=wh,
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


# --------------------------------------------------------------- job master

@router.get("/api/jobs")
def api_jobs_list(include_inactive: str | None = None,
                  user: Employee = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    _guard(db, user)
    q = db.query(PlantJob)
    if str(include_inactive or "").lower() not in ("1", "true", "yes"):
        q = q.filter(PlantJob.active == True)  # noqa: E712
    rows = q.order_by(PlantJob.active.desc(), PlantJob.id).all()
    return {"jobs": [{"id": j.id, "job_code": j.job_code or "", "name": j.name,
                      "active": j.active} for j in rows]}


@router.post("/api/jobs")
async def api_jobs_save(request: Request, user: Employee = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    _guard(db, user)
    b = await request.json()
    name = (b.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Job name is required")
    code = (b.get("job_code") or "").strip() or None
    jid = b.get("id")
    if jid:
        j = db.query(PlantJob).filter(PlantJob.id == jid).first()
        if not j:
            raise HTTPException(status_code=404, detail="Job not found")
        j.name = name
        j.job_code = code
        if "active" in b:
            j.active = bool(b["active"])
    else:
        db.add(PlantJob(name=name, job_code=code, active=bool(b.get("active", True))))
    db.commit()
    return {"ok": True}


@router.delete("/api/jobs/{jid}")
def api_jobs_delete(jid: int, user: Employee = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Soft-delete: a job used on any work-log line is deactivated (history
    preserved); an unused job is removed outright."""
    _guard(db, user)
    j = db.query(PlantJob).filter(PlantJob.id == jid).first()
    if not j:
        raise HTTPException(status_code=404, detail="Not found")
    used = (db.query(PlantLabourWorkLog).filter(PlantLabourWorkLog.job_id == jid).first()
            or db.query(PlantContractorWorkLog).filter(PlantContractorWorkLog.job_id == jid).first())
    if used:
        j.active = False
        db.commit()
        return {"ok": True, "deactivated": True}
    db.delete(j)
    db.commit()
    return {"ok": True, "deleted": True}


# --------------------------------------------------------------- browse

@router.get("/api/browse/day")
def api_browse_day(date: str | None = None,
                   user: Employee = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Read-only view of one day: attendance (labour + contractors) and both
    work logs, with names resolved and OT/half shown."""
    _guard(db, user)
    d = _parse_date(date)

    lmap = {l.id: l for l in db.query(PlantLabour).all()}
    la = (db.query(PlantLabourAttendance)
          .filter(PlantLabourAttendance.att_date == d)
          .order_by(PlantLabourAttendance.labour_id).all())
    labour = [{"name": lmap[a.labour_id].name if a.labour_id in lmap else "—",
               "designation": (lmap[a.labour_id].designation or "") if a.labour_id in lmap else "",
               "status": a.status, "half_part": a.half_part,
               "ot": bool(a.ot), "ot_hours": a.ot_hours, "ot_amount": a.ot_amount}
              for a in la]

    cmap = {c.id: c for c in db.query(PlantContractor).all()}
    ca = (db.query(PlantContractorAttendance)
          .filter(PlantContractorAttendance.att_date == d)
          .order_by(PlantContractorAttendance.contractor_id).all())
    contractors = [{"name": cmap[a.contractor_id].name if a.contractor_id in cmap else "—",
                    "skilled": a.skilled, "helper": a.helper,
                    "ot": bool(a.ot), "ot_persons": a.ot_persons,
                    "ot_hours": a.ot_hours, "ot_amount": a.ot_amount}
                   for a in ca]

    jmap = {j.id: (f"{j.job_code} · {j.name}" if j.job_code else j.name)
            for j in db.query(PlantJob).all()}
    lwl = [{"job": jmap.get(w.job_id, ""), "nature_of_work": w.nature_of_work or "",
            "skilled": w.skilled, "helper": w.helper, "qty_nos": w.qty_nos,
            "weight_kg": w.weight_kg, "remarks": w.remarks or ""}
           for w in db.query(PlantLabourWorkLog)
           .filter(PlantLabourWorkLog.log_date == d)
           .order_by(PlantLabourWorkLog.seq, PlantLabourWorkLog.id).all()]
    cwl = [{"contractor": cmap[w.contractor_id].name if w.contractor_id in cmap else "—",
            "job": jmap.get(w.job_id, ""),
            "nature_of_work": w.nature_of_work or "", "workers": w.workers,
            "qty_nos": w.qty_nos, "weight_kg": w.weight_kg, "remarks": w.remarks or ""}
           for w in db.query(PlantContractorWorkLog)
           .filter(PlantContractorWorkLog.log_date == d)
           .order_by(PlantContractorWorkLog.seq, PlantContractorWorkLog.id).all()]

    present = sum(1 for a in la if a.status == "P")
    half = sum(1 for a in la if a.status == "H")
    absent = sum(1 for a in la if a.status == "A")
    ot_total = sum(a.ot_amount for a in la) + sum(a.ot_amount for a in ca)
    contr_head = sum(a.skilled + a.helper for a in ca)

    return {
        "date": d.isoformat(),
        "summary": {"present": present, "half": half, "absent": absent,
                    "contractor_headcount": contr_head, "ot_amount": ot_total,
                    "has_data": bool(la or ca or lwl or cwl)},
        "labour": labour, "contractors": contractors,
        "labour_worklog": lwl, "contractor_worklog": cwl,
    }


@router.get("/api/browse/range")
def api_browse_range(start: str | None = None, end: str | None = None,
                     user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """A per-day roll-up across a date range: attendance counts, contractor
    headcount, and total qty/weight of work done. Newest day first."""
    _guard(db, user)
    e = _parse_date(end)
    s_ = _parse_date(start)
    if s_ > e:
        s_, e = e, s_

    from collections import defaultdict
    days = defaultdict(lambda: {"present": 0, "half": 0, "absent": 0,
                                "contractor_headcount": 0, "qty_nos": 0.0,
                                "weight_kg": 0.0, "work_lines": 0})

    for a in (db.query(PlantLabourAttendance)
              .filter(PlantLabourAttendance.att_date >= s_,
                      PlantLabourAttendance.att_date <= e).all()):
        k = a.att_date.isoformat()
        if a.status == "P": days[k]["present"] += 1
        elif a.status == "H": days[k]["half"] += 1
        elif a.status == "A": days[k]["absent"] += 1

    for a in (db.query(PlantContractorAttendance)
              .filter(PlantContractorAttendance.att_date >= s_,
                      PlantContractorAttendance.att_date <= e).all()):
        days[a.att_date.isoformat()]["contractor_headcount"] += a.skilled + a.helper

    for w in (db.query(PlantLabourWorkLog)
              .filter(PlantLabourWorkLog.log_date >= s_,
                      PlantLabourWorkLog.log_date <= e).all()):
        k = w.log_date.isoformat()
        days[k]["qty_nos"] += w.qty_nos or 0
        days[k]["weight_kg"] += w.weight_kg or 0
        days[k]["work_lines"] += 1
    for w in (db.query(PlantContractorWorkLog)
              .filter(PlantContractorWorkLog.log_date >= s_,
                      PlantContractorWorkLog.log_date <= e).all()):
        k = w.log_date.isoformat()
        days[k]["qty_nos"] += w.qty_nos or 0
        days[k]["weight_kg"] += w.weight_kg or 0
        days[k]["work_lines"] += 1

    rows = [{"date": k, **v} for k, v in days.items()]
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {"start": s_.isoformat(), "end": e.isoformat(), "days": rows}



# --------------------------------------------------------------- dashboard

@router.get("/api/dashboard")
def api_dashboard(start: str | None = None, end: str | None = None,
                  user: Employee = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Aggregates for the dashboard over a date range:
      * daily attendance trend (present/half/absent + contractor headcount)
      * qty & weight produced per day (own team + contractors combined)
      * qty & weight totals per contractor team (own team shown as 'Own team')
      * headline totals for the range."""
    _guard(db, user)
    e = _parse_date(end)
    s_ = _parse_date(start)
    if s_ > e:
        s_, e = e, s_

    from collections import defaultdict
    trend = defaultdict(lambda: {"present": 0, "half": 0, "absent": 0,
                                 "contractor": 0, "qty": 0.0, "weight": 0.0})

    for a in (db.query(PlantLabourAttendance)
              .filter(PlantLabourAttendance.att_date >= s_,
                      PlantLabourAttendance.att_date <= e).all()):
        k = a.att_date.isoformat()
        if a.status == "P": trend[k]["present"] += 1
        elif a.status == "H": trend[k]["half"] += 1
        elif a.status == "A": trend[k]["absent"] += 1
    for a in (db.query(PlantContractorAttendance)
              .filter(PlantContractorAttendance.att_date >= s_,
                      PlantContractorAttendance.att_date <= e).all()):
        trend[a.att_date.isoformat()]["contractor"] += a.skilled + a.helper

    cmap = {c.id: c.name for c in db.query(PlantContractor).all()}
    per_team = defaultdict(lambda: {"qty": 0.0, "weight": 0.0})

    for w in (db.query(PlantLabourWorkLog)
              .filter(PlantLabourWorkLog.log_date >= s_,
                      PlantLabourWorkLog.log_date <= e).all()):
        k = w.log_date.isoformat()
        trend[k]["qty"] += w.qty_nos or 0
        trend[k]["weight"] += w.weight_kg or 0
        per_team["Own team"]["qty"] += w.qty_nos or 0
        per_team["Own team"]["weight"] += w.weight_kg or 0
    for w in (db.query(PlantContractorWorkLog)
              .filter(PlantContractorWorkLog.log_date >= s_,
                      PlantContractorWorkLog.log_date <= e).all()):
        k = w.log_date.isoformat()
        trend[k]["qty"] += w.qty_nos or 0
        trend[k]["weight"] += w.weight_kg or 0
        name = cmap.get(w.contractor_id, "Unassigned")
        per_team[name]["qty"] += w.qty_nos or 0
        per_team[name]["weight"] += w.weight_kg or 0

    # fill every calendar day in range so the trend line has no gaps
    from datetime import timedelta
    days = []
    cur = s_
    while cur <= e:
        k = cur.isoformat()
        t = trend.get(k, {"present": 0, "half": 0, "absent": 0,
                          "contractor": 0, "qty": 0.0, "weight": 0.0})
        days.append({"date": k, **t})
        cur += timedelta(days=1)

    teams = sorted(({"team": n, "qty": round(v["qty"], 2),
                     "weight": round(v["weight"], 2)}
                    for n, v in per_team.items()),
                   key=lambda r: r["weight"], reverse=True)

    totals = {
        "present": sum(d["present"] for d in days),
        "half": sum(d["half"] for d in days),
        "absent": sum(d["absent"] for d in days),
        "contractor_mandays": sum(d["contractor"] for d in days),
        "qty": round(sum(d["qty"] for d in days), 2),
        "weight": round(sum(d["weight"] for d in days), 2),
    }
    return {"start": s_.isoformat(), "end": e.isoformat(),
            "days": days, "teams": teams, "totals": totals}


# --------------------------------------------------------------- monthly

def _prev_month(today=None):
    from datetime import date as _d
    t = today or _d.today()
    y, m = (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)
    return y, m


def _build_monthly(db: Session, year: int, month: int):
    """Compute the monthly payroll + work figures from stored data.
    Money: labour amount = present-day-equivalent (H=0.5) * per_day_salary + OT;
    contractor total = man-days * per_day_rate + OT."""
    import calendar
    from datetime import date as _d
    ndays = calendar.monthrange(year, month)[1]
    start, end = _d(year, month, 1), _d(year, month, ndays)

    # --- company (own labour) ---
    lmap = {l.id: l for l in db.query(PlantLabour).all()}
    la = (db.query(PlantLabourAttendance)
          .filter(PlantLabourAttendance.att_date >= start,
                  PlantLabourAttendance.att_date <= end).all())
    per = {}   # labour_id -> {grid, present_equiv, ot_hours, ot_amount}
    for a in la:
        rec = per.setdefault(a.labour_id, {"grid": {}, "present_equiv": 0.0,
                                           "ot_hours": 0, "ot_amount": 0.0})
        rec["grid"][a.att_date.day] = a.status
        if a.status == "P":
            rec["present_equiv"] += 1
        elif a.status == "H":
            rec["present_equiv"] += 0.5
        rec["ot_hours"] += a.ot_hours
        rec["ot_amount"] += a.ot_amount
    rows = []
    tot = {"workers": 0, "present_days": 0.0, "ot_hours": 0, "ot_amount": 0.0,
           "salary": 0.0, "grand": 0.0}
    for lid, rec in sorted(per.items(), key=lambda kv: lmap[kv[0]].name if kv[0] in lmap else ""):
        l = lmap.get(lid)
        if not l:
            continue
        salary = rec["present_equiv"] * (l.per_day_salary or 0)
        grand = salary + rec["ot_amount"]
        rows.append({"name": l.name, "grid": rec["grid"],
                     "days": rec["present_equiv"], "amount": salary,
                     "ot_hours": rec["ot_hours"], "ot_amount": rec["ot_amount"]})
        tot["workers"] += 1
        tot["present_days"] += rec["present_equiv"]
        tot["ot_hours"] += rec["ot_hours"]
        tot["ot_amount"] += rec["ot_amount"]
        tot["salary"] += salary
        tot["grand"] += grand
    company = {"rows": rows, "totals": tot}

    # --- contractors (one sheet each, skip those with no activity) ---
    cmap = {c.id: c for c in db.query(PlantContractor).all()}
    ca = (db.query(PlantContractorAttendance)
          .filter(PlantContractorAttendance.att_date >= start,
                  PlantContractorAttendance.att_date <= end)
          .order_by(PlantContractorAttendance.att_date).all())
    by_c = {}
    for a in ca:
        by_c.setdefault(a.contractor_id, []).append(a)
    contractors = []
    for cid, recs in by_c.items():
        c = cmap.get(cid)
        if not c:
            continue
        crows, mandays, ot_amt = [], 0, 0.0
        for a in sorted(recs, key=lambda r: r.att_date):
            total = a.skilled + a.helper
            mandays += total
            ot_amt += a.ot_amount
            crows.append({"date": a.att_date.strftime("%d %b %Y"),
                          "skilled": a.skilled, "helper": a.helper, "total": total,
                          "ot_persons": a.ot_persons if a.ot else 0,
                          "ot_amount": a.ot_amount})
        base = mandays * (c.per_day_rate or 0)
        contractors.append({"name": c.name, "rows": crows,
                            "totals": {"mandays": mandays, "base": base,
                                       "ot_amount": ot_amt, "grand": base + ot_amt}})
    contractors.sort(key=lambda x: x["name"])

    # --- team-wise work summary ---
    from collections import defaultdict
    ts = defaultdict(lambda: {"work_lines": 0, "qty": 0.0, "weight": 0.0})
    for w in (db.query(PlantLabourWorkLog)
              .filter(PlantLabourWorkLog.log_date >= start,
                      PlantLabourWorkLog.log_date <= end).all()):
        ts["Own team"]["work_lines"] += 1
        ts["Own team"]["qty"] += w.qty_nos or 0
        ts["Own team"]["weight"] += w.weight_kg or 0
    for w in (db.query(PlantContractorWorkLog)
              .filter(PlantContractorWorkLog.log_date >= start,
                      PlantContractorWorkLog.log_date <= end).all()):
        name = cmap[w.contractor_id].name if w.contractor_id in cmap else "Unassigned"
        ts[name]["work_lines"] += 1
        ts[name]["qty"] += w.qty_nos or 0
        ts[name]["weight"] += w.weight_kg or 0
    work_summary = sorted(({"team": n, **v} for n, v in ts.items()),
                          key=lambda r: r["weight"], reverse=True)
    total_weight = sum(w["weight"] for w in work_summary)

    has_data = bool(rows or contractors or work_summary)
    return company, contractors, work_summary, total_weight, has_data


@router.get("/api/monthly")
def api_monthly_preview(period: str | None = None,
                        user: Employee = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Headline figures for the monthly screen (no PDF). period=YYYY-MM;
    defaults to the previous month."""
    _guard(db, user)
    if period:
        try:
            year, month = (int(x) for x in period.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="period must be YYYY-MM")
    else:
        year, month = _prev_month()
    company, contractors, work_summary, total_weight, has_data = _build_monthly(db, year, month)
    return {
        "period": f"{year:04d}-{month:02d}",
        "default_period": f"{_prev_month()[0]:04d}-{_prev_month()[1]:02d}",
        "has_data": has_data,
        "company_total": company["totals"]["grand"],
        "company_workers": company["totals"]["workers"],
        "contractor_count": len(contractors),
        "contractor_total": sum(c["totals"]["grand"] for c in contractors),
        "total_weight": total_weight,
    }


@router.post("/api/monthly/submit")
async def api_monthly_submit(request: Request,
                             user: Employee = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    """Render the monthly PDF and upload to MONTHLY REPORT/<YYYY-MM> Plant Report.pdf."""
    _guard(db, user)
    b = await request.json()
    period = b.get("period")
    if period:
        try:
            year, month = (int(x) for x in period.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="period must be YYYY-MM")
    else:
        year, month = _prev_month()
    company, contractors, work_summary, total_weight, has_data = _build_monthly(db, year, month)
    if not has_data:
        return {"ok": True, "uploaded": False,
                "message": "Nothing recorded for this month — nothing to submit."}
    try:
        from ..services.plant_pdf import build_monthly_pdf
        pdf = build_monthly_pdf(year, month, company, contractors, work_summary, total_weight)
        path = f"{MONTHLY_DIR}/{year:04d}-{month:02d} Plant Report.pdf"
        info = _od.upload_to_path(pdf, path, "application/pdf")
        return {"ok": True, "uploaded": True, "url": (info or {}).get("webUrl"),
                "message": "Monthly report submitted to OneDrive."}
    except Exception as e:
        log.error("[plant] monthly submit failed for %s-%s: %s", year, month, e, exc_info=True)
        return {"ok": True, "uploaded": False,
                "message": f"The OneDrive upload failed: {e}"}


PLANT_HR_TO = "admin@metfraa.com"
PLANT_HR_CC = ["gopi@metfraa.com", "thangaraj@metfraa.com",
               "arasu@metfraa.com", "info@metfraa.com"]


@router.post("/api/monthly/send-hr")
async def api_monthly_send_hr(request: Request,
                             user: Employee = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    """Render the monthly PDF and email it to HR (admin@) with CC to the
    management group."""
    _guard(db, user)
    b = await request.json()
    period = b.get("period")
    if period:
        try:
            year, month = (int(x) for x in period.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="period must be YYYY-MM")
    else:
        year, month = _prev_month()
    company, contractors, work_summary, total_weight, has_data = _build_monthly(db, year, month)
    if not has_data:
        return {"ok": True, "sent": False,
                "message": "Nothing recorded for this month — nothing to send."}
    try:
        from ..services.plant_pdf import build_monthly_pdf
        pdf = build_monthly_pdf(year, month, company, contractors, work_summary, total_weight)
    except Exception as e:
        log.error("[plant] monthly PDF build failed for HR mail: %s", e, exc_info=True)
        return {"ok": False, "sent": False, "message": f"Could not build the report: {e}"}

    from datetime import datetime as _dt
    mlabel = _dt(year, month, 1).strftime("%B %Y")
    grand = company["totals"]["grand"] + sum(c["totals"]["grand"] for c in contractors)
    subject = f"[Metfraa] Plant Attendance & Work Report — {mlabel}"
    html = f"""<div style="font-family:Arial,sans-serif;color:#0d1421;max-width:600px">
      <div style="border-top:4px solid #1F7CCB;padding-top:14px">
        <div style="font-family:monospace;font-size:11px;letter-spacing:.15em;color:#6b7689;text-transform:uppercase">Metfraa · Plant Operations</div>
        <h2 style="margin:6px 0 0;font-size:20px">Monthly Plant Report — {mlabel}</h2>
      </div>
      <p style="font-size:14px;line-height:1.6">The consolidated plant attendance and work report for
      <b>{mlabel}</b> is attached.</p>
      <table style="font-size:13px;border-collapse:collapse;margin:16px 0">
        <tr><td style="color:#6b7689;padding:3px 16px 3px 0">Company payable</td><td style="font-weight:700">INR {company['totals']['grand']:,.0f}</td></tr>
        <tr><td style="color:#6b7689;padding:3px 16px 3px 0">Contractor payable</td><td style="font-weight:700">INR {sum(c['totals']['grand'] for c in contractors):,.0f}</td></tr>
        <tr><td style="color:#6b7689;padding:3px 16px 3px 0">Total weight produced</td><td style="font-weight:700">{total_weight:,.2f} Kg</td></tr>
        <tr><td style="color:#6b7689;padding:6px 16px 3px 0;border-top:1px solid #d6dde6">Grand total</td><td style="font-weight:700;font-size:15px;border-top:1px solid #d6dde6;padding-top:6px">INR {grand:,.0f}</td></tr>
      </table>
      <p style="font-size:11px;color:#6b7689;font-family:monospace;letter-spacing:.05em;border-top:1px dashed #d6dde6;padding-top:12px">
        METFRAA · PLANT OPERATIONS · AUTOMATED MESSAGE</p>
    </div>"""
    fname = f"{year:04d}-{month:02d} Plant Report.pdf"
    try:
        from ..services.email_service import send_email_async
        ok = await send_email_async(
            PLANT_HR_TO, subject, html, cc=PLANT_HR_CC,
            attachments=[(fname, pdf, "application/pdf")])
        if not ok:
            return {"ok": True, "sent": False,
                    "message": "Send failed — check SMTP configuration."}
        return {"ok": True, "sent": True,
                "message": f"Sent to {PLANT_HR_TO} (CC: {', '.join(PLANT_HR_CC)})."}
    except Exception as e:
        log.error("[plant] monthly HR mail failed: %s", e, exc_info=True)
        return {"ok": True, "sent": False, "message": f"Send failed: {e}"}

