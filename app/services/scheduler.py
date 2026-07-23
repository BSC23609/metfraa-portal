"""Background scheduler for Metfraa KPI Tracker.

Runs two daily jobs:
1. Missed-day alert   → 10:00 AM IST (skips Sundays)
2. Daily task report  → 10:00 AM IST (skips Sundays) — new in 2B

Both are separate jobs; ordering within the minute is not critical.
Falls back gracefully if APScheduler / dependencies aren't installed.
"""
import logging
import os
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# ---------------- MISSED-DAY ALERT ----------------

def _missed_day_alert():
    """Send email alerts to employees who missed the previous day's entry.

    NOTE: this is a placeholder that dispatches to the existing legacy logic.
    In v2 (post-migration), legacy daily entries are wiped, so this may be
    a no-op — but we keep the cron running for schema compatibility.
    """
    try:
        import pytz
        from ..database import SessionLocal
        from ..models import DailyEntry, Employee
        from .email_service import send_email_async, missed_day_email_html

        IST = pytz.timezone(os.getenv("TIMEZONE", "Asia/Kolkata"))
        base_url = os.getenv("BASE_URL", "https://kpis.metfraa.com").rstrip("/")

        yesterday = datetime.now(IST).date() - timedelta(days=1)
        if yesterday.weekday() == 6:  # Sunday
            log.info(f"[missed-day-cron] {yesterday} was Sunday — skipping.")
            return

        db = SessionLocal()
        try:
            employees = (
                db.query(Employee)
                .filter(Employee.is_active.is_(True))
                .filter(Employee.email.isnot(None))
                .all()
            )
            missed_ids = set(e.id for e in employees)
            submitted_ids = {
                r.employee_id for r in db.query(DailyEntry)
                .filter(DailyEntry.entry_date == yesterday)
                .all()
            }
            missed_ids -= submitted_ids
            if not missed_ids:
                log.info(f"[missed-day-cron] no missed submissions for {yesterday}")
                return

            import asyncio
            loop = asyncio.new_event_loop()
            try:
                for emp in employees:
                    if emp.id not in missed_ids or not emp.email:
                        continue
                    subject = f"Missed KPI entry: {yesterday.strftime('%d %b %Y')}"
                    html = missed_day_email_html(emp.name, yesterday.strftime('%d %b %Y'), base_url)
                    loop.run_until_complete(send_email_async(emp.email, subject, html))
                    log.info(f"[missed-day-cron] emailed {emp.name}")
            finally:
                loop.close()
        finally:
            db.close()
    except Exception as e:
        log.error(f"[missed-day-cron] failed: {e}", exc_info=True)


# ---------------- DAILY TASK REPORT ----------------

def _daily_task_report_job():
    """Dispatch to the daily_task_excel module."""
    try:
        from .daily_task_excel import daily_task_report_job
        daily_task_report_job()
    except Exception as e:
        log.error(f"[daily-task-cron] failed: {e}", exc_info=True)


# ---------------- Scheduler ----------------

def start_scheduler():
    """Set up APScheduler with both crons. Returns the scheduler or None."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        log.warning("[scheduler] APScheduler not installed — jobs won't run")
        return None

    try:
        import pytz
        tz = pytz.timezone(os.getenv("TIMEZONE", "Asia/Kolkata"))
    except Exception:
        tz = None

    sched = BackgroundScheduler(timezone=tz) if tz else BackgroundScheduler()

    # Missed-day alert: 10:00 AM IST
    missed_time = os.getenv("MISSED_DAY_ALERT_TIME", "10:00")
    try:
        h, m = missed_time.split(":")
        sched.add_job(
            _missed_day_alert,
            trigger=CronTrigger(hour=int(h), minute=int(m), timezone=tz),
            id="missed_day_alert",
            replace_existing=True,
        )
        log.info(f"[scheduler] missed_day_alert scheduled at {missed_time} IST daily")
    except Exception as e:
        log.error(f"[scheduler] failed to schedule missed-day alert: {e}")

    # Daily task report: 10:00 AM IST
    task_time = os.getenv("DAILY_TASK_REPORT_TIME", "10:00")
    try:
        h, m = task_time.split(":")
        sched.add_job(
            _daily_task_report_job,
            trigger=CronTrigger(hour=int(h), minute=int(m), timezone=tz),
            id="daily_task_report",
            replace_existing=True,
        )
        log.info(f"[scheduler] daily_task_report scheduled at {task_time} IST daily")
    except Exception as e:
        log.error(f"[scheduler] failed to schedule daily task report: {e}")

    sched.start()
    log.info("[scheduler] started")
    return sched
