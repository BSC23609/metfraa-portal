"""CRM module for the Metfraa Portal — leads, enquiries & quotations.

Open to any logged-in user (the sales team). Leads flow through a pipeline;
enquiries capture the PEB building requirement; quotations are built with
line items, GST and terms, exported as a branded PDF and emailed to the
customer.
"""
import asyncio
import os
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import engine, get_db
from ..deps import get_current_user
from ..models import CrmEnquiry, CrmEnquiryDoc, CrmLead, CrmQuotation, Employee

# Per-file cap. Vercel Hobby limits a request body to ~4.5 MB, so documents
# are uploaded one per request and capped a little under that.
DOC_MAX_MB = int(os.getenv("CRM_DOC_MAX_MB", "4"))


def _ensure_doc_table():
    """Create crm_enquiry_docs on first use so the feature works even when the
    INIT_DB migration step hasn't been run on Vercel. Idempotent and cheap."""
    try:
        CrmEnquiryDoc.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass

router = APIRouter(prefix="/crm", tags=["crm"])
templates = Jinja2Templates(directory="app/templates")

STAGES = ["New", "Contacted", "Qualified", "Quoted", "Negotiation", "Won", "Lost"]
OPEN_STAGES = ["New", "Contacted", "Qualified", "Quoted", "Negotiation"]
SOURCES = ["Website", "Referral", "Cold call", "Exhibition", "WhatsApp", "Walk-in", "Existing customer", "Other"]
BUILDING_USES = ["Factory / Industrial shed", "Warehouse / Godown", "Cold storage",
                 "Workshop", "Showroom / Commercial", "Multi-storey steel building", "Other"]
DEFAULT_TERMS = (
    "Prices are exclusive of GST unless stated otherwise.\n"
    "Quotation valid for 15 days from the date of issue.\n"
    "Delivery schedule to be confirmed on receipt of confirmed order and advance.\n"
    "Payment: as mutually agreed in the purchase order.\n"
    "Design to applicable IS codes; foundation in client's scope unless stated.")


def _iso(d):
    return d.isoformat() if d else None


def _pdate(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ page
@router.get("/", response_class=HTMLResponse)
def page(request: Request, user: Employee = Depends(get_current_user),
         db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "crm.html", {"user": user})


# =============================================================== LEADS
def _lead_json(l: CrmLead, db: Session = None):
    d = {
        "id": l.id, "company": l.company, "contact_name": l.contact_name,
        "phone": l.phone, "email": l.email, "designation": l.designation,
        "source": l.source, "location": l.location, "stage": l.stage,
        "owner": l.owner, "est_value": l.est_value,
        "next_follow_up": _iso(l.next_follow_up), "notes": l.notes,
        "lost_reason": l.lost_reason, "created_by": l.created_by,
        "created_at": _iso(l.created_at),
    }
    if db is not None:
        d["enquiry_count"] = db.query(CrmEnquiry).filter(CrmEnquiry.lead_id == l.id).count()
        d["quote_count"] = db.query(CrmQuotation).filter(CrmQuotation.lead_id == l.id).count()
    return d


class LeadIn(BaseModel):
    id: int | None = None
    company: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    designation: str | None = None
    source: str | None = None
    location: str | None = None
    stage: str | None = None
    owner: str | None = None
    est_value: float | None = None
    next_follow_up: str | None = None
    notes: str | None = None
    lost_reason: str | None = None


@router.get("/api/meta")
def api_meta(user: Employee = Depends(get_current_user)):
    return {"stages": STAGES, "sources": SOURCES, "building_uses": BUILDING_USES,
            "default_terms": DEFAULT_TERMS, "me": getattr(user, "name", "")}


@router.get("/api/summary")
def api_summary(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    by_stage = {s: 0 for s in STAGES}
    for l in db.query(CrmLead).all():
        by_stage[l.stage] = by_stage.get(l.stage, 0) + 1
    open_value = sum((l.est_value or 0) for l in db.query(CrmLead)
                     .filter(CrmLead.stage.in_(OPEN_STAGES)).all())
    won_value = sum((l.est_value or 0) for l in db.query(CrmLead)
                    .filter(CrmLead.stage == "Won").all())
    today = date.today()
    due = (db.query(CrmLead)
           .filter(CrmLead.next_follow_up != None,  # noqa: E711
                   CrmLead.next_follow_up <= today,
                   CrmLead.stage.in_(OPEN_STAGES)).count())
    return {"by_stage": by_stage, "open_value": open_value, "won_value": won_value,
            "follow_ups_due": due,
            "total_leads": db.query(CrmLead).count(),
            "total_enquiries": db.query(CrmEnquiry).count(),
            "total_quotations": db.query(CrmQuotation).count()}


@router.get("/api/leads")
def api_leads(q: str | None = None, stage: str | None = None,
              user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    qy = db.query(CrmLead)
    if stage and stage != "All":
        qy = qy.filter(CrmLead.stage == stage)
    if q:
        like = f"%{q.strip()}%"
        qy = qy.filter(or_(CrmLead.company.ilike(like), CrmLead.contact_name.ilike(like),
                           CrmLead.phone.ilike(like), CrmLead.email.ilike(like),
                           CrmLead.location.ilike(like)))
    rows = qy.order_by(CrmLead.updated_at.desc(), CrmLead.id.desc()).all()
    return {"leads": [_lead_json(l, db) for l in rows]}


@router.get("/api/lead/{lid}")
def api_lead(lid: int, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    l = db.get(CrmLead, lid)
    if not l:
        raise HTTPException(404, "Lead not found")
    d = _lead_json(l, db)
    d["enquiries"] = [_enquiry_json(e) for e in db.query(CrmEnquiry)
                      .filter(CrmEnquiry.lead_id == lid).order_by(CrmEnquiry.id.desc()).all()]
    d["quotations"] = [_quote_json(qu, brief=True) for qu in db.query(CrmQuotation)
                       .filter(CrmQuotation.lead_id == lid).order_by(CrmQuotation.id.desc()).all()]
    return d


@router.post("/api/lead/save")
def api_lead_save(payload: LeadIn, user: Employee = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    new = not payload.id
    l = CrmLead() if new else db.get(CrmLead, payload.id)
    if not l:
        raise HTTPException(404, "Lead not found")
    if new:
        l.created_by = getattr(user, "name", None)
        l.owner = payload.owner or getattr(user, "name", None)
        db.add(l)
    for f in ("company", "contact_name", "phone", "email", "designation",
              "source", "location", "notes", "lost_reason"):
        setattr(l, f, (getattr(payload, f) or "").strip() or None)
    if payload.owner:
        l.owner = payload.owner.strip()
    l.stage = (payload.stage or l.stage or "New")
    l.est_value = _f(payload.est_value)
    l.next_follow_up = _pdate(payload.next_follow_up)
    db.commit()
    db.refresh(l)
    return {"ok": True, "lead": _lead_json(l, db)}


@router.post("/api/lead/{lid}/stage")
def api_lead_stage(lid: int, payload: dict, user: Employee = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    l = db.get(CrmLead, lid)
    if not l:
        raise HTTPException(404, "Lead not found")
    st = (payload or {}).get("stage")
    if st not in STAGES:
        raise HTTPException(400, "Invalid stage")
    l.stage = st
    if st == "Lost" and (payload or {}).get("lost_reason"):
        l.lost_reason = str(payload["lost_reason"]).strip()[:300]
    db.commit()
    return {"ok": True}


@router.post("/api/lead/{lid}/delete")
def api_lead_delete(lid: int, user: Employee = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    l = db.get(CrmLead, lid)
    if not l:
        raise HTTPException(404, "Lead not found")
    # detach children rather than orphan-delete, so quotes/enquiries survive if wanted
    db.query(CrmEnquiry).filter(CrmEnquiry.lead_id == lid).delete()
    db.query(CrmQuotation).filter(CrmQuotation.lead_id == lid).update({CrmQuotation.lead_id: None})
    db.delete(l)
    db.commit()
    return {"ok": True}


# =============================================================== ENQUIRIES
def _enquiry_json(e: CrmEnquiry):
    return {
        "id": e.id, "enquiry_no": e.enquiry_no, "lead_id": e.lead_id, "date": _iso(e.date),
        "building_use": e.building_use, "length_m": e.length_m, "width_m": e.width_m,
        "eave_height_m": e.eave_height_m, "bay_spacing_m": e.bay_spacing_m,
        "clear_span": e.clear_span, "crane": e.crane, "crane_capacity": e.crane_capacity,
        "mezzanine": e.mezzanine, "cladding": e.cladding, "location": e.location,
        "required_by": _iso(e.required_by), "budget": e.budget, "status": e.status,
        "notes": e.notes, "created_by": e.created_by, "created_at": _iso(e.created_at),
    }


def _next_no(db: Session, model, col, prefix_base):
    year = datetime.now().year
    prefix = f"{prefix_base}-{year}-"
    n = 0
    for (no,) in db.query(col).filter(col.like(prefix + "%")).all():
        try:
            n = max(n, int((no or "").rsplit("-", 1)[-1]))
        except Exception:
            pass
    return f"{prefix}{n + 1:04d}"


class EnquiryIn(BaseModel):
    id: int | None = None
    lead_id: int | None = None
    date: str | None = None
    building_use: str | None = None
    length_m: float | None = None
    width_m: float | None = None
    eave_height_m: float | None = None
    bay_spacing_m: float | None = None
    clear_span: bool | None = False
    crane: bool | None = False
    crane_capacity: str | None = None
    mezzanine: bool | None = False
    cladding: str | None = None
    location: str | None = None
    required_by: str | None = None
    budget: float | None = None
    status: str | None = None
    notes: str | None = None


@router.get("/api/enquiries")
def api_enquiries(q: str | None = None, lead_id: int | None = None,
                  user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    qy = db.query(CrmEnquiry)
    if lead_id:
        qy = qy.filter(CrmEnquiry.lead_id == lead_id)
    if q:
        like = f"%{q.strip()}%"
        qy = qy.filter(or_(CrmEnquiry.enquiry_no.ilike(like),
                           CrmEnquiry.building_use.ilike(like),
                           CrmEnquiry.location.ilike(like)))
    rows = qy.order_by(CrmEnquiry.id.desc()).all()
    out = []
    for e in rows:
        d = _enquiry_json(e)
        lead = db.get(CrmLead, e.lead_id) if e.lead_id else None
        d["lead_company"] = lead.company if lead else None
        d["lead_contact"] = lead.contact_name if lead else None
        try:
            d["doc_count"] = db.query(CrmEnquiryDoc).filter(CrmEnquiryDoc.enquiry_id == e.id).count()
        except Exception:
            db.rollback()
            d["doc_count"] = 0
        out.append(d)
    return {"enquiries": out}


@router.post("/api/enquiry/save")
def api_enquiry_save(payload: EnquiryIn, user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    new = not payload.id
    e = CrmEnquiry() if new else db.get(CrmEnquiry, payload.id)
    if not e:
        raise HTTPException(404, "Enquiry not found")
    if new:
        e.enquiry_no = _next_no(db, CrmEnquiry, CrmEnquiry.enquiry_no, "ENQ")
        e.created_by = getattr(user, "name", None)
        db.add(e)
    e.lead_id = payload.lead_id
    e.date = _pdate(payload.date) or (e.date or date.today())
    e.building_use = (payload.building_use or "").strip() or None
    e.length_m = _f(payload.length_m)
    e.width_m = _f(payload.width_m)
    e.eave_height_m = _f(payload.eave_height_m)
    e.bay_spacing_m = _f(payload.bay_spacing_m)
    e.clear_span = bool(payload.clear_span)
    e.crane = bool(payload.crane)
    e.crane_capacity = (payload.crane_capacity or "").strip() or None
    e.mezzanine = bool(payload.mezzanine)
    e.cladding = (payload.cladding or "").strip() or None
    e.location = (payload.location or "").strip() or None
    e.required_by = _pdate(payload.required_by)
    e.budget = _f(payload.budget)
    e.status = (payload.status or e.status or "Open")
    e.notes = (payload.notes or "").strip() or None
    db.commit()
    db.refresh(e)
    return {"ok": True, "enquiry": _enquiry_json(e)}


@router.post("/api/enquiry/{eid}/delete")
def api_enquiry_delete(eid: int, user: Employee = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    e = db.get(CrmEnquiry, eid)
    if not e:
        raise HTTPException(404, "Enquiry not found")
    db.query(CrmQuotation).filter(CrmQuotation.enquiry_id == eid).update({CrmQuotation.enquiry_id: None})
    db.query(CrmEnquiryDoc).filter(CrmEnquiryDoc.enquiry_id == eid).delete()
    db.delete(e)
    db.commit()
    return {"ok": True}


# -------------------------------------------------- enquiry documents
def _doc_json(d: CrmEnquiryDoc):
    return {"id": d.id, "filename": d.filename, "mime_type": d.mime_type,
            "size_bytes": d.size_bytes, "uploaded_by": d.uploaded_by,
            "uploaded_at": _iso(d.uploaded_at)}


@router.get("/api/enquiry/{eid}/docs")
def api_enquiry_docs(eid: int, user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _ensure_doc_table()
    rows = (db.query(CrmEnquiryDoc).filter(CrmEnquiryDoc.enquiry_id == eid)
            .order_by(CrmEnquiryDoc.id).all())
    return {"docs": [_doc_json(d) for d in rows]}


@router.post("/api/enquiry/{eid}/docs")
async def api_enquiry_docs_upload(eid: int, files: list[UploadFile] = File(default=[]),
                                  user: Employee = Depends(get_current_user),
                                  db: Session = Depends(get_db)):
    _ensure_doc_table()
    e = db.get(CrmEnquiry, eid)
    if not e:
        raise HTTPException(404, "Enquiry not found")
    if not files:
        raise HTTPException(400, "No files received")
    saved = []
    for f in files[:20]:
        data = await f.read()
        if not data:
            continue
        if len(data) > DOC_MAX_MB * 1024 * 1024:
            raise HTTPException(413, f"{f.filename or 'file'} is too large. Max {DOC_MAX_MB} MB per file.")
        row = CrmEnquiryDoc(enquiry_id=eid, filename=(f.filename or "document")[:300],
                            mime_type=f.content_type or "application/octet-stream",
                            size_bytes=len(data), content=data,
                            uploaded_by=getattr(user, "name", None))
        db.add(row)
        db.flush()
        saved.append(_doc_json(row))
    db.commit()
    return {"ok": True, "docs": saved}


@router.get("/api/enquiry/doc/{doc_id}")
def api_enquiry_doc_download(doc_id: int, user: Employee = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    d = db.get(CrmEnquiryDoc, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    safe = (d.filename or "document").replace('"', "")
    return Response(content=bytes(d.content), media_type=d.mime_type or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{safe}"'})


@router.post("/api/enquiry/doc/{doc_id}/delete")
def api_enquiry_doc_delete(doc_id: int, user: Employee = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    d = db.get(CrmEnquiryDoc, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    db.delete(d)
    db.commit()
    return {"ok": True}


# =============================================================== QUOTATIONS
def _compute_totals(items, discount, gst_pct):
    subtotal = 0.0
    clean = []
    for n, it in enumerate(items or [], 1):
        qty = _f(it.get("qty")) or 0
        rate = _f(it.get("rate")) or 0
        amount = round(qty * rate, 2)
        clean.append({"sn": n, "description": (it.get("description") or "").strip(),
                      "qty": qty or None, "unit": (it.get("unit") or "").strip() or None,
                      "rate": rate or None, "amount": amount or None})
        subtotal += amount
    disc = _f(discount) or 0
    gp = _f(gst_pct)
    gp = 18.0 if gp is None else gp
    taxable = max(0.0, subtotal - disc)
    gst_amount = round(taxable * gp / 100, 2)
    total = round(taxable + gst_amount, 2)
    return clean, round(subtotal, 2), disc, gp, gst_amount, total


def _quote_json(qu: CrmQuotation, brief=False):
    d = {
        "id": qu.id, "quote_no": qu.quote_no, "lead_id": qu.lead_id,
        "enquiry_id": qu.enquiry_id, "date": _iso(qu.date), "valid_until": _iso(qu.valid_until),
        "customer_company": qu.customer_company, "customer_name": qu.customer_name,
        "project": qu.project, "subtotal": qu.subtotal, "gst_pct": qu.gst_pct,
        "gst_amount": qu.gst_amount, "discount": qu.discount, "total": qu.total,
        "status": qu.status, "sent_at": _iso(qu.sent_at), "created_by": qu.created_by,
        "created_at": _iso(qu.created_at),
    }
    if not brief:
        d.update({"customer_address": qu.customer_address, "customer_contact": qu.customer_contact,
                  "items": qu.items or [], "terms": qu.terms, "sent_to": qu.sent_to})
    return d


class QuoteIn(BaseModel):
    id: int | None = None
    lead_id: int | None = None
    enquiry_id: int | None = None
    date: str | None = None
    valid_until: str | None = None
    customer_company: str | None = None
    customer_name: str | None = None
    customer_address: str | None = None
    customer_contact: str | None = None
    project: str | None = None
    items: list = []
    discount: float | None = 0
    gst_pct: float | None = 18
    terms: str | None = None
    status: str | None = None


@router.get("/api/quotations")
def api_quotations(q: str | None = None, status: str | None = None,
                   user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    qy = db.query(CrmQuotation)
    if status and status != "All":
        qy = qy.filter(CrmQuotation.status == status)
    if q:
        like = f"%{q.strip()}%"
        qy = qy.filter(or_(CrmQuotation.quote_no.ilike(like),
                           CrmQuotation.customer_company.ilike(like),
                           CrmQuotation.customer_name.ilike(like),
                           CrmQuotation.project.ilike(like)))
    rows = qy.order_by(CrmQuotation.id.desc()).all()
    return {"quotations": [_quote_json(x, brief=True) for x in rows]}


@router.get("/api/quotation/{qid}")
def api_quotation(qid: int, user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    qu = db.get(CrmQuotation, qid)
    if not qu:
        raise HTTPException(404, "Quotation not found")
    return _quote_json(qu)


@router.post("/api/quotation/save")
def api_quotation_save(payload: QuoteIn, user: Employee = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    new = not payload.id
    qu = CrmQuotation() if new else db.get(CrmQuotation, payload.id)
    if not qu:
        raise HTTPException(404, "Quotation not found")
    if new:
        qu.quote_no = _next_no(db, CrmQuotation, CrmQuotation.quote_no, "QTN")
        qu.created_by = getattr(user, "name", None)
        qu.status = "Draft"
        db.add(qu)
    qu.lead_id = payload.lead_id
    qu.enquiry_id = payload.enquiry_id
    qu.date = _pdate(payload.date) or (qu.date or date.today())
    qu.valid_until = _pdate(payload.valid_until)
    qu.customer_company = (payload.customer_company or "").strip() or None
    qu.customer_name = (payload.customer_name or "").strip() or None
    qu.customer_address = (payload.customer_address or "").strip() or None
    qu.customer_contact = (payload.customer_contact or "").strip() or None
    qu.project = (payload.project or "").strip() or None
    items, subtotal, disc, gp, gst_amount, total = _compute_totals(
        payload.items, payload.discount, payload.gst_pct)
    qu.items, qu.subtotal, qu.discount = items, subtotal, disc
    qu.gst_pct, qu.gst_amount, qu.total = gp, gst_amount, total
    qu.terms = (payload.terms or "").strip() or None
    if payload.status in ("Draft", "Sent", "Accepted", "Rejected"):
        qu.status = payload.status
    db.commit()
    db.refresh(qu)
    # Keep the linked lead/enquiry in step
    if qu.lead_id:
        lead = db.get(CrmLead, qu.lead_id)
        if lead and lead.stage in ("New", "Contacted", "Qualified"):
            lead.stage = "Quoted"
            db.commit()
    if qu.enquiry_id:
        enq = db.get(CrmEnquiry, qu.enquiry_id)
        if enq and enq.status == "Open":
            enq.status = "Quoted"
            db.commit()
    return {"ok": True, "quotation": _quote_json(qu)}


@router.post("/api/quotation/{qid}/status")
def api_quotation_status(qid: int, payload: dict, user: Employee = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    qu = db.get(CrmQuotation, qid)
    if not qu:
        raise HTTPException(404, "Quotation not found")
    st = (payload or {}).get("status")
    if st not in ("Draft", "Sent", "Accepted", "Rejected"):
        raise HTTPException(400, "Invalid status")
    qu.status = st
    db.commit()
    return {"ok": True}


@router.post("/api/quotation/{qid}/delete")
def api_quotation_delete(qid: int, user: Employee = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    qu = db.get(CrmQuotation, qid)
    if not qu:
        raise HTTPException(404, "Quotation not found")
    db.delete(qu)
    db.commit()
    return {"ok": True}


@router.get("/api/quotation/{qid}/pdf")
def api_quotation_pdf(qid: int, user: Employee = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    qu = db.get(CrmQuotation, qid)
    if not qu:
        raise HTTPException(404, "Quotation not found")
    from ..services.quotation_pdf import build_quotation_pdf
    data = build_quotation_pdf(qu)
    fn = f"quotation_{(qu.quote_no or 'new').replace('/', '-')}.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fn}"'})


@router.post("/api/quotation/{qid}/send")
def api_quotation_send(qid: int, payload: dict | None = None,
                       user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    qu = db.get(CrmQuotation, qid)
    if not qu:
        raise HTTPException(404, "Quotation not found")
    to = ((payload or {}).get("to") or qu.customer_contact or "").strip()
    # pull an email out of the contact field if it looks like "phone / email"
    cand = [t.strip() for t in to.replace(";", ",").replace("/", ",").split(",") if "@" in t]
    to_email = cand[0] if cand else (to if "@" in to else "")
    if not to_email:
        raise HTTPException(400, "No customer email to send to — add one and retry")

    from ..services.quotation_pdf import build_quotation_pdf
    from ..services.email_service import send_email_async
    pdf = build_quotation_pdf(qu)
    fn = f"quotation_{(qu.quote_no or 'new').replace('/', '-')}.pdf"
    subject = f"Quotation {qu.quote_no} — Metfraa Steel Buildings"
    html = (f"<div style='font-family:Arial,sans-serif;color:#1E1D1D'>"
            f"<p>Dear {qu.customer_name or 'Sir/Madam'},</p>"
            f"<p>Please find attached our quotation <b>{qu.quote_no}</b>"
            f"{(' for ' + qu.project) if qu.project else ''}.</p>"
            f"<p>The quotation is valid up to {_iso(qu.valid_until) or 'the date mentioned'}. "
            f"We would be glad to take this forward — please feel free to reach us for any clarification.</p>"
            f"<p>Warm regards,<br>{qu.created_by or 'Metfraa Sales Team'}<br>"
            f"Metfraa Steel Buildings Pvt. Ltd.</p></div>")
    text = f"Dear {qu.customer_name or ''}, please find attached quotation {qu.quote_no}."

    async def _go():
        return await send_email_async(to_email, subject, html, text,
                                      attachments=[(fn, pdf, "application/pdf")])
    emailed = False
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_go())
            emailed = True
        else:
            emailed = asyncio.run(_go())
    except RuntimeError:
        try:
            emailed = asyncio.run(_go())
        except Exception:
            emailed = False
    except Exception:
        emailed = False

    if emailed:
        qu.sent_at = datetime.utcnow()
        qu.sent_to = to_email
        if qu.status == "Draft":
            qu.status = "Sent"
        db.commit()
    return {"ok": True, "emailed": emailed, "to": to_email}


# =============================================================== EXPORTS
@router.get("/api/leads/excel")
def api_leads_excel(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    from .maint import _build_xlsx, _xlsx_download
    headers = ["Company", "Contact", "Phone", "Email", "Source", "Location",
               "Stage", "Owner", "Est. Value", "Next follow-up", "Notes"]
    rows = []
    for l in db.query(CrmLead).order_by(CrmLead.id.desc()).all():
        rows.append([l.company, l.contact_name, l.phone, l.email, l.source, l.location,
                     l.stage, l.owner, l.est_value, _iso(l.next_follow_up), l.notes])
    return _xlsx_download(_build_xlsx("Leads", headers, rows), "crm_leads.xlsx")


@router.get("/api/quotations/excel")
def api_quotations_excel(user: Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    from .maint import _build_xlsx, _xlsx_download
    headers = ["Quote No.", "Date", "Customer", "Project", "Subtotal", "Discount",
               "GST %", "GST Amt", "Total", "Status", "Prepared by"]
    rows = []
    for x in db.query(CrmQuotation).order_by(CrmQuotation.id.desc()).all():
        rows.append([x.quote_no, _iso(x.date), x.customer_company or x.customer_name, x.project,
                     x.subtotal, x.discount, x.gst_pct, x.gst_amount, x.total, x.status, x.created_by])
    return _xlsx_download(_build_xlsx("Quotations", headers, rows), "crm_quotations.xlsx")
