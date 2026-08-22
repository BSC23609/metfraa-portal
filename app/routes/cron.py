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
