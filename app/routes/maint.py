"""Maintenance (CMMS) module — asset master, events, readings, PM.

First screen: the asset master (the machines seeded from the equipment list).
Breakdown/PM logging, readings, PM scheduling, reports and dashboard follow in
later slices. Access is gated by the maint_admin flag (superadmin implies it).
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_current_user
from ..models import Employee, MaintAsset, MaintMachineType, PlantLabour

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
