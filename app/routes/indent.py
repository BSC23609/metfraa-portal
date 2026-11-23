"""Spare Parts Purchase Indent module.

A requisition raised against the Spare Parts inventory: a header (indent no,
date, department, requester, purpose, required-by) plus line items. On creation
a notification email is sent automatically to the purchase/stores recipients.
Access is gated by the same maint_admin flag as the Maintenance module.
"""
import asyncio
import os
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..access import get_access
from ..database import get_db
from ..deps import get_current_user
from ..models import Employee, MaintIndent

router = APIRouter(prefix="/indent", tags=["indent"])

# To = who the indent is addressed to; CC = who is kept in the loop.
DEFAULT_TO = "Stores@metfraa.com,purchase.plant@metfraa.com"
DEFAULT_CC = "Info@metfraa.com,Thangaraj@metfraa.com"

PURPOSES = ["Breakdown", "Preventive Maintenance", "Scheduled Overhaul",
            "Replacement", "Stock Replenishment", "Other"]


def _guard(db: Session, user: Employee):
    if not get_access(db, user).can_admin_maint:
        raise HTTPException(status_code=403, detail="Maintenance admin access required")


def _split(raw):
    return [e.strip() for e in (raw or "").replace(";", ",").split(",") if e.strip()]


def _notify_to():
    return _split(os.getenv("INDENT_NOTIFY_TO") or DEFAULT_TO)


def _notify_cc():
    return _split(os.getenv("INDENT_NOTIFY_CC") or DEFAULT_CC)


def _notify_recipients():
    # Legacy env override still forces the whole To list if set.
    legacy = os.getenv("INDENT_NOTIFY_EMAILS")
    to = _split(legacy) if legacy else _notify_to()
    return to, _notify_cc()


def _iso(d):
    return d.isoformat() if d else None


def _pdate(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _json(i: MaintIndent):
    return {
        "id": i.id, "indent_no": i.indent_no, "date_of_request": _iso(i.date_of_request),
        "department": i.department, "requested_by": i.requested_by, "contact": i.contact,
        "purpose": i.purpose, "purpose_other": i.purpose_other,
        "required_by": _iso(i.required_by), "items": i.items or [], "remarks": i.remarks,
        "status": i.status, "notified": i.notified, "notified_at": _iso(i.notified_at),
        "created_by": i.created_by, "created_at": _iso(i.created_at),
        "item_count": len(i.items or []),
    }


def _next_indent_no(db: Session) -> str:
    year = datetime.now().year
    prefix = f"IND-{year}-"
    n = 0
    for (no,) in db.query(MaintIndent.indent_no).filter(
            MaintIndent.indent_no.like(prefix + "%")).all():
        try:
            n = max(n, int((no or "").rsplit("-", 1)[-1]))
        except Exception:
            pass
    return f"{prefix}{n + 1:04d}"


# ------------------------------------------------------------------ email
def _indent_html(i: MaintIndent):
    navy = "#0A2B66"
    rows = ""
    for n, it in enumerate(i.items or [], 1):
        rows += (
            "<tr>"
            f"<td style='padding:6px 8px;border:1px solid #e2e8f0'>{it.get('sn') or n}</td>"
            f"<td style='padding:6px 8px;border:1px solid #e2e8f0'>{_esc(it.get('part_name'))}</td>"
            f"<td style='padding:6px 8px;border:1px solid #e2e8f0'>{_esc(it.get('part_no'))}</td>"
            f"<td style='padding:6px 8px;border:1px solid #e2e8f0'>{_esc(it.get('make'))}</td>"
            f"<td style='padding:6px 8px;border:1px solid #e2e8f0'>{_esc(it.get('machine'))}</td>"
            f"<td style='padding:6px 8px;border:1px solid #e2e8f0'>{_esc(it.get('unit'))}</td>"
            f"<td style='padding:6px 8px;border:1px solid #e2e8f0;text-align:right'>{_esc(it.get('qty'))}</td>"
            f"<td style='padding:6px 8px;border:1px solid #e2e8f0;text-align:right'>{_esc(it.get('stock'))}</td>"
            f"<td style='padding:6px 8px;border:1px solid #e2e8f0'>{_esc(it.get('remarks'))}</td>"
            "</tr>")
    purpose = i.purpose + ((": " + i.purpose_other) if (i.purpose == "Other" and i.purpose_other) else "") if i.purpose else "-"
    return f"""\
<div style="font-family:Arial,Helvetica,sans-serif;color:#0d1421;max-width:820px">
  <h2 style="margin:0 0 2px">Spare Parts Indent — {i.indent_no}</h2>
  <p style="margin:0 0 14px;color:#64748b;font-size:12px">Metfraa Steel Buildings Pvt. Ltd. · raised {_iso(i.date_of_request) or '-'}</p>
  <table style="border-collapse:collapse;font-size:13px;margin-bottom:12px">
    <tr><td style="padding:3px 10px;color:#64748b">Department / Section</td><td style="padding:3px 10px;font-weight:600">{_esc(i.department)}</td></tr>
    <tr><td style="padding:3px 10px;color:#64748b">Requested by</td><td style="padding:3px 10px;font-weight:600">{_esc(i.requested_by)}</td></tr>
    <tr><td style="padding:3px 10px;color:#64748b">Contact / Email</td><td style="padding:3px 10px">{_esc(i.contact)}</td></tr>
    <tr><td style="padding:3px 10px;color:#64748b">Purpose</td><td style="padding:3px 10px">{_esc(purpose)}</td></tr>
    <tr><td style="padding:3px 10px;color:#64748b">Required by</td><td style="padding:3px 10px;font-weight:600">{_iso(i.required_by) or '-'}</td></tr>
  </table>
  <table style="border-collapse:collapse;font-size:12px;width:100%">
    <thead><tr style="background:{navy};color:#fff">
      <th style="padding:6px 8px;border:1px solid {navy}">S.No.</th>
      <th style="padding:6px 8px;border:1px solid {navy};text-align:left">Part Name / Description</th>
      <th style="padding:6px 8px;border:1px solid {navy}">Part No.</th>
      <th style="padding:6px 8px;border:1px solid {navy}">Make / Spec</th>
      <th style="padding:6px 8px;border:1px solid {navy}">Name of m/c</th>
      <th style="padding:6px 8px;border:1px solid {navy}">Unit</th>
      <th style="padding:6px 8px;border:1px solid {navy}">Qty Req.</th>
      <th style="padding:6px 8px;border:1px solid {navy}">Stock</th>
      <th style="padding:6px 8px;border:1px solid {navy}">Remarks</th>
    </tr></thead><tbody>{rows}</tbody></table>
  {('<p style="margin-top:12px"><b>Remarks:</b> ' + _esc(i.remarks) + '</p>') if i.remarks else ''}
  <p style="color:#94a3b8;font-size:12px;margin-top:16px">Automated indent notification — Metfraa Maintenance portal.</p>
</div>"""


def _esc(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _send_indent_email(i: MaintIndent) -> bool:
    from ..services.email_service import send_email_async
    to_list, cc_list = _notify_recipients()
    if not to_list and cc_list:          # ensure at least one To
        to_list, cc_list = cc_list, []
    if not to_list:
        return False
    subject = f"New Spare Parts Indent — {i.indent_no} ({len(i.items or [])} item/s)"
    html = _indent_html(i)
    text = f"Spare Parts Indent {i.indent_no} raised. {len(i.items or [])} item(s). Please see the portal."
    to = ", ".join(to_list)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(send_email_async(to, subject, html, text, cc=cc_list))
            return True
    except RuntimeError:
        pass
    try:
        return asyncio.run(send_email_async(to, subject, html, text, cc=cc_list))
    except Exception:
        return False


# ------------------------------------------------------------------ schema
class IndentIn(BaseModel):
    id: int | None = None
    date_of_request: str | None = None
    department: str | None = None
    requested_by: str | None = None
    contact: str | None = None
    purpose: str | None = None
    purpose_other: str | None = None
    required_by: str | None = None
    items: list = []
    remarks: str | None = None
    status: str | None = None


# ------------------------------------------------------------------ endpoints
@router.get("/api/list")
def api_list(q: str | None = None, user: Employee = Depends(get_current_user),
             db: Session = Depends(get_db)):
    _guard(db, user)
    qy = db.query(MaintIndent)
    if q:
        like = f"%{q.strip()}%"
        qy = qy.filter(or_(MaintIndent.indent_no.ilike(like),
                           MaintIndent.department.ilike(like),
                           MaintIndent.requested_by.ilike(like)))
    rows = qy.order_by(MaintIndent.id.desc()).all()
    to, cc = _notify_recipients()
    return {"indents": [_json(i) for i in rows], "to": to, "cc": cc,
            "purposes": PURPOSES}


@router.get("/api/{iid}")
def api_get(iid: int, user: Employee = Depends(get_current_user),
            db: Session = Depends(get_db)):
    _guard(db, user)
    i = db.get(MaintIndent, iid)
    if not i:
        raise HTTPException(404, "Indent not found")
    return _json(i)


@router.post("/api/save")
def api_save(payload: IndentIn, user: Employee = Depends(get_current_user),
             db: Session = Depends(get_db)):
    _guard(db, user)
    new = not payload.id
    i = MaintIndent() if new else db.get(MaintIndent, payload.id)
    if not i:
        raise HTTPException(404, "Indent not found")
    if new:
        i.indent_no = _next_indent_no(db)
        i.created_by = getattr(user, "name", None)
        db.add(i)
    i.date_of_request = _pdate(payload.date_of_request) or (i.date_of_request or date.today())
    i.department = (payload.department or "").strip() or None
    i.requested_by = (payload.requested_by or "").strip() or None
    i.contact = (payload.contact or "").strip() or None
    i.purpose = (payload.purpose or "").strip() or None
    i.purpose_other = (payload.purpose_other or "").strip() or None
    i.required_by = _pdate(payload.required_by)
    i.items = payload.items or []
    i.remarks = (payload.remarks or "").strip() or None
    if payload.status:
        i.status = payload.status
    db.commit()
    db.refresh(i)

    emailed = False
    if new:
        emailed = _send_indent_email(i)
        if emailed:
            i.notified = True
            i.notified_at = datetime.utcnow()
            db.commit()
            db.refresh(i)
    to, cc = _notify_recipients()
    return {"ok": True, "indent": _json(i), "emailed": emailed, "to": to, "cc": cc}


@router.post("/api/{iid}/notify")
def api_notify(iid: int, user: Employee = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _guard(db, user)
    i = db.get(MaintIndent, iid)
    if not i:
        raise HTTPException(404, "Indent not found")
    emailed = _send_indent_email(i)
    if emailed:
        i.notified = True
        i.notified_at = datetime.utcnow()
        db.commit()
    to, cc = _notify_recipients()
    return {"ok": True, "emailed": emailed, "to": to, "cc": cc}


@router.post("/api/{iid}/delete")
def api_delete(iid: int, user: Employee = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _guard(db, user)
    i = db.get(MaintIndent, iid)
    if not i:
        raise HTTPException(404, "Indent not found")
    db.delete(i)
    db.commit()
    return {"ok": True}


@router.get("/api/{iid}/excel")
def api_excel(iid: int, user: Employee = Depends(get_current_user),
              db: Session = Depends(get_db)):
    _guard(db, user)
    i = db.get(MaintIndent, iid)
    if not i:
        raise HTTPException(404, "Indent not found")
    from .maint import _build_xlsx, _XLSX_MIME
    headers = ["S.No.", "Part Name / Description", "Part No.", "Make / Specification",
               "Name of m/c", "Unit", "Qty Required", "Stock in Hand", "Remarks"]
    rows = []
    for n, it in enumerate(i.items or [], 1):
        rows.append([it.get("sn") or n, it.get("part_name"), it.get("part_no"),
                     it.get("make"), it.get("machine"), it.get("unit"),
                     it.get("qty"), it.get("stock"), it.get("remarks")])
    rows += [[], ["Indent No.", i.indent_no, "", "", "Date of Request", _iso(i.date_of_request)],
             ["Department / Section", i.department, "", "", "Required By", _iso(i.required_by)],
             ["Requested By", i.requested_by, "", "", "Contact / Email", i.contact],
             ["Purpose", (i.purpose or "") + ((": " + i.purpose_other) if (i.purpose == "Other" and i.purpose_other) else "")]]
    data = _build_xlsx("Indent", headers, rows)
    fn = f"indent_{(i.indent_no or 'new').replace('/', '-')}.xlsx"
    return Response(content=data, media_type=_XLSX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})
