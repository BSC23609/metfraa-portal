"""WATI (WhatsApp Business API) client — ported from the BSC Tickets Portal.

Every guard in here exists because BSC hit the failure in production:

  * WATI returns HTTP 200 even when it refuses to send (template not found,
    parameter mismatch, number not on WhatsApp). The real outcome is in the
    JSON body's `result` / `validWhatsAppNumber`, so a 200 is NOT success.
  * A blank template parameter makes WATI reject the whole message with
    "cannot have blank text" — every value falls back to '-'.
  * WATI rejects params containing newlines, tabs or runs of spaces.
  * An unbounded request can hang for minutes; on Vercel that burns the whole
    function budget and surfaces as a 504 on the cron. Hard timeout, always.
  * Every attempt is logged so a silent failure is visible afterwards, which
    is how BSC eventually found HR had never received a single alert.

Templates must be created in WATI as CATEGORY = UTILITY, or Meta's marketing
frequency cap will quietly throttle them. See docs/WATI_TEMPLATES_METFRAA.md
for the exact body text and variable names to register — the parameter names
below must match the template variables EXACTLY or WATI declines the send.
"""
import logging
import os
import re
from datetime import datetime

import httpx

log = logging.getLogger(__name__)


def _base() -> str:
    return (os.getenv("WATI_BASE_URL") or "").rstrip("/")


def _token() -> str:
    return os.getenv("WATI_TOKEN") or ""


def configured() -> bool:
    return bool(_base() and _token())


# Metfraa's own templates — the BSC ones carry BSC branding and live in a
# different WATI account. Names default to met_* and can be overridden per
# environment if Meta approval lands under a different name.
TPL = {
    "request": lambda: os.getenv("WATI_OUTPASS_REQUEST_TPL", "met_outpass_request"),
    "approved": lambda: os.getenv("WATI_OUTPASS_APPROVED_TPL", "met_outpass_approved"),
    "rejected": lambda: os.getenv("WATI_OUTPASS_REJECTED_TPL", "met_outpass_rejected"),
    "overdue": lambda: os.getenv("WATI_OVERDUE_TPL", "met_outpass_overdue"),
    "return_reminder": lambda: os.getenv("WATI_RETURN_REMINDER_TPL",
                                         "met_gatepass_return_reminder"),
}


def normalize_phone(raw) -> str:
    """Indian mobiles arrive in every shape; WATI wants digits with country code."""
    p = re.sub(r"\D", "", str(raw or ""))
    if not p:
        return ""
    if len(p) == 10:
        return "91" + p
    if len(p) == 11 and p.startswith("0"):
        return "91" + p[1:]
    return p


def clean_param(v) -> str:
    """WATI rejects newlines, tabs and long space runs inside parameters."""
    return re.sub(r"\s+", " ", str("" if v is None else v)).strip()


def _log_attempt(db, phone: str, template: str, result: str, detail: str = "") -> None:
    """Best-effort audit row. Logging must never break or slow a send."""
    try:
        from ..models import WaLog
        db.add(WaLog(phone=str(phone or "")[:32], template=str(template or "")[:64],
                     result=result, detail=str(detail or "")[:500],
                     created_at=datetime.utcnow()))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def send_template(phone, template_name: str, params: dict, db=None) -> bool:
    """Send one WATI template. Returns True only if WATI actually accepted it."""
    original = phone
    phone = normalize_phone(phone)
    if not phone:
        log.warning("[wati] no phone for %s", template_name)
        if db is not None:
            _log_attempt(db, original, template_name, "no_phone", "empty/invalid number")
        return False

    # Blank values make WATI reject the entire message — always substitute.
    parameters = [{"name": k, "value": clean_param(v) or "-"} for k, v in params.items()]

    if not configured():
        log.info("[wati] (not configured) would send %s to %s: %s",
                 template_name, phone, params)
        if db is not None:
            _log_attempt(db, phone, template_name, "skipped", "WATI not configured")
        return False

    tok = _token()
    headers = {"Authorization": tok if tok.startswith("Bearer") else f"Bearer {tok}",
               "Content-Type": "application/json"}
    url = f"{_base()}/api/v1/sendTemplateMessage"
    timeout = float(os.getenv("WATI_TIMEOUT_MS", "8000")) / 1000.0
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, headers=headers,
                            params={"whatsappNumber": phone},
                            json={"template_name": template_name,
                                  "broadcast_name": template_name,
                                  "parameters": parameters})
        text = r.text or ""
        if r.status_code >= 400:
            log.warning("[wati] %s -> %s %s", template_name, r.status_code, text[:300])
            if db is not None:
                _log_attempt(db, phone, template_name, "http_error",
                             f"{r.status_code} {text[:300]}")
            return False
        # A 200 is not success — WATI reports refusal inside the body.
        try:
            body = r.json()
        except Exception:
            body = None
        if body and (body.get("result") in (False, "false")
                     or body.get("validWhatsAppNumber") is False):
            log.warning("[wati] %s -> declined: %s", template_name, text[:300])
            if db is not None:
                _log_attempt(db, phone, template_name, "declined", text[:300])
            return False
        if db is not None:
            _log_attempt(db, phone, template_name, "sent", "")
        return True
    except httpx.TimeoutException:
        log.warning("[wati] %s -> timed out", template_name)
        if db is not None:
            _log_attempt(db, phone, template_name, "error", "timed out")
        return False
    except Exception as e:
        log.warning("[wati] send failed: %s", e)
        if db is not None:
            _log_attempt(db, phone, template_name, "error", str(e)[:300])
        return False


# ---------------------------------------------------------------- wrappers
# Parameter NAMES must match the template variables in WATI exactly.

def _type_label(o) -> str:
    return "Gatepass" if o.type == "gatepass" else "Outpass"


def outpass_request(approver, o, db=None) -> bool:
    return send_template(approver.phone, TPL["request"](), {
        "name": approver.name, "ref": o.ref_no,
        "requester": o.requester.name if o.requester else "-",
        "type": _type_label(o), "purpose": o.purpose or "-",
        "date": o.req_date.strftime("%d %b %Y") if o.req_date else "-",
        "out_time": o.out_time or "-",
        # Dynamic button suffix: the template's URL is
        #   https://app.metfraa.com/oga/{{token}}  (approve)
        #   https://app.metfraa.com/ogr/{{token}}  (reject)
        "token": o.action_token or "-",
    }, db)


def outpass_approved(o, db=None) -> bool:
    req = o.requester
    return send_template(req.phone if req else None, TPL["approved"](), {
        "name": req.name if req else "-", "ref": o.ref_no, "type": _type_label(o),
        "approver": o.actioned_by_name or "-",
        # Button URL: https://app.metfraa.com/dl/{{token}} — the approved pass PDF
        "token": o.pdf_token or "-",
    }, db)


def outpass_rejected(o, db=None) -> bool:
    req = o.requester
    return send_template(req.phone if req else None, TPL["rejected"](), {
        "name": req.name if req else "-", "ref": o.ref_no, "type": _type_label(o),
        "approver": o.actioned_by_name or "-", "reason": o.reject_reason or "-",
    }, db)


def outpass_overdue(to_name: str, to_phone, o, overdue_min: int, db=None) -> bool:
    return send_template(to_phone, TPL["overdue"](), {
        "name": to_name or "Sir",
        "employee": o.requester.name if o.requester else "-",
        "ref": o.ref_no, "out_time": o.out_time or "-",
        "expected": o.in_time or "-", "overdue_min": str(overdue_min),
        "purpose": o.purpose or "-",
        "duty": "On duty" if o.on_duty else "Personal",
    }, db)


def gatepass_return_reminder(o, overdue_min: int, db=None) -> bool:
    req = o.requester
    return send_template(req.phone if req else None, TPL["return_reminder"](), {
        "name": req.name if req else "-", "ref": o.ref_no,
        "out_time": o.out_time or "-", "expected": o.in_time or "-",
        "overdue_min": str(overdue_min),
        # Button URL: https://app.metfraa.com/ogb/{{token}} — one tap records
        # the return, so nobody has to open the portal to close a pass.
        "token": o.return_token or "-",
    }, db)
