#!/usr/bin/env python3
"""Check whether the gatepass tables and columns exist in the live database.

Read-only. Run this when a module shows "Internal Server Error" — it says in
one line whether the cause is a missing schema.

    set "DATABASE_URL=<your Neon connection string>"
    python scripts\\check_schema.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.getenv("DATABASE_URL"):
    sys.exit("ERROR: DATABASE_URL is not set. Copy it from Vercel > Settings > "
             "Environment Variables and `set` it first.")

from sqlalchemy import inspect  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app import models  # noqa: F401,E402

insp = inspect(engine)
live_tables = set(insp.get_table_names())

missing_tables, missing_cols = [], []
for name, table in sorted(Base.metadata.tables.items()):
    if name not in live_tables:
        missing_tables.append(name)
        continue
    have = {c["name"] for c in insp.get_columns(name)}
    want = {c.name for c in table.columns}
    gap = sorted(want - have)
    if gap:
        missing_cols.append((name, gap))

W = 72
print("=" * W)
print("SCHEMA CHECK")
print("=" * W)
print(f"tables defined in code : {len(Base.metadata.tables)}")
print(f"tables found in the DB : {len(live_tables & set(Base.metadata.tables))}")

if missing_tables:
    print(f"\n[!] MISSING TABLES ({len(missing_tables)})")
    for t in missing_tables:
        print(f"    {t}")
else:
    print("\n[ok] Every table exists.")

if missing_cols:
    print(f"\n[!] MISSING COLUMNS ({len(missing_cols)} table(s))")
    for t, cols in missing_cols:
        print(f"    {t}: {', '.join(cols)}")
else:
    print("[ok] Every column exists.")

if missing_tables or missing_cols:
    print("\n" + "-" * W)
    print("FIX — run this once from the repo root, with DATABASE_URL still set:")
    print()
    print('  python -c "from app.database import Base, engine; import app.models; '
          'Base.metadata.create_all(bind=engine); '
          'from app.startup_migrations import run_startup_migrations; '
          'run_startup_migrations()"')
    print()
    print("Then re-run this script — it should report everything present.")
    print("-" * W)
    sys.exit(1)

print("\nSchema is up to date. If a page still errors, the cause is elsewhere —")
print("check the Vercel runtime logs for the traceback.")
