"""One-tap approve/reject from a WhatsApp button, and the pass PDF link.

Ported from BSC. These live at the app ROOT (/oga, /ogr, /dl) rather than under
/gatepass because a WhatsApp template's dynamic button may only vary in its LAST
path segment — the rest of the URL is fixed at template-approval time. Short
paths also keep the visible link tidy.

There is deliberately NO login here: the unguessable token is the authorisation.
An approver taps a button on their phone at a gate; forcing a session there would
mean the feature simply goes unused. The token is single-use (cleared on action)
and dies with the pass date.
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import OutpassRequest

router = APIRouter(tags=["gatepass-public"])
log = logging.getLogger(__name__)
IST = timedelta(hours=5, minutes=30)


def _page(emoji: str, title: str, msg: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(status_code=status, content=f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title></head>
<body style="margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f9">
<div style="max-width:440px;margin:12vh auto;background:#fff;border:1px solid #d6dde6;
            border-radius:16px;padding:32px 24px;text-align:center">
  <div style="font-size:56px;line-height:1">{emoji}</div>
  <h2 style="color:#0d1421;margin:.5em 0 .2em">{title}</h2>
  <p style="color:#6b7689;font-size:15px;margin:0">{msg}</p>
  <p style="color:#8e9aad;font-size:12px;margin-top:20px">Metfraa Portal</p>
</div></body></html>""")


def _load(db: Session, token: str):
    return (db.query(OutpassRequest)
            .filter(OutpassRequest.action_token == token).first())


def _expired(req_date) -> bool:
    """A pass is dead once its date has passed — approving yesterday's outpass
    tomorrow is meaningless and would confuse the overdue watcher."""
    if not req_date:
        return False
    return req_date < (datetime.utcnow() + IST).date()


def _type_name(t: str) -> str:
    return "gate pass" if t == "gatepass" else "outpass"


def _guard(o):
    """Shared preconditions for both actions. Returns a page, or None to proceed."""
    if not o:
        return _page("⛔", "Link not valid",
                     "This approval link is not recognised.", 404)
    if o.status != "pending":
        return _page("✅" if o.status == "approved" else "⛔",
                     f"Already {o.status}",
                     f"This request was already {o.status}"
                     + (f" by {o.actioned_by_name}" if o.actioned_by_name else "") + ".")
    if _expired(o.req_date):
        return _page("🕒", "Link expired",
                     "The date on this pass has already passed.")
    return None


@router.get("/oga/{token}", response_class=HTMLResponse)
def one_tap_approve(token: str, db: Session = Depends(get_db)):
    try:
        o = _load(db, token)
        blocked = _guard(o)
        if blocked:
            return blocked
        from .gatepass import apply_approve
        apply_approve(db, o, o.approver_id,
                      (o.approver.name if o.approver else None) or o.approver_label
                      or "Approver")
        who = o.requester.name if o.requester else "The employee"
        return _page("✅", "Approved",
                     f"{who}'s {_type_name(o.type)} is approved. "
                     "The pass has been sent to them on WhatsApp.")
    except Exception:
        log.error("[oga] one-tap approve failed", exc_info=True)
        return _page("⚠️", "Something went wrong",
                     "Please try again, or use the portal.", 500)


@router.get("/ogr/{token}", response_class=HTMLResponse)
def one_tap_reject(token: str, db: Session = Depends(get_db)):
    try:
        o = _load(db, token)
        blocked = _guard(o)
        if blocked:
            return blocked
        from .gatepass import apply_reject
        apply_reject(db, o, o.approver_id,
                     (o.approver.name if o.approver else None) or o.approver_label
                     or "Approver", None)
        who = o.requester.name if o.requester else "The employee"
        return _page("⛔", "Rejected",
                     f"{who}'s {_type_name(o.type)} has been rejected. "
                     "They have been notified.")
    except Exception:
        log.error("[ogr] one-tap reject failed", exc_info=True)
        return _page("⚠️", "Something went wrong",
                     "Please try again, or use the portal.", 500)


@router.get("/dl/{token}")
def download_pass(token: str, db: Session = Depends(get_db)):
    """The approved pass as a PDF. Opened from the WhatsApp button, shown at
    the gate — so it renders inline rather than downloading."""
    o = (db.query(OutpassRequest)
         .filter(OutpassRequest.pdf_token == token,
                 OutpassRequest.status == "approved").first())
    if not o:
        return _page("⛔", "Pass not found",
                     "This pass link is not valid, or the pass was not approved.", 404)
    try:
        from ..services.outpass_pdf import build_outpass_pdf
        req = o.requester
        pdf = build_outpass_pdf({
            "type": o.type, "on_duty": o.on_duty,
            "date": o.req_date.strftime("%d %b %Y") if o.req_date else "",
            "emp_code": req.employee_code if req else "",
            "name": req.name if req else "",
            "designation": (req.designation if req else "") or "",
            "purpose": o.purpose, "out_time": o.out_time, "in_time": o.in_time,
            "ref_no": o.ref_no, "approver": o.actioned_by_name,
            "approved_at": o.actioned_at_ist or "",
        })
    except Exception:
        log.error("[dl] pass pdf failed for %s", o.ref_no, exc_info=True)
        return _page("⚠️", "Could not generate the pass",
                     "Please try again, or open it from the portal.", 500)
    safe = (o.ref_no or "pass").replace("/", "-")
    name = f"{(o.requester.name if o.requester else 'pass')} {safe}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.get("/ogb/{token}", response_class=HTMLResponse)
def one_tap_return(token: str, db: Session = Depends(get_db)):
    """One-tap "I'm back" from the return-reminder WhatsApp.

    The recorded time is when the button is tapped, which is what we want —
    the alternative is chasing people to open the portal, which is exactly why
    passes were sitting open at BSC. Marking a return you didn't make is the
    same risk as the in-app button, so no extra authorisation is warranted.
    """
    try:
        o = (db.query(OutpassRequest)
             .filter(OutpassRequest.return_token == token).first())
        if not o:
            # Token is cleared once used, so a stale tap is the common case.
            return _page("⛔", "Link not valid",
                         "This link is not recognised, or the return was already "
                         "recorded.", 404)
        if o.returned_at:
            when = (o.returned_at + IST).strftime("%d %b, %I:%M %p")
            return _page("✅", "Already recorded",
                         f"Your return was already recorded at {when}.")
        if o.status != "approved":
            return _page("⛔", "Not an open pass",
                         f"This pass is {o.status}.")
        from .gatepass import apply_return
        name = o.requester.name if o.requester else "Employee"
        apply_return(db, o, name)
        when = (o.returned_at + IST).strftime("%d %b, %I:%M %p")
        late = ""
        if o.expected_back_at and o.returned_at > o.expected_back_at:
            mins = int((o.returned_at - o.expected_back_at).total_seconds() // 60)
            hrs, mins = divmod(mins, 60)
            late = (" (" + (f"{hrs}h {mins}m" if hrs else f"{mins}m")
                    + " past the declared in-time)")
        return _page("✅", "Return recorded",
                     f"Thanks {name} — recorded at {when}{late}. "
                     "Your gatepass is now closed.")
    except Exception:
        log.error("[ogb] one-tap return failed", exc_info=True)
        return _page("⚠️", "Something went wrong",
                     "Please record your return in the portal instead.", 500)
