"""Cron endpoints — replaces the in-process APScheduler for serverless (Vercel).

Vercel Cron (configured in vercel.json) calls these on schedule and automatically
sends `Authorization: Bearer $CRON_SECRET` when the CRON_SECRET env var is set
on the project. We verify that header before doing anything.

Two guards:
- CRON_SECRET   → required in production; requests without it are rejected.
- CRON_ENABLED  → set to "true" only after cutover. During the parallel run the
                  old kpis.metfraa.com service still runs APScheduler, so these
                  endpoints no-op to avoid duplicate emails.
"""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/cron", tags=["cron"])


def _authorize(request: Request) -> None:
    secret = os.getenv("CRON_SECRET", "")
    if not secret:
        # No secret configured — only allow in non-production for local testing
        if os.getenv("APP_ENV", "development") == "production":
            raise HTTPException(status_code=503, detail="CRON_SECRET not configured")
        return
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Invalid cron authorization")


def _enabled() -> bool:
    return os.getenv("CRON_ENABLED", "").lower() in ("1", "true", "yes")


@router.get("/missed-day")
def cron_missed_day(request: Request):
    """Email employees who missed yesterday's entry. Schedule: 10:00 IST daily."""
    _authorize(request)
    if not _enabled():
        log.info("[cron] missed-day skipped — CRON_ENABLED not set (parallel run)")
        return {"status": "skipped", "reason": "CRON_ENABLED not set"}
    from ..services.scheduler import _missed_day_alert

    _missed_day_alert()
    return {"status": "ok", "job": "missed_day_alert"}


@router.get("/daily-task-report")
def cron_daily_task_report(request: Request):
    """Generate + email the daily task Excel. Schedule: 10:00 IST daily."""
    _authorize(request)
    if not _enabled():
        log.info("[cron] daily-task-report skipped — CRON_ENABLED not set (parallel run)")
        return {"status": "skipped", "reason": "CRON_ENABLED not set"}
    from ..services.scheduler import _daily_task_report_job

    _daily_task_report_job()
    return {"status": "ok", "job": "daily_task_report"}


@router.get("/maint-reminder")
def cron_maint_reminder(request: Request, db: Session = Depends(get_db)):
    """Daily pending-maintenance reminder to Ajoy (email + WhatsApp).

    Skips Sundays and holidays and is idempotent per day, so it is safe to ping
    daily (or more often). Driven by .github/workflows/maint-reminder.yml.
    """
    _authorize(request)
    if not _enabled():
        return {"ok": True, "skipped": "cron disabled"}
    from .maint import run_pm_reminder
    return {"ok": True, **run_pm_reminder(db)}


@router.get("/gatepass-overdue")
def cron_gatepass_overdue(request: Request, db: Session = Depends(get_db)):
    """Nudge on gatepasses that were never returned.

    NOT in vercel.json: Hobby plans allow only ONE cron run per day, and a
    daily check is useless for a pass due back at 3pm. Driven instead by
    .github/workflows/gatepass-overdue.yml every 15 minutes, sending
    `Authorization: Bearer $CRON_SECRET` — the same pattern BSC uses for its
    outpass watcher, retry logic included.

    Safe to call as often as you like: each recipient has its own stamp and a
    stamp is only set once a channel actually delivered, so extra runs are
    no-ops and failed sends retry.
    """
    _authorize(request)
    if not _enabled():
        return {"ok": True, "skipped": "cron disabled"}
    from .gatepass import run_overdue_check
    return {"ok": True, **run_overdue_check(db)}


# IST is UTC+05:30; WaLog.created_at is stored naive-UTC.
from datetime import datetime, timedelta, timezone  # noqa: E402

_IST = timezone(timedelta(hours=5, minutes=30))


# Marker written to wa_log on a successful month-end email, so the once-a-month
# idempotency check needs no extra table.
_REORDER_REPORT_MARK = "spare_reorder_report_email"


def _reorder_report(db: Session, force: bool = False) -> dict:
    """Month-end consolidated reorder report to maintenance (Ajoy), by EMAIL.

    Lists every spare part currently in REORDER NOW status and emails one
    summary to the maintenance inbox (MAINT_REMINDER_EMAIL, default
    maintenance@metfraa.com — the same address that gets the daily reminder, so
    no WhatsApp template and no new scheduling secret are needed). Fires once, on
    the LAST day of the month from 3pm IST onward; idempotent per month (a
    'sent' marker in wa_log this month blocks re-send). `force=1` bypasses the
    day/time gate and the once-a-month guard for on-demand testing.
    """
    from ..models import MaintSparePart, WaLog
    from ..services import email_service as _email

    now_ist = datetime.now(_IST)
    is_last_day = (now_ist + timedelta(days=1)).month != now_ist.month

    if not force:
        if not is_last_day:
            return {"status": "skipped", "reason": "not month-end",
                    "date_ist": now_ist.strftime("%Y-%m-%d %H:%M")}
        if now_ist.hour < 15:
            return {"status": "skipped", "reason": "before 3pm IST",
                    "date_ist": now_ist.strftime("%Y-%m-%d %H:%M")}
        # Once per calendar month: skip if we already logged a successful send.
        month_start = (now_ist.replace(day=1, hour=0, minute=0, second=0,
                                       microsecond=0)
                       .astimezone(timezone.utc).replace(tzinfo=None))
        already = (db.query(WaLog)
                   .filter(WaLog.template == _REORDER_REPORT_MARK,
                           WaLog.result == "sent",
                           WaLog.created_at >= month_start)
                   .first())
        if already:
            return {"status": "skipped", "reason": "already sent this month"}

    # Collect everything currently at/under its minimum.
    parts = (db.query(MaintSparePart)
             .filter(MaintSparePart.active == True)  # noqa: E712
             .order_by(MaintSparePart.machine, MaintSparePart.part_name).all())
    low = []
    for p in parts:
        current = (p.opening_qty or 0) + (p.qty_in or 0) - (p.qty_out or 0)
        if current <= (p.min_stock_level or 0):
            low.append((p, current))

    month = now_ist.strftime("%B %Y")
    if not low:
        return {"status": "ok", "month": month, "reorder_count": 0, "sent": 0,
                "forced": force, "note": "no parts need reorder"}

    def _fmt(n):
        n = round(n or 0, 2)
        return str(int(n)) if n == int(n) else str(n)

    def _esc(s):
        return (str(s or "")
                .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    rows_html, rows_txt = [], []
    for i, (p, cur) in enumerate(low, 1):
        rows_html.append(
            "<tr>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0'>{i}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0'>{_esc(p.part_name)}"
            + (f"<br><span style='color:#94a3b8;font-size:11px'>{_esc(p.part_code)}</span>" if p.part_code else "")
            + "</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0'>{_esc(p.machine) or '-'}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;text-align:right;color:#dc2626;font-weight:700'>{_fmt(cur)}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;text-align:right'>{_fmt(p.min_stock_level)}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0'>{_esc(p.supplier) or '-'}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0'>{_esc(p.store_location) or '-'}</td>"
            "</tr>")
        code = (p.part_code + " ") if p.part_code else ""
        mc = f" ({p.machine})" if p.machine else ""
        rows_txt.append(f"{i}. {code}{p.part_name}{mc} — stock {_fmt(cur)} / min {_fmt(p.min_stock_level)}")

    html = (
        "<div style='font-family:Arial,Helvetica,sans-serif;color:#0d1421;max-width:760px'>"
        f"<p>Good afternoon Ajoy,</p>"
        f"<p><b>{len(low)} spare part(s)</b> are at or below their minimum stock level "
        f"as of month-end (<b>{month}</b>) and need reordering:</p>"
        "<table style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<thead><tr style='background:#0A2B66;color:#fff'>"
        "<th style='padding:6px 10px;border:1px solid #0A2B66;text-align:left'>#</th>"
        "<th style='padding:6px 10px;border:1px solid #0A2B66;text-align:left'>Part</th>"
        "<th style='padding:6px 10px;border:1px solid #0A2B66;text-align:left'>Machine</th>"
        "<th style='padding:6px 10px;border:1px solid #0A2B66;text-align:right'>Stock</th>"
        "<th style='padding:6px 10px;border:1px solid #0A2B66;text-align:right'>Min</th>"
        "<th style='padding:6px 10px;border:1px solid #0A2B66;text-align:left'>Supplier</th>"
        "<th style='padding:6px 10px;border:1px solid #0A2B66;text-align:left'>Store location</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
        "<p style='margin-top:14px'>Full details are in the Maintenance portal under "
        "<a href='https://app.metfraa.com/maint'>Spare Parts</a>.</p>"
        "<p style='color:#94a3b8;font-size:12px'>Metfraa Steel Buildings — automated month-end reorder summary.</p>"
        "</div>")
    text = (f"Month-end spare parts reorder summary — {month}\n"
            f"{len(low)} part(s) at or below minimum:\n\n" + "\n".join(rows_txt))

    to = os.getenv("MAINT_REMINDER_EMAIL", "maintenance@metfraa.com")
    subject = f"Spare parts to reorder — {month} ({len(low)})"
    sent = 0
    try:
        if _email.send_email(to, subject, html, text):
            sent = 1
            try:
                db.add(WaLog(phone=to[:32], template=_REORDER_REPORT_MARK,
                             result="sent", detail=f"{len(low)} parts",
                             created_at=datetime.utcnow()))
                db.commit()
            except Exception:
                db.rollback()
    except Exception:
        log.warning("[cron] reorder report email failed", exc_info=True)

    return {"status": "ok", "month": month, "reorder_count": len(low),
            "to": to, "sent": sent, "forced": force}


@router.get("/spare-reorder-report")
def cron_spare_reorder_report(request: Request, force: int = 0,
                              db: Session = Depends(get_db)):
    """Month-end spare-parts reorder summary emailed to maintenance (Ajoy).

    NOT in vercel.json (Hobby caps crons at 2, both used). Driven by
    .github/workflows/spare-reorder-report.yml, which pings hourly reusing the
    existing CRON_SECRET; the endpoint self-gates to the last day of the month
    from 3pm IST and is idempotent per month, so frequent pings are safe.
    `?force=1` sends immediately for testing.
    """
    _authorize(request)
    if not _enabled():
        return {"ok": True, "skipped": "cron disabled"}
    return {"ok": True, **_reorder_report(db, force=bool(force))}


# ----------------------------------------- month-start maintenance review email
_REVIEW_REPORT_MARK = "maint_review_report_email"


def _review_report(db: Session, force: bool = False) -> dict:
    """Email the graphical Breakdown Maintenance Review at the START of the month.

    Goes to MAINT_REVIEW_EMAIL (default MAINT_REMINDER_EMAIL,
    maintenance@metfraa.com). Fires on the 1st of the month from 9am IST onward;
    idempotent per month via a wa_log marker. `force=1` sends immediately.
    """
    from ..models import WaLog
    from ..services import email_service as _email
    from ..maint_review_report import build_email

    now_ist = datetime.now(_IST)
    if not force:
        if now_ist.day != 1:
            return {"status": "skipped", "reason": "not month-start",
                    "date_ist": now_ist.strftime("%Y-%m-%d %H:%M")}
        if now_ist.hour < 9:
            return {"status": "skipped", "reason": "before 9am IST",
                    "date_ist": now_ist.strftime("%Y-%m-%d %H:%M")}
        month_start = (now_ist.replace(day=1, hour=0, minute=0, second=0,
                                       microsecond=0)
                       .astimezone(timezone.utc).replace(tzinfo=None))
        already = (db.query(WaLog)
                   .filter(WaLog.template == _REVIEW_REPORT_MARK,
                           WaLog.result == "sent",
                           WaLog.created_at >= month_start)
                   .first())
        if already:
            return {"status": "skipped", "reason": "already sent this month"}

    subject, html, text = build_email()
    to = (os.getenv("MAINT_REVIEW_EMAIL")
          or os.getenv("MAINT_REMINDER_EMAIL", "maintenance@metfraa.com"))
    sent = 0
    try:
        if _email.send_email(to, subject, html, text):
            sent = 1
            try:
                db.add(WaLog(phone=to[:32], template=_REVIEW_REPORT_MARK,
                             result="sent", detail="review report",
                             created_at=datetime.utcnow()))
                db.commit()
            except Exception:
                db.rollback()
    except Exception:
        log.warning("[cron] review report email failed", exc_info=True)
    return {"status": "ok", "to": to, "sent": sent, "forced": force}


@router.get("/maint-review-report")
def cron_maint_review_report(request: Request, force: int = 0,
                             db: Session = Depends(get_db)):
    """Month-start Breakdown Maintenance Review emailed to maintenance.

    Pinged hourly by the same workflow as the reorder report (reusing
    CRON_SECRET); self-gates to the 1st of the month from 9am IST and is
    idempotent per month. `?force=1` sends immediately for testing.
    """
    _authorize(request)
    if not _enabled():
        return {"ok": True, "skipped": "cron disabled"}
    return {"ok": True, **_review_report(db, force=bool(force))}
