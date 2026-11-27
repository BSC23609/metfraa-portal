"""Customer Ledger / KYC forms for the Metfraa CRM.

Flow: a quotation is confirmed -> the sales user generates a ledger form
(a tokenised public link) -> the customer fills the Metfraa-branded data
sheet (company, billing, bank, shipping + GST cert / cancelled cheque) ->
it lands in the admin "Ledger forms" list to review, approve and mark in SAP.

Public (customer-facing) endpoints take only the link token and need no
login. Admin endpoints require a logged-in portal user.
"""
import io
import os
import pathlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import engine, get_db
from ..deps import get_current_user
from ..models import (CrmLead, CrmLedgerDoc, CrmLedgerForm, CrmQuotation,
                      Employee)

router = APIRouter(prefix="/crm", tags=["crm-ledger"])
templates = Jinja2Templates(directory="app/templates")

DOC_MAX_MB = int(os.getenv("CRM_DOC_MAX_MB", "4"))
PUBLIC_BASE = os.getenv("PUBLIC_BASE_URL", "https://app.metfraa.com").rstrip("/")

STATUSES = ["link_sent", "submitted", "approved", "in_sap", "rejected"]
STATUS_LABEL = {"link_sent": "Link sent", "submitted": "To process",
                "approved": "Approved", "in_sap": "In SAP", "rejected": "Rejected"}

BUYER_TYPES = ["OEM", "Government Contractor Project", "Fabricator",
               "Capex / Expansion Work", "Individual House Buyer",
               "Maintenance Activity", "Re-seller"]
INDUSTRY_SEGMENTS = [
    "Agriculture", "Auto Ancillary/Body", "Auto OEM", "Boilers & Pressure Valves",
    "Cold - Forming", "Containers", "Defence", "Earth Moving Equipments",
    "Electrical Equipment", "Electrode manufacturer", "Forging", "Furniture",
    "General fabrication", "Heavy Machinery", "Housing Construction", "Infrastructure",
    "LPG Cylinder", "Machine Tools", "MSME Plant Based", "Packaging", "Power",
    "Pre-eng Building Str", "Railways", "Re Sale", "Re-rolling", "Ship building",
    "Distributor", "Project Sales", "Tube-making"]
REG_TYPES = ["PVT LTD", "GOVT PSU", "LLP", "Proprietorship"]
USAGE_OPTS = ["Once", "Monthly Requirement"]
STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
    "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman & Nicobar", "Chandigarh",
    "Dadra & Nagar Haveli and Daman & Diu", "Delhi", "Jammu & Kashmir", "Ladakh",
    "Lakshadweep", "Puducherry"]


def _ensure_tables():
    try:
        CrmLedgerForm.__table__.create(bind=engine, checkfirst=True)
        CrmLedgerDoc.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass


def _iso(d):
    return d.isoformat() if d else None


def _next_ref(db):
    year = datetime.now().year
    prefix = f"KYC-{year}-"
    n = 0
    for (ref,) in db.query(CrmLedgerForm.ref).filter(CrmLedgerForm.ref.like(prefix + "%")).all():
        try:
            n = max(n, int((ref or "").rsplit("-", 1)[-1]))
        except Exception:
            pass
    return f"{prefix}{n + 1:04d}"


def _public_fields(f: CrmLedgerForm):
    """What the public form loads to prefill itself."""
    return {
        "ref": f.ref, "status": f.status,
        "company_name": f.company_name, "company_type": f.company_type,
        "contact_number": f.contact_number, "email": f.email,
        "contact_person": f.contact_person,
        "type_of_buyer": f.type_of_buyer or [], "type_of_buyer_other": f.type_of_buyer_other,
        "industry_segment": f.industry_segment, "industry_segment_other": f.industry_segment_other,
        "usage": f.usage,
        "billing_address": f.billing_address, "billing_pincode": f.billing_pincode,
        "billing_district": f.billing_district, "billing_state": f.billing_state,
        "billing_gstin": f.billing_gstin, "company_reg_type": f.company_reg_type,
        "bank_trade_name": f.bank_trade_name, "bank_account_number": f.bank_account_number,
        "ifsc_code": f.ifsc_code,
        "shipping_same": f.shipping_same, "shipping_trade_name": f.shipping_trade_name,
        "shipping_address": f.shipping_address, "shipping_pincode": f.shipping_pincode,
        "shipping_district": f.shipping_district, "shipping_state": f.shipping_state,
        "shipping_gstin": f.shipping_gstin,
    }


def _docs_json(db, fid):
    rows = db.query(CrmLedgerDoc).filter(CrmLedgerDoc.ledger_id == fid).order_by(CrmLedgerDoc.id).all()
    return [{"id": d.id, "kind": d.kind, "filename": d.filename, "size_bytes": d.size_bytes} for d in rows]


# ============================================================= PUBLIC PAGES
@router.get("/kyc", response_class=HTMLResponse)
@router.get("/kyc/{token}", response_class=HTMLResponse)
def public_form(request: Request, token: str = "", db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "ledger_form.html", {"token": token})


# ============================================================= PUBLIC API
class StartIn(BaseModel):
    token: str | None = None


@router.post("/ledger/public/start")
def public_start(db: Session = Depends(get_db)):
    _ensure_tables()
    f = CrmLedgerForm(ref=_next_ref(db), token=secrets.token_hex(16), status="link_sent")
    db.add(f)
    db.commit()
    db.refresh(f)
    return {"ok": True, "token": f.token, "ref": f.ref}


def _by_token(db, token):
    _ensure_tables()
    f = db.query(CrmLedgerForm).filter(CrmLedgerForm.token == token).first()
    if not f:
        raise HTTPException(404, "Form link not found")
    return f


@router.get("/ledger/public/{token}")
def public_get(token: str, db: Session = Depends(get_db)):
    f = _by_token(db, token)
    return {"ok": True, "form": _public_fields(f), "docs": _docs_json(db, f.id),
            "locked": f.status in ("approved", "in_sap")}


@router.post("/ledger/public/{token}/upload")
async def public_upload(token: str, kind: str = "", files: list[UploadFile] = File(default=[]),
                        db: Session = Depends(get_db)):
    f = _by_token(db, token)
    if not files:
        raise HTTPException(400, "No file received")
    up = files[0]
    data = await up.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > DOC_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large. Max {DOC_MAX_MB} MB.")
    k = kind if kind in ("gst_billing", "cheque", "gst_shipping") else "other"
    # one document per kind — replace an existing one
    db.query(CrmLedgerDoc).filter(CrmLedgerDoc.ledger_id == f.id, CrmLedgerDoc.kind == k).delete()
    row = CrmLedgerDoc(ledger_id=f.id, kind=k, filename=(up.filename or "document")[:300],
                       mime_type=up.content_type or "application/octet-stream",
                       size_bytes=len(data), content=data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "doc": {"id": row.id, "kind": row.kind, "filename": row.filename,
                                "size_bytes": row.size_bytes}}


@router.post("/ledger/public/{token}/doc/{doc_id}/delete")
def public_doc_delete(token: str, doc_id: int, db: Session = Depends(get_db)):
    f = _by_token(db, token)
    d = db.query(CrmLedgerDoc).filter(CrmLedgerDoc.id == doc_id, CrmLedgerDoc.ledger_id == f.id).first()
    if d:
        db.delete(d)
        db.commit()
    return {"ok": True}


class SubmitIn(BaseModel):
    company_name: str | None = None
    company_type: str | None = None
    contact_number: str | None = None
    email: str | None = None
    contact_person: str | None = None
    type_of_buyer: list = []
    type_of_buyer_other: str | None = None
    industry_segment: str | None = None
    industry_segment_other: str | None = None
    usage: str | None = None
    billing_address: str | None = None
    billing_pincode: str | None = None
    billing_district: str | None = None
    billing_state: str | None = None
    billing_gstin: str | None = None
    company_reg_type: str | None = None
    bank_trade_name: str | None = None
    bank_account_number: str | None = None
    ifsc_code: str | None = None
    shipping_same: bool | None = False
    shipping_trade_name: str | None = None
    shipping_address: str | None = None
    shipping_pincode: str | None = None
    shipping_district: str | None = None
    shipping_state: str | None = None
    shipping_gstin: str | None = None


def _s(v):
    return (v or "").strip() or None


@router.post("/ledger/public/{token}/submit")
def public_submit(token: str, p: SubmitIn, db: Session = Depends(get_db)):
    f = _by_token(db, token)
    if f.status in ("approved", "in_sap"):
        raise HTTPException(400, "This form is already processed and locked.")

    required = {
        "Company Name": p.company_name, "Company Type": p.company_type,
        "Contact Number": p.contact_number, "Email": p.email,
        "Customer Industry Segment": p.industry_segment, "Usage": p.usage,
        "Billing Address": p.billing_address, "Pincode": p.billing_pincode,
        "District": p.billing_district, "State": p.billing_state,
        "GST Number": p.billing_gstin, "Company Registration Type": p.company_reg_type,
        "Bank Account Number": p.bank_account_number, "IFSC Code": p.ifsc_code,
    }
    missing = [k for k, v in required.items() if not (v or "").strip()]
    if not (p.type_of_buyer or []):
        missing.append("Type of Buyer")
    if not p.shipping_same:
        for k, v in {"Shipping Trade Name": p.shipping_trade_name,
                     "Shipping Address": p.shipping_address,
                     "Shipping Pincode": p.shipping_pincode,
                     "Shipping District": p.shipping_district,
                     "Shipping State": p.shipping_state,
                     "Shipping GST Number": p.shipping_gstin}.items():
            if not (v or "").strip():
                missing.append(k)
    if missing:
        raise HTTPException(400, "Please fill: " + ", ".join(missing))

    have = {d.kind for d in db.query(CrmLedgerDoc.kind).filter(CrmLedgerDoc.ledger_id == f.id).all()}
    doc_missing = []
    if "gst_billing" not in have:
        doc_missing.append("GST Certificate (Billing Address)")
    if "cheque" not in have:
        doc_missing.append("Cancelled Cheque Copy")
    if not p.shipping_same and "gst_shipping" not in have:
        doc_missing.append("GST Certificate (Shipping Address)")
    if doc_missing:
        raise HTTPException(400, "Please upload: " + ", ".join(doc_missing))

    f.company_name, f.company_type = _s(p.company_name), _s(p.company_type)
    f.contact_number, f.email, f.contact_person = _s(p.contact_number), _s(p.email), _s(p.contact_person)
    f.type_of_buyer = [b for b in (p.type_of_buyer or []) if b]
    f.type_of_buyer_other = _s(p.type_of_buyer_other)
    f.industry_segment, f.industry_segment_other = _s(p.industry_segment), _s(p.industry_segment_other)
    f.usage = _s(p.usage)
    f.billing_address, f.billing_pincode = _s(p.billing_address), _s(p.billing_pincode)
    f.billing_district, f.billing_state = _s(p.billing_district), _s(p.billing_state)
    f.billing_gstin, f.company_reg_type = _s(p.billing_gstin), _s(p.company_reg_type)
    f.bank_trade_name, f.bank_account_number = _s(p.bank_trade_name), _s(p.bank_account_number)
    f.ifsc_code = _s(p.ifsc_code)
    f.shipping_same = bool(p.shipping_same)
    if p.shipping_same:
        f.shipping_trade_name = f.company_name
        f.shipping_address, f.shipping_pincode = f.billing_address, f.billing_pincode
        f.shipping_district, f.shipping_state = f.billing_district, f.billing_state
        f.shipping_gstin = f.billing_gstin
    else:
        f.shipping_trade_name = _s(p.shipping_trade_name)
        f.shipping_address, f.shipping_pincode = _s(p.shipping_address), _s(p.shipping_pincode)
        f.shipping_district, f.shipping_state = _s(p.shipping_district), _s(p.shipping_state)
        f.shipping_gstin = _s(p.shipping_gstin)
    f.status = "submitted"
    f.submitted_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "ref": f.ref}


# ============================================================= ADMIN PAGE
@router.get("/ledger", response_class=HTMLResponse)
def admin_page(request: Request, user: Employee = Depends(get_current_user),
               db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "ledger_admin.html", {"user": user})


# ============================================================= ADMIN API
@router.get("/ledger/api/meta")
def admin_meta(user: Employee = Depends(get_current_user)):
    return {"public_link": f"{PUBLIC_BASE}/crm/kyc", "statuses": STATUSES,
            "status_label": STATUS_LABEL}


def _branded_qr_png(text: str) -> bytes:
    """Square navy QR for `text` with the Bharat Steel Group logo in a round
    white centre badge."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_H
    from PIL import Image, ImageDraw
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=12, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color=(10, 43, 102), back_color="white").convert("RGBA")
    w, h = img.size
    logo_path = (pathlib.Path(__file__).resolve().parent.parent
                 / "static" / "img" / "bsg_group_logo.png")
    try:
        if logo_path and logo_path.exists():
            d = int(w * 0.26)
            badge = Image.new("RGBA", (d, d), (0, 0, 0, 0))
            ImageDraw.Draw(badge).ellipse([0, 0, d - 1, d - 1], fill=(255, 255, 255, 255))
            logo = Image.open(str(logo_path)).convert("RGBA")
            md = int(d * 0.74)
            lw, lh = logo.size
            r = min(md / lw, md / lh)
            logo = logo.resize((max(1, int(lw * r)), max(1, int(lh * r))), Image.LANCZOS)
            badge.alpha_composite(logo, ((d - logo.size[0]) // 2, (d - logo.size[1]) // 2))
            img.alpha_composite(badge, ((w - d) // 2, (h - d) // 2))
    except Exception:
        pass
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


@router.get("/ledger/qr.png")
def ledger_qr(download: int = 0, user: Employee = Depends(get_current_user)):
    data = _branded_qr_png(f"{PUBLIC_BASE}/crm/kyc")
    disp = "attachment" if download else "inline"
    return Response(content=data, media_type="image/png",
                    headers={"Content-Disposition": f'{disp}; filename="metfraa-ledger-qr.png"'})


def _row_json(db, f: CrmLedgerForm):
    return {
        "id": f.id, "ref": f.ref, "status": f.status, "status_label": STATUS_LABEL.get(f.status, f.status),
        "company_name": f.company_name, "email": f.email, "contact_number": f.contact_number,
        "gstin": f.billing_gstin, "segment": f.industry_segment, "usage": f.usage,
        "location": ", ".join([x for x in [f.billing_district, f.billing_state] if x]),
        "doc_count": db.query(CrmLedgerDoc).filter(CrmLedgerDoc.ledger_id == f.id).count(),
        "created_at": _iso(f.created_at), "submitted_at": _iso(f.submitted_at),
        "token": f.token,
    }


@router.get("/ledger/api/list")
def admin_list(status: str | None = None, q: str | None = None,
               user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_tables()
    qy = db.query(CrmLedgerForm)
    if status and status != "all":
        qy = qy.filter(CrmLedgerForm.status == status)
    if q:
        like = f"%{q.strip()}%"
        qy = qy.filter(or_(CrmLedgerForm.company_name.ilike(like),
                           CrmLedgerForm.billing_gstin.ilike(like),
                           CrmLedgerForm.ref.ilike(like),
                           CrmLedgerForm.email.ilike(like)))
    rows = qy.order_by(CrmLedgerForm.id.desc()).all()
    counts = {s: db.query(CrmLedgerForm).filter(CrmLedgerForm.status == s).count() for s in STATUSES}
    counts["all"] = db.query(CrmLedgerForm).count()
    return {"forms": [_row_json(db, f) for f in rows], "counts": counts}


@router.get("/ledger/api/form/{fid}")
def admin_detail(fid: int, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.get(CrmLedgerForm, fid)
    if not f:
        raise HTTPException(404, "Not found")
    d = _public_fields(f)
    d.update({"id": f.id, "ref": f.ref, "status": f.status, "remarks": f.remarks,
              "token": f.token, "submitted_at": _iso(f.submitted_at),
              "public_link": f"{PUBLIC_BASE}/crm/kyc/{f.token}"})
    d["docs"] = _docs_json(db, f.id)
    return d


class FromQuoteIn(BaseModel):
    quotation_id: int | None = None
    lead_id: int | None = None


@router.post("/ledger/api/from-quote")
def admin_from_quote(p: FromQuoteIn, user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _ensure_tables()
    lead = None
    quote = db.get(CrmQuotation, p.quotation_id) if p.quotation_id else None
    lid = p.lead_id or (quote.lead_id if quote else None)
    if lid:
        lead = db.get(CrmLead, lid)
    f = CrmLedgerForm(ref=_next_ref(db), token=secrets.token_hex(16), status="link_sent",
                      quotation_id=(quote.id if quote else None),
                      lead_id=(lead.id if lead else None),
                      created_by=getattr(user, "name", None))
    # prefill what we know
    if quote:
        f.company_name = quote.customer_company or (lead.company if lead else None)
        f.contact_person = quote.customer_name or (lead.contact_name if lead else None)
    elif lead:
        f.company_name = lead.company
        f.contact_person = lead.contact_name
    if lead:
        f.email = lead.email
        f.contact_number = lead.phone
    db.add(f)
    db.commit()
    db.refresh(f)
    return {"ok": True, "ref": f.ref, "token": f.token,
            "link": f"{PUBLIC_BASE}/crm/kyc/{f.token}"}


@router.post("/ledger/api/{fid}/status")
def admin_status(fid: int, payload: dict, user: Employee = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    f = db.get(CrmLedgerForm, fid)
    if not f:
        raise HTTPException(404, "Not found")
    st = (payload or {}).get("status")
    if st not in STATUSES:
        raise HTTPException(400, "Invalid status")
    f.status = st
    f.reviewed_by = getattr(user, "name", None)
    if (payload or {}).get("remarks") is not None:
        f.remarks = str(payload["remarks"]).strip()[:1000] or None
    db.commit()
    return {"ok": True}


@router.post("/ledger/api/{fid}/delete")
def admin_delete(fid: int, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.get(CrmLedgerForm, fid)
    if not f:
        raise HTTPException(404, "Not found")
    db.query(CrmLedgerDoc).filter(CrmLedgerDoc.ledger_id == fid).delete()
    db.delete(f)
    db.commit()
    return {"ok": True}


@router.get("/ledger/api/doc/{doc_id}")
def admin_doc(doc_id: int, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    d = db.get(CrmLedgerDoc, doc_id)
    if not d:
        raise HTTPException(404, "Not found")
    safe = (d.filename or "document").replace('"', "")
    return Response(content=bytes(d.content), media_type=d.mime_type or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{safe}"'})


@router.get("/ledger/api/excel")
def admin_excel(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    from .maint import _build_xlsx, _xlsx_download
    headers = ["Ref", "Company", "GSTIN", "Segment", "Usage", "Location", "Email",
               "Contact", "Reg Type", "Bank A/C", "IFSC", "Status", "Submitted"]
    rows = []
    for f in db.query(CrmLedgerForm).order_by(CrmLedgerForm.id.desc()).all():
        rows.append([f.ref, f.company_name, f.billing_gstin, f.industry_segment, f.usage,
                     ", ".join([x for x in [f.billing_district, f.billing_state] if x]),
                     f.email, f.contact_number, f.company_reg_type, f.bank_account_number,
                     f.ifsc_code, STATUS_LABEL.get(f.status, f.status), _iso(f.submitted_at)])
    return _xlsx_download(_build_xlsx("Ledger forms", headers, rows), "ledger_forms.xlsx")
