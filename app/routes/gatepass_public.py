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

from fastapi import APIRouter, Depends, Request
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
    # An approved pass never changes, so let the phone keep it. Re-opening the
    # WhatsApp link then costs nothing instead of a fresh round trip on mobile
    # data — which is most of what "takes forever" actually is.
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"',
                             "Cache-Control": "private, max-age=604800, immutable"})


@router.get("/ogb/{token}", response_class=HTMLResponse)
def one_tap_return_page(token: str, db: Session = Depends(get_db)):
    """The "I'm back" button opens this. It asks the browser for a location and
    posts it to /ogb/{token}/confirm, so the return can be checked against the
    gate geofence — the same verification BSC does from its QR poster.

    If location is refused or unavailable the pass STILL closes, flagged
    unverified. Blocking the close would recreate the very problem this exists
    to fix: passes left open because recording a return was a hassle.
    """
    o = (db.query(OutpassRequest)
         .filter(OutpassRequest.return_token == token).first())
    if not o:
        return _page("⛔", "Link not valid",
                     "This link is not recognised, or the return was already "
                     "recorded.", 404)
    if o.returned_at:
        when = (o.returned_at + IST).strftime("%d %b, %I:%M %p")
        return _page("✅", "Already recorded",
                     f"Your return was already recorded at {when}.")
    if o.status != "approved":
        return _page("⛔", "Not an open pass", f"This pass is {o.status}.")

    name = o.requester.name if o.requester else "there"
    return HTMLResponse(f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Record your return</title></head>
<body style="margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f9">
<div style="max-width:440px;margin:10vh auto;background:#fff;border:1px solid #d6dde6;
            border-radius:16px;padding:32px 24px;text-align:center">
  <div id="ico" style="font-size:56px;line-height:1">📍</div>
  <h2 id="ttl" style="color:#0d1421;margin:.5em 0 .2em">Hi {name}</h2>
  <p id="msg" style="color:#6b7689;font-size:15px;margin:0">
    Checking your location so your return can be confirmed at the gate…</p>
  <p style="color:#8e9aad;font-size:12px;margin-top:20px">Metfraa Portal</p>
</div>
<script>
  var done = false;
  function show(ico, ttl, msg) {{
    document.getElementById('ico').textContent = ico;
    document.getElementById('ttl').textContent = ttl;
    document.getElementById('msg').textContent = msg;
  }}
  function send(body) {{
    if (done) return; done = true;
    fetch('/ogb/{token}/confirm', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(body)
    }}).then(function (r) {{ return r.json(); }})
      .then(function (d) {{
        if (!d.ok) return show(d.too_far ? '📍' : '⚠️',
                               d.too_far ? 'Not at the gate' : 'Could not record',
                               d.error || 'Please try the portal.');
        show(d.verified ? '✅' : '⚠️', 'Return recorded', d.message);
      }})
      .catch(function () {{ show('⚠️', 'Could not record',
        'Please record your return in the portal instead.'); }});
  }}
  if (!navigator.geolocation) {{ send({{}}); }}
  else {{
    // Don't leave someone staring at a spinner if the fix never arrives.
    var t = setTimeout(function () {{ send({{}}); }}, 12000);
    navigator.geolocation.getCurrentPosition(
      function (p) {{ clearTimeout(t); send({{lat: p.coords.latitude,
        lng: p.coords.longitude, accuracy: p.coords.accuracy}}); }},
      function () {{ clearTimeout(t); send({{}}); }},
      {{enableHighAccuracy: true, timeout: 10000, maximumAge: 0}});
  }}
</script>
</body></html>""")


@router.post("/ogb/{token}/confirm")
async def one_tap_return_confirm(token: str, request: Request,
                                 db: Session = Depends(get_db)):
    try:
        o = (db.query(OutpassRequest)
             .filter(OutpassRequest.return_token == token).first())
        if not o:
            return {"ok": False, "error": "This link is no longer valid."}
        if o.returned_at:
            when = (o.returned_at + IST).strftime("%d %b, %I:%M %p")
            return {"ok": True, "verified": bool(o.return_verified),
                    "message": f"Already recorded at {when}."}
        if o.status != "approved":
            return {"ok": False, "error": f"This pass is {o.status}."}

        body = {}
        try:
            body = await request.json() or {}
        except Exception:
            pass

        def _num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        lat, lng = _num(body.get("lat")), _num(body.get("lng"))
        acc = _num(body.get("accuracy"))

        from .gatepass import apply_return, check_geofence, require_gps
        name = o.requester.name if o.requester else "Employee"

        # Check BEFORE recording: if the geofence is enforced, a return from
        # outside it must not close the pass at all.
        geo = check_geofence(lat, lng, acc)
        if require_gps() and not geo["verified"]:
            if geo["distance_m"] is not None:
                why = (f"You appear to be {geo['distance_m']} m from the gate. "
                       "Please try again once you're back at the gate.")
            elif geo["reason"] == "gate location not configured":
                why = ("The gate location hasn't been set up yet, so your return "
                       "can't be confirmed. Please ask HR to record it.")
            else:
                why = ("Your location couldn't be read. Please allow location "
                       "access and try again at the gate, or ask HR to record "
                       "your return.")
            return {"ok": False, "error": why, "distance_m": geo["distance_m"],
                    "too_far": geo["distance_m"] is not None}

        geo = apply_return(db, o, name, via="gps" if lat is not None else "self",
                           lat=lat, lng=lng, accuracy=acc)

        when = (o.returned_at + IST).strftime("%d %b, %I:%M %p")
        late = ""
        if o.expected_back_at and o.returned_at > o.expected_back_at:
            mins = int((o.returned_at - o.expected_back_at).total_seconds() // 60)
            hrs, mins = divmod(mins, 60)
            late = (" — " + (f"{hrs}h {mins}m" if hrs else f"{mins}m")
                    + " past your in-time")
        if geo["verified"]:
            msg = f"Confirmed at the gate at {when}{late}."
        else:
            # Only reachable with GATEPASS_REQUIRE_GPS=false.
            why = geo["reason"] or "location unavailable"
            msg = (f"Recorded at {when}{late}. Location could not be confirmed "
                   f"({why}), so this shows as unverified for HR.")
        return {"ok": True, "verified": geo["verified"], "message": msg,
                "distance_m": geo["distance_m"]}
    except Exception:
        log.error("[ogb] return confirm failed", exc_info=True)
        return {"ok": False, "error": "Something went wrong. Please use the portal."}
