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


def _reorder_report(db: Session, force: bool = False) -> dict:
    """Month-end consolidated reorder report to maintenance (Ajoy).

    Lists every spare part currently in REORDER NOW status and WhatsApps a
    single summary to the maintenance number(s). Fires once, on the LAST day of
    the month from 3pm IST onward; idempotent per month (a WATI 'sent' row for
    the report template this month blocks re-send). `force=1` bypasses the day /
    time gate and the once-a-month guard for on-demand testing.
    """
    from ..models import MaintSparePart, WaLog
    from ..services import wati as _wati
    from .spares import _maint_mobiles

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
                   .filter(WaLog.template == _wati.TPL["spare_reorder_report"](),
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

    def _fmt(n):
        n = round(n or 0, 2)
        return str(int(n)) if n == int(n) else str(n)

    items = []
    for p, cur in low:
        code = (p.part_code + " ") if p.part_code else ""
        mc = f" ({p.machine})" if p.machine else ""
        items.append(f"{code}{p.part_name}{mc} {_fmt(cur)}/{_fmt(p.min_stock_level)}")

    # One line only — WATI rejects newlines in a parameter. Clamp length so the
    # template parameter stays within WhatsApp's limit.
    line, shown = "", 0
    for it in items:
        piece = (("; " if line else "") + it)
        if len(line) + len(piece) > 850:
            break
        line += piece
        shown += 1
    if shown < len(items):
        line += f"; …+{len(items) - shown} more"
    parts_text = line or "None — all parts above minimum."

    month = now_ist.strftime("%b %Y")
    mobiles = _maint_mobiles()
    sent = 0
    for phone in mobiles:
        try:
            if _wati.spare_reorder_report(phone, month, len(low), parts_text, db):
                sent += 1
        except Exception:
            log.warning("[cron] reorder report send failed for %s", phone,
                        exc_info=True)
    return {"status": "ok", "month": month, "reorder_count": len(low),
            "recipients": len(mobiles), "sent": sent, "forced": force}


@router.get("/spare-reorder-report")
def cron_spare_reorder_report(request: Request, force: int = 0,
                              db: Session = Depends(get_db)):
    """Month-end spare-parts reorder summary to maintenance (Ajoy).

    NOT in vercel.json (Hobby caps crons at 2, both used). Driven by
    .github/workflows/spare-reorder-report.yml, which pings hourly; the endpoint
    self-gates to the last day of the month from 3pm IST and is idempotent per
    month, so frequent pings are safe. `?force=1` sends immediately for testing.
    """
    _authorize(request)
    if not _enabled():
        return {"ok": True, "skipped": "cron disabled"}
    return {"ok": True, **_reorder_report(db, force=bool(force))}
