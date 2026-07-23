"""Lightweight startup migrations for column additions.

Called from main.py on startup. Idempotent — safe to run every deploy.
Uses ALTER TABLE IF NOT EXISTS which never errors on existing schema.

Add new column additions here as we ship them.
"""
import logging
from sqlalchemy import text
from .database import engine

log = logging.getLogger(__name__)

# List of ALTER TABLE statements. Each is idempotent (IF NOT EXISTS).
# Add new ones at the bottom as features are shipped.
STARTUP_MIGRATIONS = [
    # --- 2A: task-report unlock support ---
    "ALTER TABLE unlock_requests ADD COLUMN IF NOT EXISTS kind VARCHAR(32) DEFAULT 'legacy_entry'",
    "ALTER TABLE unlock_requests ADD COLUMN IF NOT EXISTS decided_by_code VARCHAR(32)",
    # --- 5: monthly_reports columns ---
    "ALTER TABLE monthly_reports ADD COLUMN IF NOT EXISTS onedrive_path VARCHAR(1024)",
    "ALTER TABLE monthly_reports ADD COLUMN IF NOT EXISTS generated_by VARCHAR(255)",
    # --- 5-hotfix: kpis.target column (schema drift — original DB missing this) ---
    "ALTER TABLE kpis ADD COLUMN IF NOT EXISTS target FLOAT NOT NULL DEFAULT 0",
    # If your DB has monthly_target, copy it to target:
    "UPDATE kpis SET target = monthly_target WHERE target = 0 AND monthly_target IS NOT NULL",
    # Any future column additions go here.
]


# Some migrations are best-effort: if they reference columns/tables that don't
# exist, they should silently fail rather than crash startup.
OPTIONAL_MIGRATIONS = {
    "UPDATE kpis SET target = monthly_target WHERE target = 0 AND monthly_target IS NOT NULL",
}


def run_startup_migrations() -> None:
    """Apply pending column additions. Runs on every startup — safe.

    Each statement runs in its own transaction so a failure on one doesn't
    prevent the others from running.
    """
    for stmt in STARTUP_MIGRATIONS:
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
            log.info(f"[migrate] applied: {stmt[:100]}")
        except Exception as e:
            # Optional migrations (like the monthly_target copy) can fail silently
            if stmt in OPTIONAL_MIGRATIONS:
                log.info(f"[migrate] optional skipped: {stmt[:100]} — {e}")
            else:
                log.error(f"[migrate] FAILED: {stmt} — {e}")
