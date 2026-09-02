#!/usr/bin/env python3
"""Team Get Together 2026 — one-shot setup: create tables + seed the register.

Run from the repo root with DATABASE_URL pointing at Neon (the POOLED endpoint):

    DATABASE_URL=postgresql://... python scripts/tgt26_setup.py

Idempotent: re-running upserts family counts without touching check-ins or
sent stamps, so it's also how a pass CHANGE gets applied after regeneration.
"""
import csv
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import engine, SessionLocal  # noqa: E402
from app.models import Base, Tgt26Pass         # noqa: E402


def main() -> None:
    Base.metadata.create_all(
        bind=engine,
        tables=[Tgt26Pass.__table__,
                Base.metadata.tables["tgt26_change_requests"]])
    rows = list(csv.DictReader(
        open(pathlib.Path(__file__).parent / "tgt26_manifest.csv")))
    db = SessionLocal()
    created = updated = 0
    try:
        for m in rows:
            p = db.query(Tgt26Pass).filter_by(pass_id=m["pass_id"]).first()
            vals = dict(sno=int(m["sno"]), company=m["comp"], name=m["name"],
                        designation=m["desig"], department=m["dept"],
                        spouse=m["spouse"] == "Y", k5=int(m["k5"]),
                        k12=int(m["k12"]), k12p=int(m["k12p"]),
                        total_attendees=int(m["total"]), mobile=m["mobile"])
            if p:
                for k, v in vals.items():
                    setattr(p, k, v)
                updated += 1
            else:
                db.add(Tgt26Pass(pass_id=m["pass_id"], **vals))
                created += 1
        db.commit()
    finally:
        db.close()
    print(f"tgt26_passes: {created} created, {updated} updated "
          f"({len(rows)} rows in manifest)")


if __name__ == "__main__":
    main()
