"""Lightweight startup migrations for column additions.

Called from main.py on startup. Idempotent — safe to run every deploy.
Uses ALTER TABLE IF NOT EXISTS which never errors on existing schema.

Add new column additions here as we ship them.
"""
import logging
import time as _time
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
    # --- 6-hotfix: legacy monthly_target column blocked new KPI inserts ---
    # Drop NOT NULL so new rows (which only write to `target`) can be inserted.
    # Optional: fully drop the column once you've verified no code reads it.
    "ALTER TABLE kpis ALTER COLUMN monthly_target DROP NOT NULL",
    # --- 6: KPI direction + bonus support ---
    "ALTER TABLE kpis ADD COLUMN IF NOT EXISTS direction VARCHAR(16) NOT NULL DEFAULT 'higher_better'",
    "ALTER TABLE kpis ADD COLUMN IF NOT EXISTS allow_bonus BOOLEAN NOT NULL DEFAULT FALSE",
    # Any future column additions go here.
]


# Some migrations are best-effort: if they reference columns/tables that don't
# exist, they should silently fail rather than crash startup.
OPTIONAL_MIGRATIONS = {
    "UPDATE kpis SET target = monthly_target WHERE target = 0 AND monthly_target IS NOT NULL",
    # monthly_target may not exist on fresh DBs — that's fine
    "ALTER TABLE kpis ALTER COLUMN monthly_target DROP NOT NULL",
}


# --- Expense parity Slice 0: advance chain, period lock, consolidation ---
EXPENSE_PARITY_MIGRATIONS = [
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS advance_stage VARCHAR(24)",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS advance_hr_verified_by VARCHAR(200)",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS advance_hr_verified_at VARCHAR(32)",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS advance_mgmt_approved_by VARCHAR(200)",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS advance_mgmt_approved_at VARCHAR(32)",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS advance_paid_by VARCHAR(200)",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS advance_paid_at VARCHAR(32)",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS trip_end_date VARCHAR(32)",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS late_settlement BOOLEAN DEFAULT FALSE",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS late_hours DOUBLE PRECISION",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS differential_amount DOUBLE PRECISION",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS deadline_bypass BOOLEAN DEFAULT FALSE",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS purpose_category VARCHAR(32)",
    "ALTER TABLE expense_submissions ADD COLUMN IF NOT EXISTS purpose_other_reason TEXT",
    "CREATE INDEX IF NOT EXISTS ix_expense_submissions_advance_stage ON expense_submissions (advance_stage)",
    "CREATE INDEX IF NOT EXISTS ix_expense_submissions_purpose_category ON expense_submissions (purpose_category)",
    # Existing open advances predate the 3-stage chain; they sit at the pay step.
    "UPDATE expense_submissions SET advance_stage = 'accounts_pay' "
    "WHERE form_type = 'met_advance' AND status = 'advance_approved' AND advance_stage IS NULL",
]
EXPENSE_PARITY_MIGRATIONS += [
    "ALTER TABLE expense_monthly_payments ADD COLUMN IF NOT EXISTS email_sent_at VARCHAR(32)",
    "ALTER TABLE expense_monthly_payments ADD COLUMN IF NOT EXISTS email_error TEXT",
    "CREATE INDEX IF NOT EXISTS ix_expense_pending_uploads_token "
    "ON expense_pending_uploads (upload_token)",
]
# MonthlyReport.payload was declared on the model but never given a migration,
# so it exists in code and not in the database. Nothing reads or writes it
# today, but any query loading the whole model would fail on Postgres — the
# same class of break that took out the gatepass page.
MISC_MIGRATIONS = [
    "ALTER TABLE monthly_reports ADD COLUMN IF NOT EXISTS payload JSONB",
]

GATEPASS_MIGRATIONS = [
    "ALTER TABLE outpass_requests ADD COLUMN IF NOT EXISTS action_token VARCHAR(64)",
    "ALTER TABLE outpass_requests ADD COLUMN IF NOT EXISTS pdf_token VARCHAR(64)",
    "ALTER TABLE outpass_requests ADD COLUMN IF NOT EXISTS return_token VARCHAR(64)",
    "ALTER TABLE outpass_requests ADD COLUMN IF NOT EXISTS returned_via VARCHAR(16)",
    "ALTER TABLE outpass_requests ADD COLUMN IF NOT EXISTS return_verified BOOLEAN DEFAULT FALSE",
    "ALTER TABLE outpass_requests ADD COLUMN IF NOT EXISTS return_lat DOUBLE PRECISION",
    "ALTER TABLE outpass_requests ADD COLUMN IF NOT EXISTS return_lng DOUBLE PRECISION",
    "ALTER TABLE outpass_requests ADD COLUMN IF NOT EXISTS return_accuracy_m DOUBLE PRECISION",
    "ALTER TABLE outpass_requests ADD COLUMN IF NOT EXISTS return_distance_m INTEGER",
    "CREATE INDEX IF NOT EXISTS idx_outpass_return_token ON outpass_requests(return_token)",
    "CREATE INDEX IF NOT EXISTS idx_outpass_action_token ON outpass_requests(action_token)",
    "CREATE INDEX IF NOT EXISTS idx_outpass_pdf_token ON outpass_requests(pdf_token)",
    "CREATE INDEX IF NOT EXISTS idx_wa_log_created ON wa_log(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_outpass_open ON outpass_requests(returned_at) "
    "WHERE returned_at IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_outpass_expected ON outpass_requests(expected_back_at)",
]
STARTUP_MIGRATIONS = (STARTUP_MIGRATIONS + EXPENSE_PARITY_MIGRATIONS
                      + GATEPASS_MIGRATIONS + MISC_MIGRATIONS)


def run_startup_migrations() -> None:
    """Apply pending column additions. Runs on every startup — safe.

    Each statement runs in its own transaction so a failure on one doesn't
    prevent the others from running.
    """
    # One connection for every statement. Under NullPool (serverless) a fresh
    # engine.begin() per statement opens a new TLS connection to Neon, so 12
    # statements meant 12 round-trip handshakes on every cold start.
    _t0 = _time.time()
    with engine.connect() as conn:
        for stmt in STARTUP_MIGRATIONS:
            try:
                with conn.begin():
                    conn.execute(text(stmt))
                log.info(f"[migrate] applied: {stmt[:100]}")
            except Exception as e:
                # Optional migrations (like the monthly_target copy) can fail silently
                if stmt in OPTIONAL_MIGRATIONS:
                    log.info(f"[migrate] optional skipped: {stmt[:100]} — {e}")
                else:
                    log.error(f"[migrate] FAILED: {stmt} — {e}")
    log.warning(
        f"[migrate] startup migrations ran in {_time.time() - _t0:.2f}s. "
        "This runs on EVERY cold start while INIT_DB is set — "
        "unset INIT_DB in Vercel now that the schema is current."
    )
