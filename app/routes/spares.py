"""Spare Parts Inventory module — machine spare parts register.

Mirrors the group's Spare Parts Inventory workbook. Current stock, stock value
and reorder status are derived (never stored) so they can't drift:
    current_stock = opening_qty + qty_in - qty_out
    stock_value   = current_stock * unit_price
    reorder       = current_stock <= min_stock_level  -> "REORDER NOW" else "OK"

Access is gated by the same maint_admin flag as the Maintenance module.
"""
import csv
import io
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_current_user
from ..models import Employee, MaintSparePart

router = APIRouter(prefix="/spares", tags=["spares"])
log = logging.getLogger("spares")
templates = Jinja2Templates(directory="app/templates")


def _guard(db: Session, user: Employee):
    if not get_access(db, user).can_admin_maint:
        raise HTTPException(status_code=403, detail="Spare parts access only")


def _iso(d):
    return d.isoformat() if d else None


def _pdate(s):
    if not s:
        return None
    if isinstance(s, date):
        return s
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _fnum(v, default=0.0):
    if v in (None, ""):
        return default
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _json(p: MaintSparePart) -> dict:
    current = (p.opening_qty or 0) + (p.qty_in or 0) - (p.qty_out or 0)
    value = current * (p.unit_price or 0)
    reorder = "REORDER NOW" if current <= (p.min_stock_level or 0) else "OK"
    return {
        "id": p.id,
        "part_code": p.part_code,
        "part_name": p.part_name,
        "machine": p.machine,
        "manufacturer": p.manufacturer,
        "unit": p.unit,
        "opening_qty": round(p.opening_qty or 0, 3),
        "qty_in": round(p.qty_in or 0, 3),
        "qty_out": round(p.qty_out or 0, 3),
        "current_stock": round(current, 3),
        "min_stock_level": round(p.min_stock_level or 0, 3),
        "reorder_status": reorder,
        "unit_price": round(p.unit_price or 0, 2),
        "stock_value": round(value, 2),
        "supplier": p.supplier,
        "last_purchase_date": _iso(p.last_purchase_date),
    }


# -------------------------------------------------------------------- page
@router.get("/", response_class=HTMLResponse)
def page(request: Request, user: Employee = Depends(get_current_user),
         db: Session = Depends(get_db)):
    _guard(db, user)
    return templates.TemplateResponse(request, "spares.html", {"user": user})


# -------------------------------------------------------------------- list
@router.get("/api/list")
def api_list(q: str | None = None, reorder: int = 0,
             user: Employee = Depends(get_current_user),
             db: Session = Depends(get_db)):
    _guard(db, user)
    query = db.query(MaintSparePart).filter(MaintSparePart.active == True)  # noqa: E712
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            MaintSparePart.part_name.ilike(like),
            MaintSparePart.part_code.ilike(like),
            MaintSparePart.machine.ilike(like),
            MaintSparePart.manufacturer.ilike(like),
            MaintSparePart.supplier.ilike(like),
        ))
    rows = [_json(p) for p in query.order_by(MaintSparePart.part_name).all()]
    if reorder:
        rows = [r for r in rows if r["reorder_status"] == "REORDER NOW"]
    totals = {
        "parts": len(rows),
        "stock_value": round(sum(r["stock_value"] for r in rows), 2),
        "reorder_count": sum(1 for r in rows if r["reorder_status"] == "REORDER NOW"),
        "total_units": round(sum(r["current_stock"] for r in rows), 3),
    }
    return {"rows": rows, "totals": totals}


# -------------------------------------------------------------------- save
class PartIn(BaseModel):
    part_code: str | None = None
    part_name: str
    machine: str | None = None
    manufacturer: str | None = None
    unit: str | None = None
    opening_qty: float | None = 0
    qty_in: float | None = 0
    qty_out: float | None = 0
    min_stock_level: float | None = 0
    unit_price: float | None = 0
    supplier: str | None = None
    last_purchase_date: str | None = None


def _apply(p: MaintSparePart, d: PartIn):
    p.part_code = (d.part_code or "").strip() or None
    p.part_name = (d.part_name or "").strip()
    p.machine = (d.machine or "").strip() or None
    p.manufacturer = (d.manufacturer or "").strip() or None
    p.unit = (d.unit or "").strip() or None
    p.opening_qty = _fnum(d.opening_qty)
    p.qty_in = _fnum(d.qty_in)
    p.qty_out = _fnum(d.qty_out)
    p.min_stock_level = _fnum(d.min_stock_level)
    p.unit_price = _fnum(d.unit_price)
    p.supplier = (d.supplier or "").strip() or None
    p.last_purchase_date = _pdate(d.last_purchase_date)


@router.post("/api/save")
def api_save(payload: PartIn, pid: int | None = None,
             user: Employee = Depends(get_current_user),
             db: Session = Depends(get_db)):
    _guard(db, user)
    if not (payload.part_name or "").strip():
        raise HTTPException(status_code=400, detail="Part name is required")
    if pid:
        p = db.get(MaintSparePart, pid)
        if not p:
            raise HTTPException(status_code=404, detail="Part not found")
    else:
        p = MaintSparePart()
        db.add(p)
    _apply(p, payload)
    db.commit()
    return {"ok": True, "part": _json(p)}


# ------------------------------------------------------------- stock move
class MoveIn(BaseModel):
    direction: str                 # 'in' | 'out'
    qty: float
    unit_price: float | None = None     # optional price update on an 'in'
    purchase_date: str | None = None    # optional date update on an 'in'


@router.post("/api/{pid}/move")
def api_move(pid: int, payload: MoveIn,
             user: Employee = Depends(get_current_user),
             db: Session = Depends(get_db)):
    _guard(db, user)
    p = db.get(MaintSparePart, pid)
    if not p:
        raise HTTPException(status_code=404, detail="Part not found")
    qty = _fnum(payload.qty)
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    if payload.direction == "in":
        p.qty_in = (p.qty_in or 0) + qty
        if payload.unit_price not in (None, ""):
            p.unit_price = _fnum(payload.unit_price)
        p.last_purchase_date = _pdate(payload.purchase_date) or date.today()
    elif payload.direction == "out":
        current = (p.opening_qty or 0) + (p.qty_in or 0) - (p.qty_out or 0)
        if qty > current:
            raise HTTPException(status_code=400,
                                detail=f"Only {current:g} in stock")
        p.qty_out = (p.qty_out or 0) + qty
    else:
        raise HTTPException(status_code=400, detail="direction must be 'in' or 'out'")
    db.commit()
    return {"ok": True, "part": _json(p)}


# ----------------------------------------------------------------- delete
@router.post("/api/{pid}/delete")
def api_delete(pid: int, user: Employee = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _guard(db, user)
    p = db.get(MaintSparePart, pid)
    if not p:
        raise HTTPException(status_code=404, detail="Part not found")
    p.active = False
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------- import
class ImportIn(BaseModel):
    csv_text: str
    replace: bool = False          # True -> deactivate existing first


# header label -> model field
_IMPORT_MAP = {
    "part code": "part_code", "partcode": "part_code",
    "part name": "part_name", "partname": "part_name", "description": "part_name",
    "machine / equipment": "machine", "machine": "machine", "equipment": "machine",
    "manufacturer": "manufacturer", "make": "manufacturer",
    "unit": "unit", "uom": "unit",
    "opening qty": "opening_qty", "opening": "opening_qty",
    "qty in": "qty_in", "in": "qty_in",
    "qty out": "qty_out", "out": "qty_out",
    "min stock level": "min_stock_level", "min stock": "min_stock_level",
    "reorder level": "min_stock_level",
    "unit price": "unit_price", "price": "unit_price", "rate": "unit_price",
    "supplier": "supplier", "vendor": "supplier",
    "last purchase date": "last_purchase_date", "purchase date": "last_purchase_date",
}
# columns we skip (derived / running number)
_IMPORT_SKIP = {"s.no", "sno", "sl.no", "current stock", "stock",
                "reorder status", "status", "stock value", "value"}


@router.post("/api/import")
def api_import(payload: ImportIn, user: Employee = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _guard(db, user)
    text = (payload.csv_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No CSV data provided")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="Need a header row plus at least one data row")

    header = [(c or "").strip().lower() for c in rows[0]]
    fields = []
    for h in header:
        if h in _IMPORT_SKIP:
            fields.append(None)
        else:
            fields.append(_IMPORT_MAP.get(h))
    if "part_name" not in fields:
        raise HTTPException(status_code=400,
                            detail="Could not find a 'Part Name' column in the header")

    if payload.replace:
        db.query(MaintSparePart).filter(MaintSparePart.active == True).update(  # noqa: E712
            {MaintSparePart.active: False}, synchronize_session=False)

    created = 0
    for r in rows[1:]:
        data = {}
        for i, field in enumerate(fields):
            if not field or i >= len(r):
                continue
            data[field] = r[i]
        name = (data.get("part_name") or "").strip()
        if not name:
            continue
        p = MaintSparePart(
            part_code=(data.get("part_code") or "").strip() or None,
            part_name=name,
            machine=(data.get("machine") or "").strip() or None,
            manufacturer=(data.get("manufacturer") or "").strip() or None,
            unit=(data.get("unit") or "").strip() or None,
            opening_qty=_fnum(data.get("opening_qty")),
            qty_in=_fnum(data.get("qty_in")),
            qty_out=_fnum(data.get("qty_out")),
            min_stock_level=_fnum(data.get("min_stock_level")),
            unit_price=_fnum(data.get("unit_price")),
            supplier=(data.get("supplier") or "").strip() or None,
            last_purchase_date=_pdate(data.get("last_purchase_date")),
        )
        db.add(p)
        created += 1
    db.commit()
    return {"ok": True, "created": created}


# ----------------------------------------------------------------- export
@router.get("/export.csv")
def export_csv(user: Employee = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _guard(db, user)
    rows = (db.query(MaintSparePart)
            .filter(MaintSparePart.active == True)  # noqa: E712
            .order_by(MaintSparePart.part_name).all())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["S.No", "Part Code", "Part Name", "Machine / Equipment",
                "Manufacturer", "Unit", "Opening Qty", "Qty In", "Qty Out",
                "Current Stock", "Min Stock Level", "Reorder Status",
                "Unit Price", "Stock Value", "Supplier", "Last Purchase Date"])
    for i, p in enumerate(rows, 1):
        j = _json(p)
        w.writerow([i, j["part_code"] or "", j["part_name"], j["machine"] or "",
                    j["manufacturer"] or "", j["unit"] or "", j["opening_qty"],
                    j["qty_in"], j["qty_out"], j["current_stock"],
                    j["min_stock_level"], j["reorder_status"], j["unit_price"],
                    j["stock_value"], j["supplier"] or "",
                    j["last_purchase_date"] or ""])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition":
                             "attachment; filename=spare_parts_inventory.csv"})
