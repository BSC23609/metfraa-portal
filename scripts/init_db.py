"""Metfraa KPI Tracker — init_db.py

Post-Phase-1A: employees are populated by the migration script, not here.
This file now only ensures tables exist and imports all models so
SQLAlchemy sees the full schema on startup.

The old seed logic is preserved but disabled — if you ever need to
re-seed a fresh DB from scratch, set INIT_DB_SEED=1 in the environment
and manually adapt the seed function to the current Employee schema.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, engine
# Import ALL models so create_all sees the full schema
from app.models import (
    Employee, KPI, DailyEntry, KPIEntry,
    MonthlyReport, UnlockRequest, AuditLog, PasswordResetRequest,
)


def create_tables():
    """Create any missing tables. Idempotent — safe to run on every deploy."""
    print("Initializing Metfraa KPI Tracker database...")
    Base.metadata.create_all(bind=engine)
    print("✓ Tables created / verified")


def main():
    create_tables()
    if os.getenv("INIT_DB_SEED") == "1":
        print("INIT_DB_SEED=1 requested but no seed logic is active in v2.")
        print("Employees are managed via scripts/migrate_v2.py and the admin panel.")
    print("✓ Database ready")


if __name__ == "__main__":
    main()
