"""Team Get Together 2026 — pass distribution, QR verification, change requests.

Root-mounted like gatepass_public: the WhatsApp template's dynamic button may
only vary in its LAST path segment, and gate volunteers scanning QR codes must
not need a login — the unguessable hash inside every pass_id is the
authorisation (same principle as the gatepass return_token).

Routes
  GET  /tgt26/pass/{pid}.png     public   pass image download (WhatsApp button)
  GET  /tgt26/verify/{pid}       public   QR target — VALID / INVALID / USED page
  GET  /tgt26/checkin/{pid}      public   one-tap check-in from the verify page
  POST /tgt26/wati-webhook       public   WATI "message received" → change capture
  GET  /tgt26/change-requests    admin    review captured change requests
  POST /tgt26/send-passes        admin    broadcast the pass template to all 62

Static: put the 62 PNG files in app/static/tgt26_passes/ (served here via
FileResponse because vercel.json routes everything through /api/index).
Setup:  python scripts/tgt26_setup.py   (creates tables + seeds the register)
"""
import logging
import os
import pathlib
import re
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..models import Employee, Tgt26ChangeRequest, Tgt26Pass, WaLog
from ..services import wati

router = APIRouter(tags=["tgt26"])
log = logging.getLogger(__name__)
IST = timedelta(hours=5, minutes=30)

PASS_DIR = pathlib.Path(__file__).resolve().parent.parent / "static" / "tgt26_passes"
PID_RE = re.compile(r"^TGT26-\d{3}-[0-9A-F]{8}$")

COMPANY_FULL = {
    "BSC": "Bharat Steel (Chennai) Pvt. Ltd.",
    "MET": "Metfraa Steel Buildings Pvt. Ltd.",
    "CRS": "Crayon Roofings & Structures",
    "G2S": "G2 Steel Services Pvt. Ltd.",
}

# Template registered in the Metfraa WATI account — see
# docs/WATI_TEMPLATES_METFRAA.md ("tgt26_event_pass") for the exact body.
TGT26_TPL = os.getenv("WATI_TGT26_PASS_TPL", "tgt26_event_pass")


def _page(cls: str, verdict: str, body: str, status: int = 200) -> HTMLResponse:
    color = {"ok": "#1E8E3E", "bad": "#C5221F", "used": "#E8710A",
             "info": "#0069A6"}[cls]
    return HTMLResponse(status_code=status, content=f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Team Get Together 2026</title></head>
<body style="margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#F5F8FC;color:#152238">
<div style="background:#0F2A52;color:#fff;padding:16px;text-align:center;font-weight:700">
TEAM GET TOGETHER 2026 &bull; PASS VERIFICATION</div>
<div style="max-width:440px;margin:24px auto;background:#fff;border-radius:12px;
box-shadow:0 2px 10px rgba(15,42,82,.12);overflow:hidden">
<div style="padding:16px;text-align:center;font-size:21px;font-weight:700;color:#fff;background:{color}">
{verdict}</div>{body}</div></body></html>""")


def _row(label: str, value: str) -> str:
    return (f'<tr><td style="padding:10px 16px;border-bottom:1px solid #EAF1F9;'
            f'color:#5B6B80;width:45%">{label}</td>'
            f'<td style="padding:10px 16px;border-bottom:1px solid #EAF1F9">{value}</td></tr>')


# --------------------------------------------------------------------- image
@router.get("/tgt26/pass/{pid}.png")
def download_pass(pid: str):
    if not PID_RE.match(pid):
        return _page("bad", "\u2716 INVALID LINK", "", status=404)
    path = PASS_DIR / f"{pid}.png"
    if not path.is_file():
        return _page("bad", "\u2716 PASS NOT FOUND",
                     f"<table style='width:100%;border-collapse:collapse'>"
                     f"{_row('Pass ID', pid)}</table>", status=404)
    return FileResponse(path, media_type="image/png",
                        filename=f"TGT26 Event Pass - {pid}.png",
                        headers={"Cache-Control": "public, max-age=86400"})


# -------------------------------------------------------------------- verify
@router.get("/tgt26/verify/{pid}", response_class=HTMLResponse)
def verify(pid: str, db: Session = Depends(get_db)):
    p = db.query(Tgt26Pass).filter_by(pass_id=pid).first() if PID_RE.match(pid) else None
    if not p:
        return _page("bad", "\u2716 INVALID PASS",
                     f"<table style='width:100%;border-collapse:collapse'>"
                     f"{_row('Pass ID', pid)}"
                     f"{_row('Action', 'Not in the register — do not permit entry.')}"
                     f"</table>")
    body = ("<table style='width:100%;border-collapse:collapse'>"
            + _row("Name", f"<b>{p.name}</b>")
            + _row("Company", COMPANY_FULL.get(p.company, p.company))
            + _row("Designation", p.designation or "-")
            + _row("Spouse", "Yes" if p.spouse else "No")
            + _row("Kids &lt;5 / &lt;12 / &gt;12", f"{p.k5} / {p.k12} / {p.k12p}")
            + _row("Total attendees", f"<b>{p.total_attendees}</b>")
            + _row("Pass ID", p.pass_id))
    if p.checked_in_at:
        ist = p.checked_in_at + IST
        body += _row("Checked in", ist.strftime("%d-%b %I:%M %p")) + "</table>"
        return _page("used", "\u26A0 ALREADY CHECKED IN", body)
    body += ("</table>"
             f'<a href="/tgt26/checkin/{p.pass_id}" style="display:block;margin:16px;'
             f'padding:13px;background:#0069A6;color:#fff;text-align:center;'
             f'border-radius:8px;text-decoration:none;font-weight:700">'
             f"Mark as Checked In</a>")
    return _page("ok", "\u2714 VALID PASS", body)


@router.get("/tgt26/checkin/{pid}", response_class=HTMLResponse)
def checkin(pid: str, db: Session = Depends(get_db)):
    p = db.query(Tgt26Pass).filter_by(pass_id=pid).first() if PID_RE.match(pid) else None
    if not p:
        return _page("bad", "\u2716 INVALID PASS", "")
    if p.checked_in_at:
        ist = p.checked_in_at + IST
        return _page("used", "\u26A0 ALREADY CHECKED IN",
                     f"<table style='width:100%;border-collapse:collapse'>"
                     f"{_row('Name', p.name)}"
                     f"{_row('First check-in', ist.strftime('%d-%b %I:%M %p'))}</table>")
    p.checked_in_at = datetime.utcnow()
    db.commit()
    return _page("ok", "\u2714 CHECKED IN",
                 f"<table style='width:100%;border-collapse:collapse'>"
                 f"{_row('Name', p.name)}{_row('Total attendees', str(p.total_attendees))}"
                 f"</table>")


# ------------------------------------------------------------------- webhook
def _send_session_text(phone: str, message: str, db: Session) -> None:
    """Free-form reply inside the 24h window the button tap just opened.

    Same guards as wati.send_template: hard timeout, WaLog row either way, and
    a failure never raises — a webhook must always 200 or WATI retries forever.
    """
    if not wati.configured():
        log.info("[tgt26] (wati not configured) would reply to %s: %s", phone, message)
        return
    tok = os.getenv("WATI_TOKEN") or ""
    headers = {"Authorization": tok if tok.startswith("Bearer") else f"Bearer {tok}"}
    url = (os.getenv("WATI_BASE_URL") or "").rstrip("/") + f"/api/v1/sendSessionMessage/{phone}"
    timeout = float(os.getenv("WATI_TIMEOUT_MS", "8000")) / 1000.0
    result, detail = "sent", ""
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, headers=headers, params={"messageText": message})
        if r.status_code >= 400:
            result, detail = "http_error", f"{r.status_code} {r.text[:300]}"
    except Exception as exc:  # noqa: BLE001
        result, detail = "error", str(exc)[:300]
    try:
        db.add(WaLog(phone=phone[:32], template="tgt26_session_reply",
                     result=result, detail=detail))
        db.commit()
    except Exception:
        db.rollback()


@router.post("/tgt26/wati-webhook")
async def wati_webhook(request: Request, db: Session = Depends(get_db)):
    """WATI dashboard → Webhooks → "Message received" → this URL.

    Two-step capture: the "Need Changes" quick-reply creates an
    awaiting_details row and the bot asks for specifics; the sender's next
    text message fills it in. Always returns 200 — WATI retries non-200s.
    """
    try:
        data = await request.json()
    except Exception:
        return {"ok": True}
    if data.get("owner") is True:  # our own outbound messages echo back too
        return {"ok": True}
    phone = re.sub(r"\D", "", str(data.get("waId") or ""))
    text = str(data.get("text") or "").strip()
    if not phone or not text:
        return {"ok": True}

    emp = (db.query(Tgt26Pass)
             .filter(Tgt26Pass.mobile == phone[-10:])
             .first())

    if text.lower() in ("need changes", "need change"):
        db.add(Tgt26ChangeRequest(
            phone=phone, employee_name=emp.name if emp else None,
            pass_id=emp.pass_id if emp else None, status="awaiting_details"))
        db.commit()
        _send_session_text(
            phone,
            "Sure! Please reply with the changes required in your pass "
            "(family member additions or removals, name corrections, etc.). "
            "Our HR team will review and send you an updated pass.", db)
        return {"ok": True}

    open_req = (db.query(Tgt26ChangeRequest)
                  .filter_by(phone=phone, status="awaiting_details")
                  .order_by(Tgt26ChangeRequest.id.desc())
                  .first())
    if open_req:
        open_req.requested_change = text[:2000]
        open_req.status = "received"
        open_req.received_at = datetime.utcnow()
        db.commit()
        _send_session_text(
            phone,
            "Thank you. Your change request has been recorded and forwarded to "
            "the HR team. You will receive your updated pass shortly.", db)
    return {"ok": True}


# --------------------------------------------------------------------- admin
@router.get("/tgt26/change-requests", response_class=HTMLResponse)
def change_requests(db: Session = Depends(get_db),
                    user: Employee = Depends(require_admin)):
    rows = (db.query(Tgt26ChangeRequest)
              .order_by(Tgt26ChangeRequest.created_at.desc()).all())
    trs = "".join(
        f"<tr>"
        f"<td style='padding:8px 10px;border-bottom:1px solid #EAF1F9;white-space:nowrap'>"
        f"{(r.created_at + IST).strftime('%d-%b %I:%M %p')}</td>"
        f"<td style='padding:8px 10px;border-bottom:1px solid #EAF1F9'>{r.employee_name or '?'}</td>"
        f"<td style='padding:8px 10px;border-bottom:1px solid #EAF1F9'>{r.phone}</td>"
        f"<td style='padding:8px 10px;border-bottom:1px solid #EAF1F9'>"
        f"{r.requested_change or '<i>(awaiting details)</i>'}</td>"
        f"<td style='padding:8px 10px;border-bottom:1px solid #EAF1F9'>{r.status}</td></tr>"
        for r in rows) or "<tr><td style='padding:16px'>No change requests yet.</td></tr>"
    return _page("info", f"CHANGE REQUESTS ({len(rows)})",
                 "<div style='overflow-x:auto'><table style='width:100%;"
                 "border-collapse:collapse;font-size:14px'>"
                 "<tr><th style='padding:8px 10px;text-align:left'>Time</th>"
                 "<th style='padding:8px 10px;text-align:left'>Name</th>"
                 "<th style='padding:8px 10px;text-align:left'>Phone</th>"
                 "<th style='padding:8px 10px;text-align:left'>Request</th>"
                 "<th style='padding:8px 10px;text-align:left'>Status</th></tr>"
                 f"{trs}</table></div>")


@router.get("/tgt26/send", response_class=HTMLResponse)
def send_console(db: Session = Depends(get_db),
                 user: Employee = Depends(require_admin)):
    """Tiny admin console so the send can be driven from a browser: dry run,
    test send to one number, then the full broadcast. Wraps /tgt26/send-passes."""
    total = db.query(Tgt26Pass).count()
    pending = db.query(Tgt26Pass).filter(Tgt26Pass.pass_sent_at.is_(None)).count()
    body = f"""
<div style="padding:20px">
<p style="margin:0 0 14px;color:#5B6B80">Register: <b>{total}</b> passes,
<b>{pending}</b> not yet sent. WATI configured: <b>{wati.configured()}</b>.</p>
<div style="display:grid;gap:10px">
 <button onclick="run('?dry_run=true')" style="padding:12px;border:1px solid #0069A6;
   background:#fff;color:#0069A6;border-radius:8px;font-weight:700;cursor:pointer">
   1. Dry run — list recipients (sends nothing)</button>
 <div style="display:flex;gap:8px">
  <input id=testnum value="7395956648" style="flex:1;padding:12px;border:1px solid
    #C9D8EA;border-radius:8px" placeholder="10-digit mobile">
  <button onclick="run('?dry_run=false&resend=true&only='+document.getElementById('testnum').value)"
    style="padding:12px 16px;background:#436C8A;color:#fff;border:0;border-radius:8px;
    font-weight:700;cursor:pointer">2. Send TEST</button>
 </div>
 <button onclick="if(confirm('Send the pass to ALL pending employees?'))run('?dry_run=false')"
   style="padding:12px;background:#0069A6;color:#fff;border:0;border-radius:8px;
   font-weight:700;cursor:pointer">3. Send to ALL pending</button>
</div>
<pre id=out style="background:#F5F8FC;border:1px solid #EAF1F9;border-radius:8px;
  padding:12px;margin-top:14px;white-space:pre-wrap;font-size:12px">Results appear here.</pre>
</div>
<script>
async function run(qs) {{
  const out = document.getElementById('out');
  out.textContent = 'Working...';
  const r = await fetch('/tgt26/send-passes' + qs, {{method: 'POST'}});
  out.textContent = JSON.stringify(await r.json(), null, 2);
}}
</script>"""
    return _page("info", "SEND EVENT PASSES", body)


@router.post("/tgt26/send-passes")
def send_passes(dry_run: bool = True, resend: bool = False,
                only: str | None = None,
                db: Session = Depends(get_db),
                user: Employee = Depends(require_admin)):
    """Broadcast the pass template via the portal's own WATI client — no CSV
    upload or attribute mapping in the WATI dashboard needed. Named params must
    match the template variables exactly: {{name}}, {{total}}, and the dynamic
    button suffix {{pass_file}}.

    Safe by default: dry_run=true only reports who WOULD be messaged.
    ?only=7395956648 restricts to one mobile — use this for the test send
    before the full broadcast. Already-sent employees are skipped unless
    ?resend=true (a test recipient needs resend=true to receive the real
    broadcast later). Every attempt lands in wa_log.
    """
    q = db.query(Tgt26Pass).order_by(Tgt26Pass.sno)
    if only:
        digits = re.sub(r"\D", "", only)[-10:]
        q = q.filter(Tgt26Pass.mobile == digits)
    if not resend:
        q = q.filter(Tgt26Pass.pass_sent_at.is_(None))
    targets = q.all()
    if dry_run:
        return {"dry_run": True, "would_send": len(targets),
                "template": TGT26_TPL, "configured": wati.configured(),
                "recipients": [{"sno": p.sno, "name": p.name, "mobile": p.mobile}
                               for p in targets]}
    sent = failed = 0
    for p in targets:
        ok = wati.send_template(p.mobile, TGT26_TPL,
                                {"name": p.name,
                                 "total": str(p.total_attendees),
                                 "pass_file": f"{p.pass_id}.png"}, db=db)
        if ok:
            p.pass_sent_at = datetime.utcnow()
            sent += 1
        else:
            failed += 1
        db.commit()
    return {"dry_run": False, "sent": sent, "failed": failed,
            "template": TGT26_TPL}
